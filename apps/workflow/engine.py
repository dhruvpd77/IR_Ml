"""Production workflow.

Business rules enforced here, not in the templates:

1. Planning submission is required before a serial can be assigned.
2. The production leader assigns the serial, then allocates the station.
3. Assembly and Electrical run side by side and do not block each other.
4. Testing opens only after both Assembly and Electrical are complete.
5. EOL opens only after Testing. QC opens only after EOL.
6. A machine is Completed only by QC approval.
7. Rework saves the current card as draft, sends the machine to Production for a
   new station, then follows Assembly → Testing → EOL as needed, and returns to
   the origin phase actual job card. Electrical is skipped on the rework path.
"""

from django.db import connection, transaction
from django.utils import timezone

from accounts.permissions import can_operate_phase, can_reject
from audit.utils import log_audit
from core.constants import (
    PHASE_ROLE,
    STATUS_FOR_OPENED_PHASE,
    EventType,
    MachineStatus,
    PhaseCode,
    PhaseStatus,
    Roles,
)
from jobcards.models import JobCardSubmission, MachineAttachment
from jobcards.services import MISSING, JobCardError, persist_submission, qc_card_template
from machines.models import Machine
from notifications.services import machine_label, machine_path, notify_roles
from rework.models import ReworkAction, ReworkRequest
from workflow.models import MachinePhaseState, ProductionPhase, WorkflowEvent
from workflow.rework_flow import (
    ReworkFlowError,
    active_rework,
    advance_rework_after_phase,
    raise_rework,
)

OPENING_MESSAGES = {
    PhaseCode.PLANNER: "was submitted by Planning and is ready for a serial number.",
    PhaseCode.PRODUCTION: "has a serial number and is ready for station allocation.",
    PhaseCode.ASSEMBLY: "has been assigned to Assembly.",
    PhaseCode.ELECTRICAL: "has been assigned to Electrical.",
    PhaseCode.TESTING: "has cleared Assembly and Electrical and is ready for testing.",
    PhaseCode.EOL: "has cleared Testing and is ready for end-of-line inspection.",
    PhaseCode.QC: "has cleared end-of-line inspection and is ready for final quality review.",
}


class WorkflowError(Exception):
    pass


def for_update(queryset):
    features = connection.features
    locked = getattr(features, "has_select_for_update", None)
    if locked is None:
        locked = getattr(features, "supports_select_for_update", False)
    if locked:
        return queryset.select_for_update()
    return queryset


def _phase(code):
    try:
        return ProductionPhase.objects.get(code=code, is_active=True)
    except ProductionPhase.DoesNotExist as exc:
        raise WorkflowError("That production phase is not configured.") from exc


def _lock(machine):
    return for_update(Machine.objects.all()).get(pk=machine.pk)


def _state(machine, phase):
    try:
        return for_update(MachinePhaseState.objects.select_related("phase")).get(machine=machine, phase=phase)
    except MachinePhaseState.DoesNotExist as exc:
        raise WorkflowError(f"{phase.name} has not been initialised for this machine.") from exc


def _event(machine, event_type, user, phase=None, cycle=1, remarks="", metadata=None):
    WorkflowEvent.objects.create(
        machine=machine,
        phase=phase,
        event_type=event_type,
        cycle=cycle,
        actor=user if getattr(user, "is_authenticated", False) else None,
        remarks=remarks or "",
        metadata=metadata or {},
    )


def _require_operator(user, phase_code):
    if not can_operate_phase(user, phase_code):
        raise WorkflowError("You are not authorised to update this production phase.")


def _require_open(state, phase):
    if state.status == PhaseStatus.COMPLETED:
        raise WorkflowError(f"{phase.name} has already been submitted for this cycle.")
    if state.status != PhaseStatus.IN_PROGRESS:
        raise WorkflowError(f"{phase.name} is not the active phase for this machine.")


def _clean_serial(value):
    return (value or "").strip().upper() or None


def _assert_unique_serial(machine, field, serial, label):
    if serial and Machine.objects.exclude(pk=machine.pk).filter(**{field: serial}).exists():
        raise WorkflowError(f"{label} {serial} is already used by another machine.")


def initialize_machine(machine, user):
    if machine.phase_states.exists():
        return
    phases = list(ProductionPhase.objects.filter(is_active=True).order_by("sequence", "name"))
    if not phases:
        raise WorkflowError("Production phases are not configured.")
    now = timezone.now()
    MachinePhaseState.objects.bulk_create(
        [
            MachinePhaseState(
                machine=machine,
                phase=phase,
                status=PhaseStatus.IN_PROGRESS if phase.code == PhaseCode.PLANNING else PhaseStatus.PENDING,
                started_at=now if phase.code == PhaseCode.PLANNING else None,
                started_by=user if phase.code == PhaseCode.PLANNING else None,
                cycle=1,
            )
            for phase in phases
        ]
    )
    machine.current_phase = PhaseCode.PLANNING
    machine.status = MachineStatus.DRAFT
    machine.save(update_fields=["current_phase", "status", "updated_at"])
    _event(machine, EventType.CREATED, user, phase=phases[0], remarks="Machine registered.")


def _complete(machine, phase, user, remarks=""):
    state = _state(machine, phase)
    _require_open(state, phase)
    now = timezone.now()
    started = state.started_at or now
    duration = max(0, int((now - started).total_seconds()))
    state.status = PhaseStatus.COMPLETED
    state.completed_at = now
    state.completed_by = user
    was_rework = state.rework_open
    state.rework_open = False
    state.save()
    _event(
        machine,
        EventType.PHASE_COMPLETED,
        user,
        phase=phase,
        cycle=state.cycle,
        remarks=remarks,
        metadata={
            "started_at": started.isoformat(),
            "completed_at": now.isoformat(),
            "duration_seconds": duration,
            "cycle": state.cycle,
        },
    )
    return state, was_rework


def _open(machine, phase, user):
    state = _state(machine, phase)
    if state.status == PhaseStatus.COMPLETED:
        raise WorkflowError(f"{phase.name} is already complete.")
    if state.status != PhaseStatus.IN_PROGRESS:
        state.status = PhaseStatus.IN_PROGRESS
        state.started_at = timezone.now()
        state.started_by = user
        state.completed_at = None
        state.completed_by = None
        state.save()
        _event(machine, EventType.PHASE_STARTED, user, phase=phase, cycle=state.cycle)
    return state


def _set_position(machine, phases):
    if len(phases) > 1:
        machine.current_phase = PhaseCode.BUILD
        machine.status = MachineStatus.IN_PRODUCTION
    else:
        phase = phases[0]
        machine.current_phase = phase.code
        machine.status = STATUS_FOR_OPENED_PHASE.get(phase.code, machine.status)
    machine.save(update_fields=["current_phase", "status", "updated_at"])


def _notify_opened(machine, phases, user):
    label = machine_label(machine)
    path = machine_path(machine)
    rework_note = " This machine is in a rework cycle." if machine.is_under_rework else ""
    for phase in phases:
        role = PHASE_ROLE.get(phase.code)
        if not role:
            continue
        detail = OPENING_MESSAGES.get(phase.code, f"is ready for {phase.name}.")
        notify_roles(
            [role],
            title=f"{machine.machine_id} assigned to {phase.name}",
            body=f"{label} {detail}{rework_note}",
            url=path,
            machine=machine,
            exclude_user=user,
        )


def _advance(machine, from_phase, user):
    # Assembly and Electrical are the same step. The next phase stays closed until both are complete.
    if from_phase.parallel_group:
        waiting = MachinePhaseState.objects.filter(
            machine=machine,
            phase__parallel_group=from_phase.parallel_group,
            phase__is_active=True,
        ).exclude(status=PhaseStatus.COMPLETED)
        if waiting.exists():
            machine.current_phase = PhaseCode.BUILD
            machine.status = MachineStatus.UNDER_REWORK if machine.is_under_rework and _rework_still_open(machine) else MachineStatus.IN_PRODUCTION
            machine.save(update_fields=["current_phase", "status", "updated_at"])
            return
    upcoming = list(
        ProductionPhase.objects.filter(is_active=True, sequence__gt=from_phase.sequence).order_by("sequence", "name")
    )
    if not upcoming:
        return
    next_sequence = upcoming[0].sequence
    opening = [phase for phase in upcoming if phase.sequence == next_sequence]
    opened = []
    for phase in opening:
        state = _state(machine, phase)
        if state.status == PhaseStatus.COMPLETED:
            continue
        _open(machine, phase, user)
        opened.append(phase)
    if not opened:
        return
    _set_position(machine, opened)
    if _rework_still_open(machine):
        machine.status = MachineStatus.UNDER_REWORK
        machine.save(update_fields=["status", "updated_at"])
    _notify_opened(machine, opened, user)


def _rework_still_open(machine):
    return MachinePhaseState.objects.filter(machine=machine, rework_open=True).exists()


def _resolve_rework(machine, phase, user, corrective_action, remarks):
    request = (
        ReworkRequest.objects.filter(machine=machine, assigned_phase=phase, status=ReworkRequest.Status.OPEN)
        .order_by("-pk")
        .first()
    )
    if request is None:
        return
    ReworkAction.objects.create(
        request=request,
        corrective_action=corrective_action,
        resolution_remarks=remarks or "",
        corrected_by=user,
    )
    request.status = ReworkRequest.Status.AWAITING_REINSPECTION
    request.save(update_fields=["status"])
    _event(
        machine,
        EventType.REWORK_COMPLETED,
        user,
        phase=phase,
        remarks=corrective_action,
        metadata={"rework": request.rework_code},
    )
    notify_roles(
        [Roles.QC, Roles.PRODUCTION_LEADER, Roles.ADMIN, Roles.SUPER_ADMIN],
        title=f"Rework completed for {machine.machine_id}",
        body=f"{request.rework_code} was corrected in {phase.name}. {corrective_action}",
        url=machine_path(machine),
        machine=machine,
        exclude_user=user,
        category="rework",
    )


def submit_planning(machine, user):
    _require_operator(user, PhaseCode.PLANNING)
    with transaction.atomic():
        machine = _lock(machine)
        if not user.is_management and machine.created_by_id != user.id:
            raise WorkflowError("You can only submit machine records that you created.")
        phase = _phase(PhaseCode.PLANNING)
        _require_open(_state(machine, phase), phase)
        planning = machine.planning
        planning.submitted_by = user
        planning.submitted_at = timezone.now()
        planning.save(update_fields=["submitted_by", "submitted_at"])
        _complete(machine, phase, user, remarks="Planning data submitted.")
        _advance(machine, phase, user)
        log_audit(user, "planning.submit", instance=machine)
        return machine


def planner_release(machine, user, serial):
    _require_operator(user, PhaseCode.PLANNER)
    serial = _clean_serial(serial)
    if not serial:
        raise WorkflowError("Enter a serial number before releasing the machine.")
    with transaction.atomic():
        machine = _lock(machine)
        _assert_unique_serial(machine, "planner_serial", serial, "Serial number")
        phase = _phase(PhaseCode.PLANNER)
        _require_open(_state(machine, phase), phase)
        machine.planner_serial = serial
        machine.save(update_fields=["planner_serial", "updated_at"])
        _event(machine, EventType.SERIAL_ASSIGNED, user, phase=phase, remarks=serial, metadata={"serial": serial})
        _complete(machine, phase, user, remarks=f"Serial {serial} assigned.")
        _advance(machine, phase, user)
        log_audit(user, "planner.release", instance=machine, changes={"serial": serial})
        return machine


def production_release(machine, user, station, production_serial="", remarks=""):
    _require_operator(user, PhaseCode.PRODUCTION)
    if station is None or not station.is_active:
        raise WorkflowError("Select an active production station.")
    production_serial = _clean_serial(production_serial)
    with transaction.atomic():
        machine = _lock(machine)
        _assert_unique_serial(machine, "production_serial", production_serial, "Production serial")
        phase = _phase(PhaseCode.PRODUCTION)
        _require_open(_state(machine, phase), phase)
        machine.station = station
        machine.production_serial = production_serial
        machine.production_remarks = (remarks or "").strip()
        machine.save(update_fields=["station", "production_serial", "production_remarks", "updated_at"])
        _event(
            machine,
            EventType.STATION_ASSIGNED,
            user,
            phase=phase,
            remarks=machine.production_remarks,
            metadata={"station": station.code, "production_serial": production_serial or ""},
        )
        _complete(machine, phase, user, remarks=f"Released to {station.name}.")
        rework = active_rework(machine)
        if rework:
            # Station chosen — move along the rework path (not the normal next phase).
            try:
                advance_rework_after_phase(
                    machine,
                    user,
                    phase,
                    resolution_comment=remarks or f"Station assigned: {station.name}.",
                )
            except ReworkFlowError as exc:
                raise WorkflowError(str(exc)) from exc
        else:
            _advance(machine, phase, user)
        log_audit(user, "production.release", instance=machine, changes={"station": station.code})
        return machine


def _job_card(machine, user, phase_code, answers, files, remarks, corrective_action, as_draft, approving=False, require_all=False, skip_required=False):
    if phase_code not in PhaseCode.JOB_CARDS:
        raise WorkflowError("This phase does not use a digital job card.")
    if phase_code == PhaseCode.QC and not as_draft and not approving:
        raise WorkflowError("QC is completed by approving the machine or by raising a rework.")
    _require_operator(user, phase_code)
    with transaction.atomic():
        machine = _lock(machine)
        phase = _phase(phase_code)
        state = _state(machine, phase)
        _require_open(state, phase)
        open_rework = active_rework(machine)
        needs_rework_comment = (
            not as_draft
            and open_rework is not None
            and phase_code in {PhaseCode.ASSEMBLY, PhaseCode.TESTING, PhaseCode.EOL, PhaseCode.QC}
        )
        corrective_missing = needs_rework_comment and not (corrective_action or "").strip()
        try:
            submission = persist_submission(
                machine=machine,
                user=user,
                phase_code=phase_code,
                cycle=state.cycle,
                answers=answers,
                files=files,
                status="DRAFT" if as_draft else "SUBMITTED",
                remarks=remarks,
                corrective_action=corrective_action,
                require_all=require_all,
                skip_required=skip_required,
            )
        except JobCardError as exc:
            if corrective_missing:
                errors = dict(exc.field_errors or {})
                errors["corrective_action"] = MISSING
                raise JobCardError("Review the highlighted job card fields.", errors) from exc
            raise
        if corrective_missing:
            raise JobCardError(
                "Enter the rework solved comment before submitting.",
                {"corrective_action": MISSING},
            )
        if as_draft:
            log_audit(user, "jobcard.draft", instance=submission)
            return machine, submission
        _completed, _was_rework = _complete(machine, phase, user, remarks=remarks or "Job card submitted.")
        if open_rework:
            try:
                result = advance_rework_after_phase(machine, user, phase, resolution_comment=corrective_action)
            except ReworkFlowError as exc:
                raise WorkflowError(str(exc)) from exc
            if result == "closed":
                _advance(machine, phase, user)
        else:
            _advance(machine, phase, user)
        log_audit(user, "jobcard.submit", instance=submission)
        return machine, submission


def save_job_card_draft(machine, user, phase_code, answers, files=None, remarks="", require_all=False, skip_required=False):
    machine, _submission = _job_card(
        machine, user, phase_code, answers, files, remarks, "", as_draft=True, require_all=require_all, skip_required=skip_required
    )
    return machine


def _draft_answers(machine, phase_code, cycle):
    from jobcards.models import JobCardSubmission

    draft = (
        JobCardSubmission.objects.filter(
            machine=machine,
            phase_code=phase_code,
            cycle=cycle,
            status=JobCardSubmission.Status.DRAFT,
        )
        .order_by("-pk")
        .first()
    )
    if draft is None:
        return {}
    answers = {}
    for response in draft.responses.select_related("field"):
        field = response.field
        if field.field_type == "yes_no" and response.value_bool is not None:
            answers[field.field_key] = "Yes" if response.value_bool else "No"
        elif response.value_date:
            answers[field.field_key] = response.value_date.isoformat()
        elif response.value_text:
            answers[field.field_key] = response.value_text
    return answers


def pass_phase(machine, user, phase_code):
    """Approve the open phase and move the machine on. Management can pass any phase."""
    if phase_code == PhaseCode.PLANNING:
        return submit_planning(machine, user)
    if phase_code == PhaseCode.PLANNER:
        if not (machine.planner_serial or "").strip():
            raise WorkflowError("Assign a serial number before moving this machine on.")
        return planner_release(machine, user, machine.planner_serial)
    if phase_code == PhaseCode.PRODUCTION:
        if not machine.station_id:
            raise WorkflowError("Allocate a station before moving this machine on.")
        return production_release(
            machine,
            user,
            machine.station,
            production_serial=machine.production_serial or "",
            remarks=machine.production_remarks or "",
        )
    management = getattr(user, "is_management", False)
    if phase_code == PhaseCode.QC:
        return approve_qc(machine, user, {}, remarks="Approved and released.", require_all=not management, skip_required=management)
    if phase_code not in PhaseCode.JOB_CARDS:
        raise WorkflowError("That phase cannot be passed from here.")
    phase = _phase(phase_code)
    state = machine.phase_states.filter(phase=phase).first()
    if state is None or state.status != PhaseStatus.IN_PROGRESS:
        raise WorkflowError(f"{phase.name} is not open on this machine.")
    if phase_code == PhaseCode.TESTING and not management and not (machine.test_area or "").strip():
        raise WorkflowError("Select Test area 1, Test area 2, or Test area 3 before moving this machine on.")
    answers = _draft_answers(machine, phase_code, state.cycle)
    if not management and phase_code == PhaseCode.TESTING and not str(answers.get("test_result") or "").strip():
        raise WorkflowError("Open the testing card and mark OK or NOT OK before moving on.")
    try:
        submit_job_card(machine, user, phase_code, answers, require_all=not management, skip_required=management)
    except JobCardError as exc:
        if not management and exc.field_errors:
            raise WorkflowError("Open the job card and fill every field. Missing fields are marked in red.") from exc
        raise
    return machine


def submit_job_card(machine, user, phase_code, answers, files=None, remarks="", corrective_action="", require_all=False, skip_required=False):
    machine, _submission = _job_card(
        machine,
        user,
        phase_code,
        answers,
        files,
        remarks,
        corrective_action,
        as_draft=False,
        require_all=require_all,
        skip_required=skip_required,
    )
    return machine


def approve_qc(machine, user, answers, files=None, remarks="", require_all=False, skip_required=False, corrective_action=""):
    _require_operator(user, PhaseCode.QC)
    with transaction.atomic():
        machine = _lock(machine)
        phase = _phase(PhaseCode.QC)
        state = _state(machine, phase)
        _require_open(state, phase)
        open_item = active_rework(machine)
        resolution = (corrective_action or remarks or "").strip()
        if open_item and not resolution:
            raise WorkflowError("Enter the rework solved comment before approving after rework.")
        persist_submission(
            machine=machine,
            user=user,
            phase_code=PhaseCode.QC,
            cycle=state.cycle,
            answers=answers,
            files=files,
            status="SUBMITTED",
            remarks=remarks,
            require_all=require_all,
            skip_required=skip_required,
        )
        _complete(machine, phase, user, remarks=remarks or "QC approved.")
        if open_item:
            try:
                advance_rework_after_phase(machine, user, phase, resolution_comment=resolution)
            except ReworkFlowError as exc:
                raise WorkflowError(str(exc)) from exc
        now = timezone.now()
        machine.status = MachineStatus.COMPLETED
        machine.current_phase = PhaseCode.QC
        machine.qc_approved_by = user
        machine.qc_approved_at = now
        machine.is_under_rework = False
        machine.save(
            update_fields=["status", "current_phase", "qc_approved_by", "qc_approved_at", "is_under_rework", "updated_at"]
        )
        ReworkRequest.objects.filter(machine=machine).exclude(status=ReworkRequest.Status.CLOSED).update(
            status=ReworkRequest.Status.CLOSED,
            reinspection_status="PASSED",
            closed_at=now,
        )
        _event(machine, EventType.APPROVED, user, phase=phase, cycle=state.cycle, remarks=remarks or "Final QC approval.")
        notify_roles(
            [Roles.PRODUCTION_LEADER, Roles.ADMIN, Roles.SUPER_ADMIN],
            title=f"{machine.machine_id} approved by QC",
            body=f"{machine_label(machine)} has been released by Quality Control.",
            url=machine_path(machine),
            machine=machine,
            exclude_user=user,
        )
        log_audit(user, "qc.approve", instance=machine)
        return machine


def update_finished_qc(machine, user, answers, files=None, remarks="", require_all=False, skip_required=False):
    """Change a completed QC card. The machine stays completed."""
    _require_operator(user, PhaseCode.QC)
    phase = _phase(PhaseCode.QC)
    state = machine.phase_states.filter(phase=phase).first()
    if state is None or state.status != PhaseStatus.COMPLETED or machine.status != MachineStatus.COMPLETED:
        raise WorkflowError("This QC record can be edited after the machine is completed.")
    submission = (
        JobCardSubmission.objects.filter(
            machine=machine,
            phase_code=PhaseCode.QC,
            cycle=state.cycle,
            status=JobCardSubmission.Status.SUBMITTED,
        )
        .order_by("-revision", "-pk")
        .first()
    )
    if submission is None:
        raise WorkflowError("There is no QC record to edit.")
    persist_submission(
        machine=machine,
        user=user,
        phase_code=PhaseCode.QC,
        cycle=state.cycle,
        answers=answers,
        files=files,
        status=JobCardSubmission.Status.SUBMITTED,
        remarks=remarks,
        template=qc_card_template(submission),
        allow_existing=True,
        replace=submission,
        require_all=require_all,
        skip_required=skip_required,
    )
    log_audit(user, "qc.edit", instance=machine, changes={"submission": submission.pk})
    return machine


def reject_machine(machine, user, target_phase_code, reason, answers=None, files=None, attachment_files=None, remarks=""):
    """Compatibility wrapper — rework always starts at Production, then follows the fixed path."""
    del target_phase_code, attachment_files  # old "send back to" target is no longer used
    open_state = (
        machine.phase_states.filter(status=PhaseStatus.IN_PROGRESS)
        .select_related("phase")
        .order_by("-phase__sequence")
        .first()
    )
    from_code = open_state.phase.code if open_state else ""
    if from_code == PhaseCode.ELECTRICAL:
        from_code = PhaseCode.ASSEMBLY
    if from_code not in {PhaseCode.ASSEMBLY, PhaseCode.TESTING, PhaseCode.EOL, PhaseCode.QC}:
        raise WorkflowError("Rework can be raised from Assembly, Testing, End of Line, or Quality.")
    try:
        return raise_rework(
            machine,
            user,
            from_code,
            reason,
            answers=answers,
            files=files,
            remarks=remarks or "",
        )
    except ReworkFlowError as exc:
        raise WorkflowError(str(exc)) from exc


def reachable_rework_targets(machine):
    reached = (
        machine.phase_states.filter(status__in=[PhaseStatus.IN_PROGRESS, PhaseStatus.COMPLETED])
        .order_by("-phase__sequence")
        .values_list("phase__sequence", flat=True)
        .first()
    )
    if not reached:
        return ProductionPhase.objects.none()
    return ProductionPhase.objects.filter(is_active=True, sequence__lte=reached).exclude(code=PhaseCode.QC).order_by("sequence", "name")


def open_rework(machine):
    return active_rework(machine)
