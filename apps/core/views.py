from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from accounts.decorators import management_required
from accounts.permissions import can_operate_phase
from core.constants import PhaseCode, PhaseStatus, Roles
from core.navigation import home_phase
from core.stats import CARD_META, STAGE_LABELS, admin_stats, department_stats, machines_for_card
from machines.floor import floor_board
from machines.services import visible_machines
from workflow.models import ProductionPhase, WorkflowEvent
from workflow.presenters import pipeline_label


def health(request):
    return HttpResponse("ok")


def permission_denied_page(request, exception):
    return render(request, "403.html", status=403)


def not_found_page(request, exception):
    return render(request, "404.html", status=404)


@management_required
def machine_analytics(request):
    return render(request, "core/analytics.html", floor_board())


@management_required
def dashboard_card(request, key):
    card = CARD_META.get(key)
    machines = machines_for_card(key)
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
        {"card": card, "key": key, "machines": machines, "note": note, "count": machines.count()},
    )


@login_required
def dashboard(request):
    phase_code = home_phase(request.user)
    if phase_code is None:
        recent = list(visible_machines(request.user).prefetch_related("phase_states__phase")[:8])
        for machine in recent:
            machine.pipeline = pipeline_label(machine)
        return render(
            request,
            "core/dashboard_admin.html",
            {
                "stats": admin_stats(),
                "recent": recent,
                "events": WorkflowEvent.objects.select_related("machine", "actor", "phase")[:10],
            },
        )
    phase = ProductionPhase.objects.filter(code=phase_code).first()
    queue = visible_machines(request.user).filter(
        phase_states__phase__code=phase_code,
        phase_states__status=PhaseStatus.IN_PROGRESS,
    ).distinct()[:8]
    if phase_code == PhaseCode.PLANNING:
        queue_url = reverse("machines:list")
    elif phase_code == PhaseCode.PLANNER:
        queue_url = reverse("workflow:planner")
    elif phase_code == PhaseCode.PRODUCTION:
        queue_url = reverse("workflow:production")
    else:
        queue_url = reverse("workflow:phase", args=[phase_code])
    serial_queue = []
    serial_url = ""
    if request.user.role == Roles.PRODUCTION_LEADER:
        serial_queue = list(
            visible_machines(request.user)
            .filter(phase_states__phase__code=PhaseCode.PLANNER, phase_states__status=PhaseStatus.IN_PROGRESS)
            .distinct()[:8]
        )
        serial_url = reverse("workflow:planner")
    return render(
        request,
        "core/dashboard_department.html",
        {
            "phase": phase,
            "stats": department_stats(phase_code),
            "queue": queue,
            "queue_url": queue_url,
            "serial_queue": serial_queue,
            "serial_url": serial_url,
            "can_act": can_operate_phase(request.user, phase_code),
            "role_name": request.user.role_label,
        },
    )
