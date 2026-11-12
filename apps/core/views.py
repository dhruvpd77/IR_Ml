from calendar import month_name
from datetime import datetime
from urllib.parse import urlencode

from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from accounts.decorators import board_viewer_required, management_required, super_admin_required
from accounts.permissions import can_operate_phase
from core.constants import PhaseCode, PhaseStatus, Roles
from core.navigation import home_phase
from core.stats import (
    CARD_META,
    DEPARTMENT_CARDS,
    STAGE_LABELS,
    admin_stats,
    department_cards,
    details_analytics,
    machines_for_card,
    machines_for_department_card,
    scoped_machines,
)
from machines.floor import floor_board, floor_board_payload
from machines.forms import COMPANY_CHOICES, SHIFT_CHOICES, TYPE_CHOICES
from machines.models import MonthlyTentativePlan
from machines.services import visible_machines
from workflow.models import ProductionPhase, WorkflowEvent
from workflow.presenters import pipeline_label


def chosen_machine_type(request):
    chosen = (request.GET.get("type") or request.POST.get("type") or "").strip()
    allowed = {code for code, _label in TYPE_CHOICES}
    return chosen if chosen in allowed else ""


def chosen_shift(request):
    shift = (request.GET.get("shift") or "").strip()
    allowed = {code for code, _label in SHIFT_CHOICES}
    return shift if shift in allowed else ""


def parse_month(raw):
    text = (raw or "").strip()
    if len(text) == 7 and text[4] == "-":
        try:
            year, month = int(text[:4]), int(text[5:7])
        except ValueError:
            return None
        if 1 <= month <= 12 and 2000 <= year <= 2100:
            return year, month
    return None


def chosen_month(request):
    parsed = parse_month(request.GET.get("month") or request.POST.get("month"))
    if parsed:
        return parsed
    today = timezone.localdate()
    return today.year, today.month


def chosen_day(request):
    raw = (request.GET.get("date") or "").strip()
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            pass
    return timezone.localdate()


def month_bounds(year, month):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime(year, month, 1), tz)
    if month == 12:
        end = timezone.make_aware(datetime(year + 1, 1, 1), tz)
    else:
        end = timezone.make_aware(datetime(year, month + 1, 1), tz)
    return start, end


def month_options(back=18, forward=6):
    today = timezone.localdate()
    year, month = today.year, today.month
    points = []
    cursor_year, cursor_month = year, month
    for _ in range(back):
        cursor_month -= 1
        if cursor_month == 0:
            cursor_month = 12
            cursor_year -= 1
        points.append((cursor_year, cursor_month))
    points.reverse()
    points.append((year, month))
    cursor_year, cursor_month = year, month
    for _ in range(forward):
        cursor_month += 1
        if cursor_month == 13:
            cursor_month = 1
            cursor_year += 1
        points.append((cursor_year, cursor_month))
    return [{"value": f"{item_year:04d}-{item_month:02d}", "label": f"{month_name[item_month]} {item_year}"} for item_year, item_month in points]


def dashboard_query(machine_type="", month="", day="", shift="", scope=""):
    params = {}
    if scope:
        params["scope"] = scope
    if month:
        params["month"] = month
    if day:
        params["date"] = day
    if shift:
        params["shift"] = shift
    if machine_type:
        params["type"] = machine_type
    return urlencode(params)


@require_GET
@never_cache
def service_worker(request):
    """Serve the PWA service worker from site root so it can control the whole app."""
    path = Path(settings.BASE_DIR) / "static" / "js" / "sw.js"
    if not path.exists():
        raise Http404("Service worker missing.")
    response = FileResponse(path.open("rb"), content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response


@require_GET
def web_manifest(request):
    path = Path(settings.BASE_DIR) / "static" / "manifest.webmanifest"
    if not path.exists():
        raise Http404("Manifest missing.")
    return FileResponse(path.open("rb"), content_type="application/manifest+json")


def health(request):
    return HttpResponse("ok")


def permission_denied_page(request, exception):
    return render(request, "403.html", status=403)


def not_found_page(request, exception):
    return render(request, "404.html", status=404)


@board_viewer_required
def machine_analytics(request):
    shift = chosen_shift(request)
    on_date = None
    start = end = None
    month_value = ""
    day_value = ""
    raw_date = (request.GET.get("date") or "").strip()
    if raw_date:
        try:
            on_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            day_value = on_date.isoformat()
        except ValueError:
            on_date = None
    else:
        parsed = parse_month(request.GET.get("month"))
        if parsed:
            start, end = month_bounds(*parsed)
            month_value = f"{parsed[0]:04d}-{parsed[1]:02d}"
    if request.GET.get("live") == "1":
        payload = floor_board_payload(start=start, end=end, on_date=on_date, shift=shift)
        payload["updated"] = timezone.localtime().strftime("%d %b %Y %H:%M:%S")
        return JsonResponse(payload)
    context = floor_board(start=start, end=end, on_date=on_date, shift=shift)
    context.update(
        {
            "months": month_options(),
            "shifts": SHIFT_CHOICES,
            "selected_month": month_value,
            "selected_date": day_value,
            "selected_shift": shift,
            "live_refresh": True,
        }
    )
    return render(request, "core/analytics.html", context)


@board_viewer_required
def details_analytics_view(request):
    shift = chosen_shift(request)
    machine_type = chosen_machine_type(request)
    company = (request.GET.get("company") or "").strip()
    allowed_companies = {code for code, _label in COMPANY_CHOICES}
    if company not in allowed_companies:
        company = ""
    on_date = None
    start = end = None
    month_value = ""
    day_value = ""
    raw_date = (request.GET.get("date") or "").strip()
    if raw_date:
        try:
            on_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            day_value = on_date.isoformat()
        except ValueError:
            on_date = None
    else:
        parsed = parse_month(request.GET.get("month"))
        if parsed:
            start, end = month_bounds(*parsed)
            month_value = f"{parsed[0]:04d}-{parsed[1]:02d}"
    context = details_analytics(
        machine_type=machine_type,
        company=company,
        start=start,
        end=end,
        on_date=on_date,
        shift=shift,
    )
    context.update(
        {
            "months": month_options(),
            "shifts": SHIFT_CHOICES,
            "machine_types": TYPE_CHOICES,
            "companies": COMPANY_CHOICES,
            "selected_month": month_value,
            "selected_date": day_value,
            "selected_shift": shift,
            "selected_type": machine_type,
            "selected_company": company,
        }
    )
    return render(request, "core/details_analytics.html", context)


@board_viewer_required
def dashboard_card(request, key):
    machine_type = chosen_machine_type(request)
    scope = (request.GET.get("scope") or "").strip()
    shift = chosen_shift(request) if scope == "daily" else ""
    on_date = chosen_day(request) if scope == "daily" else None
    start = end = None
    month_value = ""
    day_value = ""
    if scope == "monthly":
        year, month = chosen_month(request)
        start, end = month_bounds(year, month)
        month_value = f"{year:04d}-{month:02d}"
    elif scope == "daily":
        day_value = on_date.isoformat()
    card = CARD_META.get(key)
    machines = machines_for_card(key, machine_type, start=start, end=end, on_date=on_date if scope == "daily" else None, shift=shift)
    if card is None or machines is None:
        raise Http404
    limit = card.get("limit")
    if limit == "REWORK":
        note = "View opens the job card through the phase that machine was sent back to."
    elif limit:
        note = f"View opens the job card through {STAGE_LABELS.get(limit, limit)} only."
    else:
        note = "View opens the full job card."
    return render(
        request,
        "core/dashboard_card.html",
        {
            "card": card,
            "key": key,
            "machines": machines,
            "note": note,
            "count": machines.count(),
            "machine_type": machine_type,
            "machine_types": TYPE_CHOICES,
            "filter_keep": dashboard_query(month=month_value, day=day_value, shift=shift, scope=scope),
            "dashboard_name": "Daily dashboard" if scope == "daily" else "Monthly dashboard",
            "dashboard_back": (
                reverse("core:daily" if scope == "daily" else "core:monthly")
                + "?"
                + dashboard_query(machine_type=machine_type, month=month_value, day=day_value, shift=shift)
            ),
        },
    )


@login_required
def department_card(request, key):
    machine_type = chosen_machine_type(request)
    phase_code = home_phase(request.user)
    card = next((item for item in DEPARTMENT_CARDS if item[0] == key), None)
    machines = machines_for_department_card(phase_code, key, machine_type) if phase_code and card else None
    if card is None or machines is None:
        raise Http404
    phase = ProductionPhase.objects.filter(code=phase_code).first()
    return render(
        request,
        "core/dashboard_department_card.html",
        {
            "card": {"label": card[1], "note": card[4]},
            "phase": phase,
            "machines": machines,
            "count": machines.count(),
            "machine_type": machine_type,
            "machine_types": TYPE_CHOICES,
        },
    )


def _render_management_dashboard(request, mode):
    machine_type = chosen_machine_type(request)
    shift = chosen_shift(request) if mode == "daily" else ""
    on_date = None
    start = end = None
    month_value = ""
    day_value = ""
    tentative = 0
    tentative_set = False
    if mode == "daily":
        day = chosen_day(request)
        on_date = day
        day_value = day.isoformat()
    else:
        year, month = chosen_month(request)
        start, end = month_bounds(year, month)
        month_value = f"{year:04d}-{month:02d}"
        plan = MonthlyTentativePlan.objects.filter(year=year, month=month).first()
        if plan:
            tentative = plan.machine_count
            tentative_set = True
    stats = admin_stats(
        machine_type,
        start=start,
        end=end,
        on_date=on_date,
        shift=shift,
        mode=mode,
        tentative=tentative,
        tentative_set=tentative_set,
    )
    machines = scoped_machines(machine_type, start=start, end=end, on_date=on_date, shift=shift)
    recent = list(machines.select_related("planning").prefetch_related("phase_states__phase").order_by("-created_at")[:8])
    for machine in recent:
        machine.pipeline = pipeline_label(machine)
    query = dashboard_query(machine_type=machine_type, month=month_value, day=day_value, shift=shift, scope=mode)
    for card in stats["cards"]:
        if card["key"] in {"tentative", "balance"}:
            card["href"] = ""
        else:
            card["href"] = f"{reverse('core:dashboard_card', args=[card['key']])}?{query}"
    events = list(
        WorkflowEvent.objects.select_related("machine", "actor", "phase")
        .filter(machine__in=machines.values("pk"))[:10]
    )
    context = {
        "stats": stats,
        "recent": recent,
        "events": events,
        "machine_type": machine_type,
        "machine_types": TYPE_CHOICES,
        "shifts": SHIFT_CHOICES,
        "selected_shift": shift,
        "months": month_options(),
        "selected_month": month_value,
        "selected_date": day_value,
        "mode": mode,
        "dashboard_title": "Monthly dashboard" if mode == "monthly" else "Daily dashboard",
        "dashboard_blurb": (
            "Tentative plan for the selected month, machines registered by the planning team, and where those machines are now."
            if mode == "monthly"
            else "Machines registered on the selected date. Shift is the 1st or 2nd shift chosen when the machine was registered."
        ),
        "filter_keep": dashboard_query(month=month_value, day=day_value, shift=shift),
        "live_refresh": True,
    }
    if request.GET.get("live") == "1":
        from core.templatetags.mqms import event_title

        return JsonResponse(
            {
                "cards": [
                    {
                        "key": card["key"],
                        "label": card["label"],
                        "value": card["value"],
                        "note": card.get("note") or "View machines",
                        "href": card.get("href") or "",
                        "tone": card.get("tone") or "navy",
                        "icon": card.get("icon") or "layers",
                    }
                    for card in stats["cards"]
                ],
                "charts": stats["charts"],
                "recent": [
                    {
                        "id": machine.machine_id,
                        "model": machine.planning.model_description if hasattr(machine, "planning") else "",
                        "pipeline": machine.pipeline,
                        "status": machine.status_label,
                        "url": reverse("machines:detail", args=[machine.machine_id]),
                    }
                    for machine in recent
                ],
                "events": [
                    {
                        "title": strip_tags(str(event_title(event))),
                        "detail": (
                            f"{event.machine.machine_id} · "
                            f"{(event.actor.display_name if event.actor_id else 'System')} · "
                            f"{timezone.localtime(event.created_at).strftime('%d %b, %H:%M')}"
                        ),
                    }
                    for event in events
                ],
                "updated": timezone.localtime().strftime("%d %b %Y %H:%M:%S"),
            }
        )
    return render(request, "core/dashboard_admin.html", context)


@board_viewer_required
def monthly_dashboard(request):
    return _render_management_dashboard(request, "monthly")


@board_viewer_required
def daily_dashboard(request):
    return _render_management_dashboard(request, "daily")


@board_viewer_required
def dashboard_slideshow(request):
    slides = [
        {"label": "Monthly dashboard", "url": f"{reverse('core:monthly')}?embed=1"},
        {"label": "Daily dashboard", "url": f"{reverse('core:daily')}?embed=1"},
        {"label": "Machine analytics", "url": f"{reverse('core:analytics')}?embed=1"},
        {"label": "Details analytics", "url": f"{reverse('core:details_analytics')}?embed=1"},
    ]
    return render(
        request,
        "core/slideshow.html",
        {
            "slides": slides,
            "slide_seconds": 15,
        },
    )


@super_admin_required
def tentative_plan(request):
    year, month = chosen_month(request)
    if request.method == "POST":
        parsed = parse_month(request.POST.get("month"))
        raw_count = (request.POST.get("machine_count") or "").strip()
        if parsed is None:
            messages.error(request, "Select a month.")
        else:
            year, month = parsed
            try:
                count = int(raw_count)
            except ValueError:
                messages.error(request, "Enter the tentative number of machines.")
            else:
                if count < 0:
                    messages.error(request, "The tentative number cannot be negative.")
                else:
                    MonthlyTentativePlan.objects.update_or_create(
                        year=year,
                        month=month,
                        defaults={"machine_count": count, "updated_by": request.user},
                    )
                    messages.success(request, f"{month_name[month]} {year} tentative plan saved as {count} machines.")
                    return redirect(f"{reverse('core:tentative')}?month={year:04d}-{month:02d}")
    plan = MonthlyTentativePlan.objects.filter(year=year, month=month).first()
    return render(
        request,
        "core/tentative_plan.html",
        {
            "months": month_options(),
            "selected_month": f"{year:04d}-{month:02d}",
            "selected_label": f"{month_name[month]} {year}",
            "machine_count": plan.machine_count if plan else "",
            "plans": MonthlyTentativePlan.objects.select_related("updated_by"),
        },
    )


@login_required
def dashboard(request):
    machine_type = chosen_machine_type(request)
    if request.user.is_general_user:
        return redirect("core:slideshow")
    phase_code = home_phase(request.user)
    if phase_code is None:
        target = reverse("core:monthly")
        if request.GET:
            target = f"{target}?{request.GET.urlencode()}"
        return redirect(target)
    phase = ProductionPhase.objects.filter(code=phase_code).first()
    queue = visible_machines(request.user).filter(
        phase_states__phase__code=phase_code,
        phase_states__status=PhaseStatus.IN_PROGRESS,
    )
    if machine_type:
        queue = queue.filter(planning__machine_type=machine_type)
    queue = queue.distinct()[:8]
    if phase_code == PhaseCode.PLANNING:
        queue_url = reverse("machines:list")
    elif phase_code in {PhaseCode.PLANNER, PhaseCode.PRODUCTION}:
        queue_url = reverse("workflow:planner")
    else:
        queue_url = reverse("workflow:phase", args=[phase_code])
    serial_queue = []
    serial_url = ""
    if request.user.role == Roles.PRODUCTION_LEADER:
        serial_qs = visible_machines(request.user).filter(
            Q(phase_states__phase__code=PhaseCode.PLANNER, phase_states__status=PhaseStatus.IN_PROGRESS)
            | Q(phase_states__phase__code=PhaseCode.PRODUCTION, phase_states__status=PhaseStatus.IN_PROGRESS)
        )
        if machine_type:
            serial_qs = serial_qs.filter(planning__machine_type=machine_type)
        serial_queue = list(serial_qs.distinct()[:8])
        serial_url = reverse("workflow:planner")
    return render(
        request,
        "core/dashboard_department.html",
        {
            "phase": phase,
            "cards": department_cards(phase_code, machine_type),
            "machine_type": machine_type,
            "machine_types": TYPE_CHOICES,
            "queue": queue,
            "queue_url": queue_url,
            "serial_queue": serial_queue,
            "serial_url": serial_url,
            "can_act": can_operate_phase(request.user, phase_code),
            "role_name": request.user.role_label,
        },
    )
