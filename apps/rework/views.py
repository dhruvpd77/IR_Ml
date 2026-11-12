from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from accounts.permissions import can_operate_phase, can_reject, can_view_machine
from core.constants import PhaseCode, PhaseStatus
from core.http import paginate, querystring
from jobcards.services import JobCardError, submission_form_state
from machines.services import visible_machines
from rework.models import ReworkRequest
from workflow.engine import (
    WorkflowError,
    approve_qc,
    reachable_rework_targets,
    reject_machine,
    submit_job_card,
)
from workflow.models import MachinePhaseState
from workflow.rework_flow import ReworkFlowError, advance_rework_after_phase


def _item_or_404(pk):
    return get_object_or_404(
        ReworkRequest.objects.select_related(
            "machine",
            "machine__planning",
            "machine__station",
            "assigned_phase",
            "rejected_phase",
            "rejected_by",
        ).prefetch_related("actions__corrected_by", "attachments", "notes__author"),
        pk=pk,
    )


def _can_work_item(user, item):
    if user.is_management or user.role == "QC":
        return True
    return can_operate_phase(user, item.assigned_phase.code)


def _job_card_url(item):
    phase_code = item.assigned_phase.code if item.assigned_phase_id else ""
    if phase_code in PhaseCode.JOB_CARDS:
        return "jobcards:fill", {"phase_code": phase_code, "machine_id": item.machine.machine_id}
    return "machines:detail", {"machine_id": item.machine.machine_id}


def _answers_from_draft(machine, phase_code, cycle):
    """Rebuild submit answers from the open draft (files stay attached on the draft)."""
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
        return {}, {}
    values, files = submission_form_state(draft)
    answers = {}
    for key, value in values.items():
        answers[key] = value
    # Existing draft attachments are reused by persist_submission; no re-upload needed.
    return answers, {}


@login_required
def rework_list(request):
    queryset = ReworkRequest.objects.select_related(
        "machine",
        "machine__planning",
        "assigned_phase",
        "rejected_phase",
        "rejected_by",
    )
    if not request.user.is_management and request.user.role != "QC":
        queryset = queryset.filter(assigned_phase__department=request.user.department)
    status = request.GET.get("status") or ""
    if status:
        queryset = queryset.filter(status=status)
    query = (request.GET.get("q") or "").strip()
    if query:
        queryset = queryset.filter(
            Q(rework_code__icontains=query)
            | Q(machine__machine_id__icontains=query)
            | Q(reason__icontains=query)
            | Q(machine__planning__work_order__icontains=query)
            | Q(machine__planning__model_description__icontains=query)
        )
    page = paginate(request, queryset)
    rows = []
    for item in page.object_list:
        phase_code = item.assigned_phase.code if item.assigned_phase_id else ""
        view_name, view_kwargs = _job_card_url(item)
        rows.append(
            {
                "item": item,
                "can_resolve": item.status == ReworkRequest.Status.OPEN and _can_work_item(request.user, item),
                "has_job_card": phase_code in PhaseCode.JOB_CARDS,
                "view_name": view_name,
                "view_kwargs": view_kwargs,
            }
        )
    return render(
        request,
        "rework/list.html",
        {
            "page": page,
            "rows": rows,
            "querystring": querystring(request),
            "statuses": ReworkRequest.Status.choices,
            "selected": status,
            "query": query,
        },
    )


@login_required
def rework_detail(request, pk):
    """Reason screen: machine basics + problem/resolution comments."""
    item = _item_or_404(pk)
    if not can_view_machine(request.user, item.machine):
        raise PermissionDenied
    view_name, view_kwargs = _job_card_url(item)
    return render(
        request,
        "rework/detail.html",
        {
            "item": item,
            "can_resolve": item.status == ReworkRequest.Status.OPEN and _can_work_item(request.user, item),
            "has_job_card": item.assigned_phase.code in PhaseCode.JOB_CARDS,
            "view_name": view_name,
            "view_kwargs": view_kwargs,
        },
    )


@login_required
def rework_resolve(request, pk):
    """Resolve screen: enter solved comment, advance only when the job card is complete."""
    item = _item_or_404(pk)
    if not can_view_machine(request.user, item.machine):
        raise PermissionDenied
    if item.status != ReworkRequest.Status.OPEN:
        messages.error(request, "This rework is already closed.")
        return redirect("rework:detail", item.pk)
    if not _can_work_item(request.user, item):
        raise PermissionDenied

    phase = item.assigned_phase
    phase_code = phase.code
    view_name, view_kwargs = _job_card_url(item)
    state = MachinePhaseState.objects.filter(machine=item.machine, phase=phase).first()
    card_open = bool(state and state.status == PhaseStatus.IN_PROGRESS)

    if request.method == "POST":
        comment = (request.POST.get("resolution") or request.POST.get("corrective_action") or "").strip()
        if not comment:
            messages.error(request, "Enter the resolve comment before continuing.")
            return redirect("rework:resolve", item.pk)

        try:
            if phase_code == PhaseCode.PRODUCTION:
                raise WorkflowError(
                    "Assign a station from Serial numbers / Stations first. Then this rework moves on."
                )
            if phase_code == PhaseCode.WAITING:
                raise WorkflowError(
                    "Assign a testing bay from Waiting Area first. Then this rework moves on."
                )
            if phase_code in PhaseCode.JOB_CARDS:
                if not card_open:
                    raise WorkflowError(f"{phase.name} is not open on this machine yet.")
                answers, files = _answers_from_draft(item.machine, phase_code, state.cycle)
                if not answers and phase_code != PhaseCode.QC:
                    raise WorkflowError(
                        f"Open the {phase.name} job card (View), fill every field, save draft, then resolve here."
                    )
                if phase_code == PhaseCode.QC:
                    approve_qc(
                        item.machine,
                        request.user,
                        answers,
                        files,
                        remarks="",
                        require_all=True,
                        skip_required=False,
                        corrective_action=comment,
                    )
                else:
                    submit_job_card(
                        item.machine,
                        request.user,
                        phase_code,
                        answers,
                        files,
                        remarks="",
                        corrective_action=comment,
                        require_all=True,
                        skip_required=False,
                    )
                messages.success(
                    request,
                    f"{item.rework_code} resolved from {phase.name}. Machine moved to the next step.",
                )
                return redirect("rework:list")

            # Non-card path step: record comment and advance.
            advance_rework_after_phase(item.machine, request.user, phase, resolution_comment=comment)
            messages.success(request, f"{item.rework_code} moved to the next step.")
            return redirect("rework:list")
        except JobCardError as exc:
            missing = len(exc.field_errors or {})
            messages.error(
                request,
                str(exc)
                if not missing
                else f"Fill all job card fields first ({missing} missing). Use View to open the full card.",
            )
            return redirect(view_name, **view_kwargs)
        except (ReworkFlowError, WorkflowError) as exc:
            messages.error(request, str(exc))
            return redirect("rework:resolve", item.pk)

    return render(
        request,
        "rework/resolve.html",
        {
            "item": item,
            "card_open": card_open,
            "has_job_card": phase_code in PhaseCode.JOB_CARDS,
            "view_name": view_name,
            "view_kwargs": view_kwargs,
        },
    )


@login_required
def rework_create(request, machine_id):
    machine = get_object_or_404(visible_machines(request.user), machine_id=machine_id)
    if not can_reject(request.user, machine):
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
