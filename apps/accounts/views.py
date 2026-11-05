from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.db.models import Case, IntegerField, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import management_required
from accounts.forms import SettingsForm, UserForm
from accounts.models import CompanyLogo, User, get_setting, set_setting
from audit.utils import log_audit
from core.constants import Roles
from core.forms import style_form
from core.http import paginate, querystring


DEMO_PASSWORD = "IrDemo@2026"
DEMO_USERNAMES = (
    "superadmin",
    "admin",
    "planning1",
    "planning2",
    "planner1",
    "planner2",
    "leader1",
    "leader2",
    "assembly1",
    "assembly2",
    "electrical1",
    "electrical2",
    "testing1",
    "testing2",
    "eol1",
    "eol2",
    "qc1",
    "qc2",
)


def demo_accounts():
    if not settings.DEBUG:
        return []
    role_order = [Roles.SUPER_ADMIN, Roles.ADMIN, *Roles.PHASE_ROLES]
    ordering = Case(
        *[When(role=role, then=Value(index)) for index, role in enumerate(role_order)],
        default=Value(len(role_order)),
        output_field=IntegerField(),
    )
    return list(
        User.objects.filter(is_active=True, username__in=DEMO_USERNAMES).order_by(ordering, "username")
    )


def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    form = AuthenticationForm(request, data=request.POST or None)
    style_form(form)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        target = request.POST.get("next") or request.GET.get("next")
        if not target or not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
            target = reverse("core:dashboard")
        return redirect(target)
    return render(
        request,
        "accounts/login.html",
        {"form": form, "quick_accounts": demo_accounts(), "demo_password": DEMO_PASSWORD},
    )


@require_POST
def logout_view(request):
    logout(request)
    return redirect("accounts:login")


@login_required
def profile(request):
    return render(request, "accounts/profile.html")


@login_required
def password_change(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    style_form(form)
    if request.method == "POST" and form.is_valid():
        form.save()
        login(request, request.user)
        messages.success(request, "Password updated.")
        return redirect("accounts:profile")
    return render(request, "accounts/password.html", {"form": form})


@management_required
def user_list(request):
    queryset = User.objects.select_related("department")
    role = request.GET.get("role") or ""
    query = (request.GET.get("q") or "").strip()
    if role:
        queryset = queryset.filter(role=role)
    if query:
        from django.db.models import Q

        queryset = queryset.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(employee_id__icontains=query)
        )
    return render(
        request,
        "accounts/user_list.html",
        {
            "page": paginate(request, queryset),
            "querystring": querystring(request),
            "roles": Roles.CHOICES,
            "selected_role": role,
            "query": query,
        },
    )


@management_required
def user_edit(request, pk=None):
    user = get_object_or_404(User, pk=pk) if pk else None
    form = UserForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        if user and user == request.user and not form.cleaned_data.get("is_active"):
            messages.error(request, "You cannot deactivate your own account.")
        elif user and user.role == Roles.SUPER_ADMIN and form.cleaned_data.get("role") != Roles.SUPER_ADMIN:
            remaining = User.objects.filter(role=Roles.SUPER_ADMIN, is_active=True).exclude(pk=user.pk).count()
            if remaining == 0:
                messages.error(request, "Keep at least one active super admin.")
            else:
                saved = form.save()
                log_audit(request.user, "user.update", instance=saved, request=request)
                messages.success(request, f"User {saved.username} saved.")
                return redirect("accounts:users")
        else:
            saved = form.save()
            if saved.role == Roles.SUPER_ADMIN:
                saved.is_superuser = True
                saved.is_staff = True
                saved.save(update_fields=["is_superuser", "is_staff"])
            log_audit(request.user, "user.create" if user is None else "user.update", instance=saved, request=request)
            messages.success(request, f"User {saved.username} saved.")
            return redirect("accounts:users")
    return render(request, "accounts/user_form.html", {"form": form, "edited_user": user})


@management_required
@require_POST
def user_toggle(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect("accounts:users")
    if user.role == Roles.SUPER_ADMIN and user.is_active:
        remaining = User.objects.filter(role=Roles.SUPER_ADMIN, is_active=True).exclude(pk=user.pk).count()
        if remaining == 0:
            messages.error(request, "Keep at least one active super admin.")
            return redirect("accounts:users")
    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    log_audit(request.user, "user.toggle", instance=user, changes={"is_active": user.is_active}, request=request)
    messages.success(request, f"{user.username} is now {'active' if user.is_active else 'inactive'}.")
    return redirect("accounts:users")


@management_required
def settings_view(request):
    initial = {
        "company_name": get_setting("company_name", "Ingersoll Rand"),
        "machine_id_prefix": get_setting("machine_id_prefix", "IR-MCH-"),
        "duplicate_fields": get_setting("duplicate_fields", "work_order,ccn,model_description"),
        "retention_note": get_setting("retention_note", ""),
    }
    form = SettingsForm(request.POST or None, request.FILES or None, initial=None if request.method == "POST" else initial)
    if request.method == "POST" and form.is_valid():
        for key, value in form.cleaned_data.items():
            if key == "logo":
                continue
            set_setting(key, value.strip(), user=request.user, label=form.fields[key].label)
        upload = form.cleaned_data.get("logo")
        if upload:
            CompanyLogo.objects.create(image=upload, updated_by=request.user)
        log_audit(request.user, "settings.update", changes={"settings": True, "logo": bool(upload)}, request=request)
        messages.success(request, "System settings saved.")
        return redirect("accounts:settings")
    return render(request, "accounts/settings.html", {"form": form, "logo": CompanyLogo.objects.order_by("-pk").first()})
