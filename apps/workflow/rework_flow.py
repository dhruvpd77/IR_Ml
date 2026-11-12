"""Path-based rework: Production station → optional Assembly/Testing/EOL → return to origin."""

from django.db import transaction
from django.utils import timezone

from accounts.permissions import can_operate_phase
from audit.utils import log_audit
from core.constants import EventType, MachineStatus, PhaseCode, PhaseStatus, Roles
from jobcards.services import JobCardError, persist_submission
from notifications.services import machine_label, machine_path, notify_roles
from rework.models import ReworkNote, ReworkRequest
from workflow.models import MachinePhaseState, ProductionPhase, WorkflowEvent

REWORK_ORIGINS = {
    PhaseCode.ASSEMBLY,
    PhaseCode.TESTING,
    PhaseCode.EOL,
    PhaseCode.QC,
}


class ReworkFlowError(Exception):
    pass


def rework_route(origin_code):
    """Phases after Production, ending with the origin (actual job card return)."""
    routes = {
        PhaseCode.ASSEMBLY: [PhaseCode.ASSEMBLY],
        PhaseCode.TESTING: [PhaseCode.ASSEMBLY, PhaseCode.WAITING, PhaseCode.TESTING],
        PhaseCode.EOL: [PhaseCode.ASSEMBLY, PhaseCode.WAITING, PhaseCode.TESTING, PhaseCode.EOL],
        PhaseCode.QC: [PhaseCode.ASSEMBLY, PhaseCode.WAITING, PhaseCode.TESTING, PhaseCode.EOL, PhaseCode.QC],
    }
    if origin_code not in routes:
        raise ReworkFlowError("Rework can be raised from Assembly, Testing, End of Line, or Quality.")
    return [PhaseCode.PRODUCTION, *routes[origin_code]]


def active_rework(machine):
    return (
        ReworkRequest.objects.filter(machine=machine, status=ReworkRequest.Status.OPEN)
        .select_related("rejected_phase", "assigned_phase", "rejected_by")
        .order_by("-pk")
        .first()
    )


def _phase(code):
    try:
        return ProductionPhase.objects.get(code=code, is_active=True)
    except ProductionPhase.DoesNotExist as exc:
        raise ReworkFlowError("That production phase is not configured.") from exc


def _state(machine, phase):
    state, _created = MachinePhaseState.objects.get_or_create(machine=machine, phase=phase)
    return state


def _event(machine, event_type, user, phase=None, remarks="", metadata=None, cycle=0):
    WorkflowEvent.objects.create(
        machine=machine,
        event_type=event_type,
        actor=user if getattr(user, "is_authenticated", False) else None,
        phase=phase,
        cycle=cycle,
        remarks=remarks or "",
        metadata=metadata or {},
    )


def _open_phase(machine, phase, user, *, new_cycle=False):
    state = _state(machine, phase)
    if new_cycle or state.status == PhaseStatus.COMPLETED:
        state.cycle += 1
    state.status = PhaseStatus.IN_PROGRESS
    state.started_at = timezone.now()
    state.started_by = user if getattr(user, "is_authenticated", False) else None
    state.completed_at = None
    state.completed_by = None
    state.save()
    _event(machine, EventType.PHASE_STARTED, user, phase=phase, cycle=state.cycle, remarks="Opened for rework path.")
    return state


def _pause_open_phases(machine, keep_codes):
    for state in machine.phase_states.filter(status=PhaseStatus.IN_PROGRESS).select_related("phase"):
        if state.phase.code in keep_codes:
            continue
        state.status = PhaseStatus.PENDING
        state.started_at = None
        state.started_by = None
        state.save(update_fields=["status", "started_at", "started_by"])


def raise_rework(machine, user, from_phase_code, problem_comment, answers=None, files=None, remarks=""):
    """Save the current card as draft (if any), then send the machine to Production for a new station."""
    problem = (problem_comment or "").strip().upper()
    if not problem:
        raise ReworkFlowError("Describe the problem before submitting rework.")
    if from_phase_code not in REWORK_ORIGINS:
        raise ReworkFlowError("Rework can be raised from Assembly, Testing, End of Line, or Quality.")
    if not can_operate_phase(user, from_phase_code) and not getattr(user, "is_management", False):
        raise ReworkFlowError("You are not authorised to raise rework on this phase.")

    path = rework_route(from_phase_code)
    with transaction.atomic():
        machine = type(machine).objects.select_for_update().get(pk=machine.pk)
        if active_rework(machine):
            raise ReworkFlowError("This machine already has an open rework.")

        origin = _phase(from_phase_code)
        origin_state = _state(machine, origin)
        if origin_state.status != PhaseStatus.IN_PROGRESS:
            raise ReworkFlowError(f"{origin.name} is not open on this machine.")

        if from_phase_code in PhaseCode.JOB_CARDS:
            persist_submission(
                machine=machine,
                user=user,
                phase_code=from_phase_code,
                cycle=origin_state.cycle,
                answers=answers or {},
                files=files or {},
                status="DRAFT",
                remarks=remarks or "",
                require_all=False,
                skip_required=True,
            )

        # Park the origin phase so it leaves other department queues until the path returns.
        origin_state.rework_open = True
        origin_state.status = PhaseStatus.PENDING
        origin_state.save(update_fields=["rework_open", "status"])

        production = _phase(PhaseCode.PRODUCTION)
        _pause_open_phases(machine, keep_codes=set())
        prod_state = _open_phase(machine, production, user, new_cycle=True)

        rework = ReworkRequest.objects.create(
            machine=machine,
            rejected_phase=origin,
            assigned_phase=production,
            reason=problem,
            rejected_by=user,
            cycle_number=prod_state.cycle,
            path_codes=",".join(path),
            path_index=0,
            status=ReworkRequest.Status.OPEN,
        )
        ReworkNote.objects.create(
            request=rework,
            phase_code=from_phase_code,
            note_type=ReworkNote.NoteType.PROBLEM,
            text=problem,
            author=user,
        )

        machine.station = None
        machine.is_under_rework = True
        machine.rework_count = (machine.rework_count or 0) + 1
        machine.status = MachineStatus.UNDER_REWORK
        machine.current_phase = PhaseCode.PRODUCTION
        machine.qc_approved_at = None
        machine.qc_approved_by = None
        machine.save(
            update_fields=[
                "station",
                "is_under_rework",
                "rework_count",
                "status",
                "current_phase",
                "qc_approved_at",
                "qc_approved_by",
                "updated_at",
            ]
        )

        _event(
            machine,
            EventType.REJECTED,
            user,
            phase=origin,
            cycle=origin_state.cycle,
            remarks=problem,
            metadata={"rework": rework.rework_code, "path": path},
        )
        notify_roles(
            [Roles.PRODUCTION_LEADER, Roles.ADMIN, Roles.SUPER_ADMIN],
            title=f"Rework raised for {machine.machine_id}",
            body=f"{machine_label(machine)} needs a new station. Problem: {problem}",
            url=machine_path(machine),
            machine=machine,
            exclude_user=user,
            category="rework",
        )
        log_audit(user, "rework.raise", instance=machine, changes={"origin": from_phase_code, "rework": rework.rework_code})
        return rework


def advance_rework_after_phase(machine, user, completed_phase, resolution_comment=""):
    """Move to the next path step, or close rework when the origin card is finished."""
    rework = active_rework(machine)
    if rework is None:
        return False

    path = rework.path_list
    if not path:
        return False

    resolution = (resolution_comment or "").strip()
    if not resolution:
        raise ReworkFlowError("Enter the work / solved comment before moving this rework on.")

    ReworkNote.objects.create(
        request=rework,
        phase_code=completed_phase.code,
        note_type=ReworkNote.NoteType.RESOLUTION,
        text=resolution,
        author=user,
    )

    # Finished the return (actual) phase — close rework and use normal forward flow.
    if rework.is_return_step and completed_phase.code == rework.origin_code:
        origin_state = _state(machine, completed_phase)
        origin_state.rework_open = False
        origin_state.save(update_fields=["rework_open"])
        rework.status = ReworkRequest.Status.CLOSED
        rework.closed_at = timezone.now()
        rework.save(update_fields=["status", "closed_at"])
        machine.is_under_rework = False
        machine.save(update_fields=["is_under_rework", "updated_at"])
        notify_roles(
            [Roles.PRODUCTION_LEADER, Roles.ADMIN, Roles.SUPER_ADMIN, Roles.QC],
            title=f"Rework closed for {machine.machine_id}",
            body=f"{rework.rework_code} is complete. {machine_label(machine)} continues on the normal path.",
            url=machine_path(machine),
            machine=machine,
            exclude_user=user,
            category="rework",
        )
        log_audit(user, "rework.close", instance=machine, changes={"rework": rework.rework_code})
        return "closed"

    next_index = rework.path_index + 1
    if next_index >= len(path):
        return "closed"

    next_code = path[next_index]
    next_phase = _phase(next_code)
    is_return = next_index == len(path) - 1

    if next_code == PhaseCode.WAITING:
        machine.test_area = ""
        machine.save(update_fields=["test_area", "updated_at"])

    if is_return and next_code == rework.origin_code:
        # Return to the same cycle so the saved draft is still there.
        state = _state(machine, next_phase)
        state.status = PhaseStatus.IN_PROGRESS
        state.rework_open = True
        if not state.started_at:
            state.started_at = timezone.now()
            state.started_by = user
        state.completed_at = None
        state.completed_by = None
        state.save()
        _event(machine, EventType.PHASE_STARTED, user, phase=next_phase, cycle=state.cycle, remarks="Returned for actual job card after rework.")
    else:
        _open_phase(machine, next_phase, user, new_cycle=True)

    rework.path_index = next_index
    rework.assigned_phase = next_phase
    rework.save(update_fields=["path_index", "assigned_phase"])

    machine.current_phase = next_code
    machine.status = MachineStatus.UNDER_REWORK
    machine.save(update_fields=["current_phase", "status", "updated_at"])

    role = {
        PhaseCode.ASSEMBLY: Roles.ASSEMBLY,
        PhaseCode.WAITING: Roles.TESTING,
        PhaseCode.TESTING: Roles.TESTING,
        PhaseCode.EOL: Roles.EOL,
        PhaseCode.QC: Roles.QC,
    }.get(next_code)
    if role:
        label = "actual job card" if is_return else "rework"
        notify_roles(
            [role],
            title=f"{machine.machine_id} ready for {next_phase.name} ({label})",
            body=f"{machine_label(machine)} is on rework path. Problem: {rework.reason}",
            url=machine_path(machine),
            machine=machine,
            exclude_user=user,
            category="rework",
        )
    log_audit(user, "rework.advance", instance=machine, changes={"next": next_code, "rework": rework.rework_code})
    return "advanced"


def rework_notes_for_report(machine):
    """Problem + resolution notes grouped by rework, only when the machine has rework history."""
    requests = (
        ReworkRequest.objects.filter(machine=machine)
        .prefetch_related("notes__author")
        .select_related("rejected_phase", "rejected_by")
        .order_by("rejected_at")
    )
    blocks = []
    for item in requests:
        notes = list(item.notes.all())
        if not notes and item.reason:
            notes = []
        blocks.append({"rework": item, "notes": notes, "problem": item.reason})
    return blocks
