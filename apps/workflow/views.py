from django.contrib import messages
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import management_required
from accounts.permissions import can_operate_phase
from audit.utils import log_audit
from core.constants import TEST_AREAS, PHASE_ROLE, PhaseCode, PhaseStatus
from core.http import paginate, querystring
from machines.forms import ProductionReleaseForm
from machines.floor import stations_by_line
from machines.models import ProductionStation
from machines.services import visible_machines
from workflow.engine import WorkflowError, production_release, release_serial_and_station
from workflow.models import ProductionPhase


def _guard(user, phase_code):
    if user.is_management or user.role == PHASE_ROLE.get(phase_code):
        return
    raise PermissionDenied


@login_required
def planner_queue(request):
    """Serial number + station together (also covers machines that only need a station)."""
    _guard(request.user, PhaseCode.PLANNER)
    if request.method == "POST":
        selected = request.POST.getlist("machines")
        if not selected:
            messages.error(request, "Tick at least one machine, then enter its serial and station.")
            return redirect("workflow:planner")
        done = 0
        for machine_id in selected:
            machine = visible_machines(request.user).filter(machine_id=machine_id).first()
            if machine is None:
                continue
            station = ProductionStation.objects.filter(
                pk=request.POST.get(f"station_{machine_id}"),
                is_active=True,
            ).first()
            serial = request.POST.get(f"serial_{machine_id}", "")
            try:
                release_serial_and_station(
                    machine,
                    request.user,
                    serial,
                    station,
                    production_serial=serial,
                    remarks="",
                )
                done += 1
            except WorkflowError as exc:
                messages.error(request, f"{machine.machine_id}: {exc}")
        if done:
            messages.success(
                request,
                f"{done} machine{'s' if done != 1 else ''} given a serial and station — Assembly and Electrical are open.",
            )
        return redirect("workflow:planner")
    queryset = (
        visible_machines(request.user)
        .filter(
            Q(phase_states__phase__code=PhaseCode.PLANNER, phase_states__status=PhaseStatus.IN_PROGRESS)
            | Q(phase_states__phase__code=PhaseCode.PRODUCTION, phase_states__status=PhaseStatus.IN_PROGRESS)
        )
        .distinct()
        .select_related("planning", "station")
        .prefetch_related("phase_states__phase")
        .order_by("machine_id")
    )
    query = (request.GET.get("q") or "").strip()
    if query:
        queryset = queryset.filter(
            Q(machine_id__icontains=query)
            | Q(planning__work_order__icontains=query)
            | Q(planner_serial__icontains=query)
        )
    focus = (request.GET.get("focus") or "").strip()
    page = paginate(request, queryset)
    rows = []
    for machine in page.object_list:
        states = {state.phase.code: state.status for state in machine.phase_states.all()}
        rows.append(
            {
                "machine": machine,
                "needs_serial": states.get(PhaseCode.PLANNER) == PhaseStatus.IN_PROGRESS,
            }
        )
    return render(
        request,
        "workflow/planner.html",
        {
            "page": page,
            "rows": rows,
            "querystring": querystring(request),
            "query": query,
            "focus": focus,
            "station_groups": stations_by_line(),
        },
    )


@login_required
def production_queue(request):
    """Legacy / rework station-only queue; main path is Serial numbers (planner)."""
    _guard(request.user, PhaseCode.PRODUCTION)
    if request.method == "POST":
        station = ProductionStation.objects.filter(pk=request.POST.get("station"), is_active=True).first()
        done = 0
        for machine_id in request.POST.getlist("machines"):
            machine = visible_machines(request.user).filter(machine_id=machine_id).first()
            if machine is None:
                continue
            try:
                production_release(
                    machine,
                    request.user,
                    station,
                    production_serial=request.POST.get(f"pserial_{machine_id}", ""),
                    remarks=request.POST.get("remarks", ""),
                )
                done += 1
            except WorkflowError as exc:
                messages.error(request, f"{machine.machine_id}: {exc}")
        if done:
            messages.success(request, f"{done} machine{'s' if done != 1 else ''} released to Assembly and Electrical.")
        return redirect("workflow:production")
    queryset = visible_machines(request.user).filter(
        phase_states__phase__code=PhaseCode.PRODUCTION,
        phase_states__status=PhaseStatus.IN_PROGRESS,
    ).distinct()
    return render(
        request,
        "workflow/production_list.html",
        {
            "page": paginate(request, queryset),
            "station_groups": stations_by_line(),
            "querystring": querystring(request),
        },
    )


@login_required
def production_machine(request, machine_id):
    _guard(request.user, PhaseCode.PRODUCTION)
    machine = get_object_or_404(visible_machines(request.user), machine_id=machine_id)
    form = ProductionReleaseForm(
        request.POST or None,
        initial={"production_serial": machine.production_serial or "", "remarks": machine.production_remarks},
    )
    if request.method == "POST" and form.is_valid():
        try:
            production_release(
                machine,
                request.user,
                form.cleaned_data["station"],
                production_serial=form.cleaned_data.get("production_serial", ""),
                remarks=form.cleaned_data.get("remarks", ""),
            )
        except WorkflowError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"{machine.machine_id} is now with Assembly and Electrical.")
            return redirect("machines:detail", machine.machine_id)
    return render(
        request,
        "workflow/production_form.html",
        {"form": form, "machine": machine, "station_groups": stations_by_line()},
    )


@login_required
def phase_queue(request, phase_code):
    phase = get_object_or_404(ProductionPhase, code=phase_code, is_active=True)
    if phase_code not in PhaseCode.JOB_CARDS and phase_code != PhaseCode.WAITING:
        raise PermissionDenied
    _guard(request.user, phase_code)
    tab = request.GET.get("tab") or "open"
    # Both conditions must match the same phase row. Separate filter() calls
    # would join twice and show machines that are open in a different phase.
    state_filter = {"phase_states__phase": phase}
    if tab == "done":
        state_filter["phase_states__status"] = PhaseStatus.COMPLETED
    elif tab == "rework" and phase_code != PhaseCode.WAITING:
        state_filter["phase_states__status"] = PhaseStatus.IN_PROGRESS
        state_filter["phase_states__rework_open"] = True
    else:
        state_filter["phase_states__status"] = PhaseStatus.IN_PROGRESS
        tab = "open"
    queryset = visible_machines(request.user).filter(**state_filter)
    query = (request.GET.get("q") or "").strip()
    if query:
        queryset = queryset.filter(Q(machine_id__icontains=query) | Q(planning__work_order__icontains=query))
    return render(
        request,
        "workflow/waiting_queue.html" if phase_code == PhaseCode.WAITING else "workflow/phase_queue.html",
        {
            "phase": phase,
            "tab": tab,
            "page": paginate(request, queryset.distinct()),
            "query": query,
            "querystring": querystring(request),
            "can_act": can_operate_phase(request.user, phase_code),
            "test_areas": TEST_AREAS,
        },
    )


@management_required
def phase_settings(request):
    return render(request, "workflow/phases.html", {"phases": ProductionPhase.objects.select_related("department")})


@management_required
def phase_edit(request, pk):
    phase = get_object_or_404(ProductionPhase, pk=pk)
    if request.method == "POST":
        phase.name = (request.POST.get("name") or phase.name).strip()[:120]
        phase.description = (request.POST.get("description") or "").strip()
        phase.save(update_fields=["name", "description"])
        log_audit(request.user, "phase.update", instance=phase, request=request)
        messages.success(request, "Phase name updated. The sequence stays fixed so machines cannot skip a stage.")
        return redirect("workflow:phases")
    return render(request, "workflow/phase_form.html", {"phase": phase})
