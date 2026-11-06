from django.contrib import messages
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.decorators import management_required
from django.templatetags.static import static

from accounts.models import current_logo
from machines.brand import brand_static
from accounts.permissions import can_operate_phase, can_view_machine
from audit.utils import log_audit
from core.constants import TEST_AREAS, PhaseCode, PhaseStatus
from jobcards.forms import FieldForm, TemplateForm
from jobcards.importers import parse_template_workbook
from jobcards.models import JobCardField, JobCardSubmission, JobCardTemplate, MachineAttachment
from jobcards.services import (
    JobCardError,
    active_template,
    answers_from_request,
    attach_qc_photo,
    attach_testing_video,
    group_fields,
    qc_card_template,
    remove_qc_photo,
    remove_testing_video,
    revise_submission,
    submission_form_state,
)
from jobcards.setup import new_template_version, unique_key
from machines.services import visible_machines
from workflow.engine import (
    WorkflowError,
    approve_qc,
    open_rework,
    update_finished_qc,
    reachable_rework_targets,
    reject_machine,
    save_job_card_draft,
    submit_job_card,
)
from workflow.models import ProductionPhase
from workflow.presenters import tracking_steps


def _machine(user, machine_id):
    machine = get_object_or_404(visible_machines(user), machine_id=machine_id)
    if not can_view_machine(user, machine):
        raise PermissionDenied
    return machine


@login_required
def fill(request, phase_code, machine_id):
    if phase_code not in PhaseCode.JOB_CARDS:
        raise PermissionDenied
    machine = _machine(request.user, machine_id)
    phase = get_object_or_404(ProductionPhase, code=phase_code, is_active=True)
    state = machine.phase_states.filter(phase=phase).first()
    try:
        template = active_template(phase_code)
    except JobCardError as exc:
        messages.error(request, str(exc))
        return redirect("machines:detail", machine.machine_id)
    qc_edit = bool(
        phase_code == PhaseCode.QC
        and state
        and state.status == PhaseStatus.COMPLETED
        and machine.status == "COMPLETED"
        and can_operate_phase(request.user, phase_code)
    )
    record = None
    if qc_edit:
        record = (
            JobCardSubmission.objects.filter(
                machine=machine,
                phase_code=phase_code,
                cycle=state.cycle,
                status=JobCardSubmission.Status.SUBMITTED,
            )
            .order_by("-revision", "-pk")
            .first()
        )
        template = qc_card_template(record)
        editable = record is not None
    else:
        editable = bool(state and state.status == PhaseStatus.IN_PROGRESS and can_operate_phase(request.user, phase_code))
        if state:
            record = (
                JobCardSubmission.objects.filter(
                    machine=machine,
                    phase_code=phase_code,
                    cycle=state.cycle,
                    status=JobCardSubmission.Status.DRAFT,
                )
                .order_by("-pk")
                .first()
            )
    values, existing_files = submission_form_state(record)
    field_errors = {}
    chosen_area = machine.test_area
    if request.method == "POST":
        if not editable:
            raise PermissionDenied
        answers, uploads = answers_from_request(template, request.POST, request.FILES)
        remarks = request.POST.get("remarks", "")
        corrective = request.POST.get("corrective_action", "")
        action = request.POST.get("action") or "submit"
        skip_required = action in {"submit", "approve"} and request.user.is_management
        if action == "reject" or skip_required:
            require_all = False
        else:
            require_all = True
        area = (request.POST.get("test_area") or "").strip()
        chosen_area = area
        test_area_error = False
        def area_missing():
            return phase_code == PhaseCode.TESTING and require_all and area not in TEST_AREAS

        try:
            with transaction.atomic():
                if phase_code == PhaseCode.TESTING and area in TEST_AREAS:
                    machine.test_area = area
                    machine.save(update_fields=["test_area", "updated_at"])
                if qc_edit:
                    if action != "update":
                        raise PermissionDenied
                    update_finished_qc(machine, request.user, answers, uploads, remarks, require_all=require_all, skip_required=False)
                    if area_missing():
                        raise JobCardError("Select the testing station.", {})
                    messages.success(request, f"{machine.machine_id} QC record updated. The machine stays completed.")
                    return redirect("jobcards:fill", phase_code, machine.machine_id)
                if phase_code == PhaseCode.QC and action == "approve":
                    approve_qc(
                        machine, request.user, answers, uploads, remarks, require_all=require_all, skip_required=skip_required
                    )
                    messages.success(request, f"{machine.machine_id} approved and completed.")
                    return redirect("machines:detail", machine.machine_id)
                if phase_code == PhaseCode.QC and action == "reject":
                    reject_machine(
                        machine,
                        request.user,
                        request.POST.get("target_phase", ""),
                        request.POST.get("reason", ""),
                        attachment_files=request.FILES.getlist("evidence"),
                        remarks=remarks,
                    )
                    messages.success(request, f"{machine.machine_id} was sent back for rework.")
                    return redirect("machines:detail", machine.machine_id)
                if action == "draft":
                    save_job_card_draft(
                        machine, request.user, phase_code, answers, uploads, remarks, require_all=require_all
                    )
                    if area_missing():
                        raise JobCardError("Select the testing station.", {})
                    messages.success(request, "Draft saved.")
                    return redirect("jobcards:fill", phase_code, machine.machine_id)
                if phase_code == PhaseCode.TESTING and str(answers.get("test_result") or "") == "NOT OK":
                    problem = answers.get("test_problem")
                    if not str(problem or "").strip():
                        raise JobCardError(
                            "Describe the problem when testing is not OK.",
                            {"test_problem": "This field is missing."},
                        )
                machine = submit_job_card(
                    machine,
                    request.user,
                    phase_code,
                    answers,
                    uploads,
                    remarks,
                    corrective,
                    require_all=require_all,
                    skip_required=skip_required,
                )
                if area_missing():
                    raise JobCardError("Select the testing station.", {})
                if phase_code in {PhaseCode.ASSEMBLY, PhaseCode.ELECTRICAL}:
                    other = PhaseCode.ELECTRICAL if phase_code == PhaseCode.ASSEMBLY else PhaseCode.ASSEMBLY
                    other_open = machine.phase_states.filter(phase__code=other).exclude(status=PhaseStatus.COMPLETED).exists()
                    if other_open:
                        messages.success(
                            request,
                            f"{machine.machine_id} {phase.name} card is complete. Testing opens after Assembly and Electrical are both done.",
                        )
                    else:
                        messages.success(request, f"{machine.machine_id} Assembly and Electrical are both done. It is now with Testing.")
                elif phase_code == PhaseCode.TESTING:
                    messages.success(request, f"{machine.machine_id} testing card is complete. It is now at End of Line.")
                else:
                    messages.success(request, f"{phase.name} job card submitted.")
                return redirect("machines:detail", machine.machine_id)
        except JobCardError as exc:
            messages.error(request, str(exc))
            field_errors = exc.field_errors
            values = answers
            test_area_error = area_missing()
        except WorkflowError as exc:
            messages.error(request, str(exc))
            values = answers
            test_area_error = area_missing()
    history = (
        machine.job_card_submissions.exclude(status=JobCardSubmission.Status.DRAFT)
        .select_related("operator")
        .prefetch_related("responses__field", "attachments")
        .order_by("phase_code", "cycle", "revision")
    )
    groups = group_fields(template.active_fields())
    for group in groups:
        fields = group["fields"]
        if not fields or not str(fields[0].field_key).startswith("elec_") or not str(fields[0].field_key).endswith("_ok"):
            continue
        rows = []
        chunk = []
        for field in fields:
            chunk.append(field)
            if len(chunk) == 3:
                rows.append({"result": chunk[0], "value": chunk[1], "remark": chunk[2]})
                chunk = []
        group["rows"] = rows
    sheet = phase_code in {PhaseCode.ASSEMBLY, PhaseCode.TESTING, PhaseCode.EOL, PhaseCode.ELECTRICAL}
    planning = machine.planning
    return render(
        request,
        "jobcards/sheet.html" if sheet else "jobcards/fill.html",
        {
            "machine": machine,
            "logo": current_logo(),
            "brand_logo": static(brand_static(machine.planning.company)),
            "planning_date": planning.submitted_at or machine.created_at,
            "sheet": sheet,
            "phase": phase,
            "state": state,
            "template": template,
            "groups": groups,
            "values": values,
            "existing_files": existing_files,
            "field_errors": field_errors,
            "test_areas": TEST_AREAS,
            "chosen_area": chosen_area,
            "test_area_error": test_area_error if request.method == "POST" else False,
            "editable": editable,
            "qc_edit": qc_edit,
            "saved_remarks": record.remarks if qc_edit and record else "",
            "rework_open": bool(state and state.rework_open),
            "open_rework": open_rework(machine),
            "targets": reachable_rework_targets(machine) if phase_code == PhaseCode.QC and editable and not qc_edit else [],
            "steps": tracking_steps(machine),
            "history": history,
            "is_qc": phase_code == PhaseCode.QC,
        },
    )


@login_required
def submission_detail(request, pk):
    submission = get_object_or_404(
        JobCardSubmission.objects.select_related("machine", "operator", "template").prefetch_related(
            "responses__field", "attachments", "later_revisions"
        ),
        pk=pk,
    )
    if not can_view_machine(request.user, submission.machine):
        raise PermissionDenied
    return render(
        request,
        "jobcards/detail.html",
        {"submission": submission, "responses": submission.responses.select_related("field")},
    )


@management_required
def revise(request, pk):
    submission = get_object_or_404(
        JobCardSubmission.objects.select_related("machine", "template").prefetch_related("responses__field"),
        pk=pk,
    )
    values, existing_files = submission_form_state(submission)
    field_errors = {}
    if request.method == "POST":
        answers, uploads = answers_from_request(submission.template, request.POST, request.FILES)
        try:
            revised = revise_submission(submission, request.user, answers, uploads, request.POST.get("reason", ""))
        except JobCardError as exc:
            messages.error(request, str(exc))
            field_errors = exc.field_errors
            values = answers
        else:
            messages.success(request, f"Revision {revised.revision} saved. The previous submission is unchanged.")
            return redirect("jobcards:submission", revised.pk)
    return render(
        request,
        "jobcards/revise.html",
        {
            "submission": submission,
            "groups": group_fields(submission.template.fields.filter(is_active=True)),
            "values": values,
            "existing_files": existing_files,
            "field_errors": field_errors,
        },
    )


def _phase_operator(request, machine_id, phase_code):
    if not can_operate_phase(request.user, phase_code):
        raise PermissionDenied
    return _machine(request.user, machine_id)


def _media_payload(stored, label):
    return JsonResponse(
        {
            "id": stored.pk,
            "name": stored.original_name or label,
            "url": reverse("jobcards:attachment", args=[stored.pk]),
        }
    )


@login_required
@require_POST
def testing_video_upload(request, machine_id):
    machine = _phase_operator(request, machine_id, PhaseCode.TESTING)
    try:
        stored = attach_testing_video(machine, request.user, request.FILES.get("video"))
    except JobCardError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return _media_payload(stored, "Inspection video")


@login_required
@require_POST
def testing_video_remove(request, machine_id, pk):
    machine = _phase_operator(request, machine_id, PhaseCode.TESTING)
    try:
        remove_testing_video(machine, request.user, pk)
    except JobCardError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def qc_photo_upload(request, machine_id):
    machine = _phase_operator(request, machine_id, PhaseCode.QC)
    try:
        stored = attach_qc_photo(machine, request.user, request.FILES.get("photo"))
    except JobCardError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return _media_payload(stored, "Inspection photo")


@login_required
@require_POST
def qc_photo_remove(request, machine_id, pk):
    machine = _phase_operator(request, machine_id, PhaseCode.QC)
    try:
        remove_qc_photo(machine, request.user, pk)
    except JobCardError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"ok": True})


@login_required
def attachment(request, pk):
    item = get_object_or_404(MachineAttachment.objects.select_related("machine"), pk=pk)
    if not can_view_machine(request.user, item.machine):
        raise PermissionDenied
    inline = item.kind in {MachineAttachment.Kind.IMAGE, MachineAttachment.Kind.VIDEO}
    return FileResponse(item.file.open("rb"), as_attachment=not inline, filename=item.original_name or "attachment")


@management_required
def template_list(request):
    templates = JobCardTemplate.objects.all()
    return render(request, "jobcards/template_list.html", {"templates": templates})


@management_required
def template_edit(request, pk=None):
    template = get_object_or_404(JobCardTemplate, pk=pk) if pk else None
    form = TemplateForm(request.POST or None, instance=template)
    if request.method == "POST" and "save-template" in request.POST and form.is_valid():
        saved = form.save(commit=False)
        if template is None:
            saved.created_by = request.user
            saved.version = 1
            saved.is_active = not JobCardTemplate.objects.filter(phase_code=saved.phase_code, is_active=True).exists()
        saved.save()
        log_audit(request.user, "jobcard.template", instance=saved, request=request)
        messages.success(request, "Job card template saved.")
        return redirect("jobcards:template_edit", saved.pk)
    return render(
        request,
        "jobcards/template_form.html",
        {"form": form, "template": template, "fields": template.fields.all() if template else []},
    )


@management_required
@require_POST
def template_version(request, pk):
    template = get_object_or_404(JobCardTemplate, pk=pk)
    clone = new_template_version(template, request.user)
    messages.success(request, f"Version {clone.version} is now active. Earlier submissions stay on version {template.version}.")
    return redirect("jobcards:template_edit", clone.pk)


@management_required
@require_POST
def template_import(request, pk):
    template = get_object_or_404(JobCardTemplate, pk=pk)
    upload = request.FILES.get("workbook")
    if not upload or not upload.name.lower().endswith(".xlsx"):
        messages.error(request, "Upload an .xlsx template.")
        return redirect("jobcards:template_edit", template.pk)
    try:
        specs, errors = parse_template_workbook(upload)
    except Exception:
        messages.error(request, "The workbook could not be read.")
        return redirect("jobcards:template_edit", template.pk)
    if not specs:
        messages.error(request, "No fields were found in that workbook.")
        return redirect("jobcards:template_edit", template.pk)
    target = new_template_version(template, request.user) if template.submissions.exists() else template
    target.fields.all().delete()
    taken = set()
    for index, spec in enumerate(specs, start=1):
        spec["field_key"] = unique_key(target, spec["label"], taken)
        JobCardField.objects.create(template=target, sort_order=index, **spec)
    for error in errors[:8]:
        messages.warning(request, error)
    messages.success(request, f"Imported {len(specs)} fields into {target.name} v{target.version}.")
    return redirect("jobcards:template_edit", target.pk)


@management_required
def field_edit(request, template_id, pk=None):
    template = get_object_or_404(JobCardTemplate, pk=template_id)
    field = get_object_or_404(JobCardField, pk=pk, template=template) if pk else None
    form = FieldForm(request.POST or None, instance=field)
    if request.method == "POST" and form.is_valid():
        form.save(template)
        messages.success(request, "Field saved.")
        return redirect("jobcards:template_edit", template.pk)
    return render(request, "jobcards/field_form.html", {"form": form, "template": template, "field": field})


@management_required
@require_POST
def field_toggle(request, pk):
    field = get_object_or_404(JobCardField, pk=pk)
    field.is_active = not field.is_active
    field.save(update_fields=["is_active"])
    return redirect("jobcards:template_edit", field.template_id)


@management_required
@require_POST
def field_move(request, pk):
    field = get_object_or_404(JobCardField, pk=pk)
    siblings = list(field.template.fields.order_by("sort_order", "pk"))
    index = next((position for position, item in enumerate(siblings) if item.pk == field.pk), None)
    direction = request.POST.get("direction")
    swap_index = index - 1 if direction == "up" else index + 1
    if index is not None and 0 <= swap_index < len(siblings):
        other = siblings[swap_index]
        field.sort_order, other.sort_order = other.sort_order, field.sort_order
        if field.sort_order == other.sort_order:
            field.sort_order = field.sort_order + (-1 if direction == "up" else 1)
        field.save(update_fields=["sort_order"])
        other.save(update_fields=["sort_order"])
    return redirect("jobcards:template_edit", field.template_id)
