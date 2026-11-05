from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import can_reject
from core.http import paginate, querystring
from machines.services import visible_machines
from rework.models import ReworkRequest
from workflow.engine import WorkflowError, reachable_rework_targets, reject_machine


@login_required
def rework_list(request):
    queryset = ReworkRequest.objects.select_related("machine", "assigned_phase", "rejected_phase", "rejected_by")
    if not request.user.is_management and request.user.role != "QC":
        queryset = queryset.filter(assigned_phase__department=request.user.department)
    status = request.GET.get("status") or ""
    if status:
        queryset = queryset.filter(status=status)
    query = (request.GET.get("q") or "").strip()
    if query:
        queryset = queryset.filter(Q(rework_code__icontains=query) | Q(machine__machine_id__icontains=query) | Q(reason__icontains=query))
    return render(
        request,
        "rework/list.html",
        {
            "page": paginate(request, queryset),
            "querystring": querystring(request),
            "statuses": ReworkRequest.Status.choices,
            "selected": status,
            "query": query,
        },
    )


@login_required
def rework_detail(request, pk):
    item = get_object_or_404(
        ReworkRequest.objects.select_related("machine", "assigned_phase", "rejected_phase", "rejected_by").prefetch_related(
            "actions__corrected_by", "attachments"
        ),
        pk=pk,
    )
    return render(request, "rework/detail.html", {"item": item})


@login_required
def rework_create(request, machine_id):
    machine = get_object_or_404(visible_machines(request.user), machine_id=machine_id)
    if not can_reject(request.user, machine):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied
    targets = reachable_rework_targets(machine)
    if request.method == "POST":
        try:
            item = reject_machine(
                machine,
                request.user,
                request.POST.get("target_phase", ""),
                request.POST.get("reason", ""),
                attachment_files=request.FILES.getlist("evidence"),
            )
        except WorkflowError as exc:
            return render(request, "rework/form.html", {"machine": machine, "targets": targets, "error": str(exc)})
        return redirect("rework:detail", item.pk)
    return render(request, "rework/form.html", {"machine": machine, "targets": targets})
