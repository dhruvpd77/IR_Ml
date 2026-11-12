import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from audit.utils import log_audit
from core.constants import EventType, FieldType, PhaseCode
from jobcards.models import JobCardResponse, JobCardSubmission, JobCardTemplate, MachineAttachment
from jobcards.images import compress_image
from jobcards.video import compress_video

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXT = {".mp4", ".webm", ".mov", ".m4v"}
DOC_EXT = IMAGE_EXT | {".pdf", ".xlsx", ".xls", ".docx", ".txt", ".csv"}
MAX_IMAGE = 20 * 1024 * 1024
MAX_PHOTOS = 8
MAX_VIDEO = 200 * 1024 * 1024
MAX_DOC = 15 * 1024 * 1024
MAX_VIDEOS = 8
MISSING = "This field is missing."
PASS_VALUES = {"Pass", "Fail", "N/A"}
YES_VALUES = {"Yes", "No"}


class JobCardError(Exception):
    def __init__(self, message, field_errors=None):
        super().__init__(message)
        self.field_errors = field_errors or {}


MODEL_SCOPED_PHASES = {PhaseCode.ASSEMBLY, PhaseCode.TESTING}


def active_template(phase_code, machine=None):
    """Return the active job card for this phase.

    Assembly/Testing are model-wise via planning catalog job_card_key.
    Electrical/EOL/QC stay shared (checklist_key blank).
    """
    if phase_code in MODEL_SCOPED_PHASES:
        from machines.catalog import (
            job_card_format_for_machine,
            job_card_key_for_machine,
            normalize_job_card_key,
            resolve_checklist_key,
        )

        if machine is None:
            raise JobCardError("Open this job card from a machine so the correct model checklist can load.")
        catalog_key = normalize_job_card_key(job_card_key_for_machine(machine))
        if not catalog_key:
            raise JobCardError("No job card is mapped for this model.")
        source_format = job_card_format_for_machine(machine)
        # Try catalog key first, then Excel sheet alias when format is excel.
        candidates = []
        for key in (catalog_key, resolve_checklist_key(catalog_key, source_format)):
            if key and key.lower() not in {item.lower() for item in candidates}:
                candidates.append(key)
        # Word row with no matching file can still use an Excel sheet of the same name.
        if source_format == "word":
            excel_key = resolve_checklist_key(catalog_key, "excel")
            if excel_key and excel_key.lower() not in {item.lower() for item in candidates}:
                candidates.append(excel_key)
        template = None
        for key in candidates:
            template = (
                JobCardTemplate.objects.filter(
                    phase_code=phase_code,
                    checklist_key__iexact=key,
                    is_active=True,
                )
                .order_by("-version")
                .first()
            )
            if template is None:
                for candidate in JobCardTemplate.objects.filter(phase_code=phase_code, is_active=True).order_by(
                    "-version"
                ):
                    if normalize_job_card_key(candidate.checklist_key).lower() == key.lower():
                        template = candidate
                        break
            if template is not None:
                break
        if template is None:
            raise JobCardError("Job card is not available for this model.")
        return template

    template = (
        JobCardTemplate.objects.filter(phase_code=phase_code, checklist_key="", is_active=True)
        .order_by("-version")
        .first()
    )
    if template is None:
        # Legacy rows created before checklist_key existed
        template = (
            JobCardTemplate.objects.filter(phase_code=phase_code, is_active=True).order_by("-version").first()
        )
    if template is None:
        raise JobCardError("No active job card template is configured for this department.")
    return template


def _empty(value):
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, tuple, dict)) and len(value) == 0:
        return True
    return False


def _decimal(value):
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        return None


def _saved_files(submission):
    saved = {}
    responses = submission.responses.select_related("field").prefetch_related("attachments")
    for response in responses:
        clips = []
        for attachment in response.attachments.order_by("pk"):
            clips.append(
                {
                    "pk": attachment.pk,
                    "name": attachment.file.name,
                    "original": attachment.original_name,
                    "kind": attachment.kind,
                }
            )
        if clips:
            saved[response.field.field_key] = clips
    return saved


def _video_batch(raw):
    if isinstance(raw, dict):
        chosen = [item for item in raw.get("files") or [] if item and (getattr(item, "size", 0) or 0) > 0]
        drop = set()
        for value in raw.get("drop") or []:
            try:
                drop.add(int(value))
            except (TypeError, ValueError):
                continue
        return chosen, drop
    if raw and (getattr(raw, "size", 0) or 0) > 0:
        return [raw], set()
    return [], set()


def _kind(filename, field_type):
    if field_type == FieldType.IMAGE:
        return MachineAttachment.Kind.IMAGE
    if field_type == FieldType.VIDEO:
        return MachineAttachment.Kind.VIDEO
    return MachineAttachment.Kind.DOCUMENT


def _validate_upload(field, upload):
    ext = os.path.splitext(upload.name or "")[1].lower()
    size = getattr(upload, "size", 0) or 0
    if field.field_type == FieldType.IMAGE:
        if ext not in IMAGE_EXT:
            return "Upload a JPG, PNG, or WEBP image."
        if size > MAX_IMAGE:
            return "Each photo must be 20 MB or smaller."
        try:
            upload.seek(0)
            image = Image.open(upload)
            image.verify()
            upload.seek(0)
        except (UnidentifiedImageError, OSError, ValueError):
            return "The uploaded image could not be read."
    elif field.field_type == FieldType.VIDEO:
        if ext not in VIDEO_EXT:
            return "Upload an MP4, WEBM, or MOV video."
        if size > MAX_VIDEO:
            return "Each video must be 200 MB or smaller."
    else:
        if ext not in DOC_EXT:
            return "Upload a PDF, Office, text, or image file."
        if size > MAX_DOC:
            return "Files must be 15 MB or smaller."
    return ""


def _qc_submission(machine):
    from workflow.models import ProductionPhase

    phase = ProductionPhase.objects.filter(code="QC").first()
    state = machine.phase_states.filter(phase=phase).first() if phase else None
    if state is None:
        raise JobCardError("Quality Control is not on this machine.")
    if state.status == "IN_PROGRESS":
        submission = (
            JobCardSubmission.objects.filter(
                machine=machine,
                phase_code="QC",
                cycle=state.cycle,
                status=JobCardSubmission.Status.DRAFT,
            )
            .order_by("-pk")
            .first()
        )
        if submission is None:
            submission = JobCardSubmission.objects.create(
                machine=machine,
                template=active_template("QC"),
                phase_code="QC",
                cycle=state.cycle,
                status=JobCardSubmission.Status.DRAFT,
            )
        return submission
    if state.status == "COMPLETED" and machine.status == "COMPLETED":
        submission = (
            JobCardSubmission.objects.filter(
                machine=machine,
                phase_code="QC",
                cycle=state.cycle,
                status=JobCardSubmission.Status.SUBMITTED,
            )
            .order_by("-revision", "-pk")
            .first()
        )
        if submission is None:
            raise JobCardError("There is no QC record to add a video to.")
        return submission
    raise JobCardError("Quality Control is not open for a video.")


def qc_card_template(submission):
    """Use the current QC card, which stores photos rather than video."""
    current = active_template("QC")
    if current is not None and current.fields.filter(field_key="qc_photo", is_active=True).exists():
        return current
    return submission.template if submission is not None else current


def _qc_video_field(submission):
    field = submission.template.fields.filter(field_key="qc_video", is_active=True).first()
    if field is None:
        current = qc_card_template(submission)
        field = current.fields.filter(field_key="qc_video", is_active=True).first()
        if field is None:
            raise JobCardError("This QC card has no video field.")
        submission.template = current
        submission.save(update_fields=["template"])
    return field


def attach_qc_video(machine, user, upload):
    if upload is None or not (getattr(upload, "size", 0) or 0):
        raise JobCardError("Choose a video first.")
    if (getattr(upload, "size", 0) or 0) > MAX_VIDEO:
        raise JobCardError("Each video must be 200 MB or smaller.")
    with transaction.atomic():
        submission = _qc_submission(machine)
        field = _qc_video_field(submission)
        response = submission.responses.filter(field=field).first()
        if response is None:
            response = JobCardResponse.objects.create(submission=submission, field=field, value_text="Video attached")
        if response.attachments.count() >= MAX_VIDEOS:
            raise JobCardError(f"Attach up to {MAX_VIDEOS} videos.")
        prepared = compress_video(upload)
        error = _validate_upload(field, prepared)
        if error:
            raise JobCardError(error)
        stored = _store_upload(machine, submission, response, field, prepared, user)
        if response.value_text != "Video attached":
            response.value_text = "Video attached"
            response.save(update_fields=["value_text"])
        log_audit(user, "qc.video", instance=machine, changes={"attachment": stored.pk})
        return stored


def remove_qc_video(machine, user, attachment_id):
    with transaction.atomic():
        submission = _qc_submission(machine)
        attachment = MachineAttachment.objects.filter(
            pk=attachment_id,
            machine=machine,
            submission=submission,
            kind=MachineAttachment.Kind.VIDEO,
        ).first()
        if attachment is None:
            raise JobCardError("That video is not on this QC record.")
        if attachment.file:
            attachment.file.delete(save=False)
        attachment.delete()
        log_audit(user, "qc.video.remove", instance=machine, changes={"attachment": attachment_id})


def _phase_submission(machine, phase_code, closed_message):
    from workflow.models import ProductionPhase

    phase = ProductionPhase.objects.filter(code=phase_code).first()
    state = machine.phase_states.filter(phase=phase).first() if phase else None
    if state is None:
        raise JobCardError(f"{phase_code} is not on this machine.")
    if state.status == "IN_PROGRESS":
        submission = (
            JobCardSubmission.objects.filter(
                machine=machine,
                phase_code=phase_code,
                cycle=state.cycle,
                status=JobCardSubmission.Status.DRAFT,
            )
            .order_by("-pk")
            .first()
        )
        if submission is None:
            submission = JobCardSubmission.objects.create(
                machine=machine,
                template=active_template(phase_code, machine),
                phase_code=phase_code,
                cycle=state.cycle,
                status=JobCardSubmission.Status.DRAFT,
            )
        return submission
    if state.status == "COMPLETED" and phase_code == "QC" and machine.status == "COMPLETED":
        submission = (
            JobCardSubmission.objects.filter(
                machine=machine,
                phase_code=phase_code,
                cycle=state.cycle,
                status=JobCardSubmission.Status.SUBMITTED,
            )
            .order_by("-revision", "-pk")
            .first()
        )
        if submission is None:
            raise JobCardError(closed_message)
        return submission
    raise JobCardError(closed_message)


def _phase_field(submission, field_key, missing_message):
    field = submission.template.fields.filter(field_key=field_key, is_active=True).first()
    if field is not None:
        return field
    current = active_template(submission.phase_code, submission.machine)
    field = current.fields.filter(field_key=field_key, is_active=True).first() if current else None
    if field is None:
        raise JobCardError(missing_message)
    submission.template = current
    submission.save(update_fields=["template"])
    return field


def attach_testing_video(machine, user, upload):
    if upload is None or not (getattr(upload, "size", 0) or 0):
        raise JobCardError("Choose a video first.")
    if (getattr(upload, "size", 0) or 0) > MAX_VIDEO:
        raise JobCardError("Each video must be 200 MB or smaller.")
    with transaction.atomic():
        submission = _phase_submission(machine, "TESTING", "Testing is not open for a video.")
        field = _phase_field(submission, "testing_video", "This testing card has no video field.")
        response = submission.responses.filter(field=field).first()
        if response is None:
            response = JobCardResponse.objects.create(submission=submission, field=field, value_text="Video attached")
        if response.attachments.count() >= MAX_VIDEOS:
            raise JobCardError(f"Attach up to {MAX_VIDEOS} videos.")
        prepared = compress_video(upload)
        error = _validate_upload(field, prepared)
        if error:
            raise JobCardError(error)
        stored = _store_upload(machine, submission, response, field, prepared, user)
        if response.value_text != "Video attached":
            response.value_text = "Video attached"
            response.save(update_fields=["value_text"])
        log_audit(user, "testing.video", instance=machine, changes={"attachment": stored.pk})
        return stored


def remove_testing_video(machine, user, attachment_id):
    with transaction.atomic():
        submission = _phase_submission(machine, "TESTING", "Testing is not open for a video.")
        attachment = MachineAttachment.objects.filter(
            pk=attachment_id,
            machine=machine,
            submission=submission,
            kind=MachineAttachment.Kind.VIDEO,
        ).first()
        if attachment is None:
            raise JobCardError("That video is not on this testing record.")
        if attachment.file:
            attachment.file.delete(save=False)
        attachment.delete()
        log_audit(user, "testing.video.remove", instance=machine, changes={"attachment": attachment_id})


def attach_qc_photo(machine, user, upload):
    if upload is None or not (getattr(upload, "size", 0) or 0):
        raise JobCardError("Choose a photo first.")
    if (getattr(upload, "size", 0) or 0) > MAX_IMAGE:
        raise JobCardError("Each photo must be 20 MB or smaller.")
    with transaction.atomic():
        submission = _phase_submission(machine, "QC", "There is no QC record to add a photo to.")
        field = _phase_field(submission, "qc_photo", "This QC card has no photo field.")
        response = submission.responses.filter(field=field).first()
        if response is None:
            response = JobCardResponse.objects.create(submission=submission, field=field, value_text="Photo attached")
        if response.attachments.count() >= MAX_PHOTOS:
            raise JobCardError(f"Attach up to {MAX_PHOTOS} photos.")
        prepared = compress_image(upload)
        error = _validate_upload(field, prepared)
        if error:
            raise JobCardError(error)
        stored = _store_upload(machine, submission, response, field, prepared, user)
        if response.value_text != "Photo attached":
            response.value_text = "Photo attached"
            response.save(update_fields=["value_text"])
        log_audit(user, "qc.photo", instance=machine, changes={"attachment": stored.pk})
        return stored


def remove_qc_photo(machine, user, attachment_id):
    with transaction.atomic():
        submission = _phase_submission(machine, "QC", "There is no QC record to change.")
        attachment = MachineAttachment.objects.filter(
            pk=attachment_id,
            machine=machine,
            submission=submission,
            kind=MachineAttachment.Kind.IMAGE,
        ).first()
        if attachment is None:
            raise JobCardError("That photo is not on this QC record.")
        if attachment.file:
            attachment.file.delete(save=False)
        attachment.delete()
        log_audit(user, "qc.photo.remove", instance=machine, changes={"attachment": attachment_id})


def _store_upload(machine, submission, response, field, upload, user):
    return MachineAttachment.objects.create(
        machine=machine,
        submission=submission,
        response=response,
        file=upload,
        original_name=os.path.basename(upload.name or "upload")[:240],
        kind=_kind(upload.name or "", field.field_type),
        caption=field.label,
        uploaded_by=user if getattr(user, "is_authenticated", False) else None,
    )


def _keep_previous_file(machine, submission, response, field, previous, user):
    MachineAttachment.objects.create(
        machine=machine,
        submission=submission,
        response=response,
        file=previous["name"],
        original_name=previous["original"],
        kind=previous["kind"],
        caption=field.label,
        uploaded_by=user if getattr(user, "is_authenticated", False) else None,
    )


def persist_submission(
    *,
    machine,
    user,
    phase_code,
    cycle,
    answers,
    files=None,
    status=JobCardSubmission.Status.SUBMITTED,
    remarks="",
    corrective_action="",
    correction_reason="",
    supersedes=None,
    revision=None,
    template=None,
    allow_existing=False,
    replace=None,
    require_all=False,
    skip_required=False,
):
    files = files or {}
    answers = answers or {}
    template = template or (replace.template if replace is not None else None) or (
        supersedes.template if supersedes else active_template(phase_code, machine)
    )
    fields = list(template.active_fields())
    strict = status == JobCardSubmission.Status.SUBMITTED

    def must_fill(field):
        conditional = field.section == "If not OK" or field.field_key == "test_problem"
        if skip_required or (conditional and str(answers.get("test_result") or "") != "NOT OK"):
            return False
        # Electrical: only OK / NOT OK radios are compulsory; value/remark text is optional.
        if phase_code == PhaseCode.ELECTRICAL:
            if field.field_type != FieldType.RADIO:
                return False
            return strict
        if require_all:
            return True
        return strict and field.required
    existing = None
    previous_files = {}
    if replace is not None:
        existing = replace
        previous_files = _saved_files(existing)
    elif supersedes is None:
        existing = (
            JobCardSubmission.objects.filter(
                machine=machine,
                phase_code=phase_code,
                cycle=cycle,
                status=JobCardSubmission.Status.DRAFT,
            )
            .order_by("-pk")
            .first()
        )
        if existing:
            previous_files = _saved_files(existing)
    elif supersedes is not None:
        previous_files = _saved_files(supersedes)
    errors = {}
    prepared = {}
    doomed = []

    for field in fields:
        raw = answers.get(field.field_key)
        upload = files.get(field.field_key)
        if field.field_type == FieldType.VIDEO:
            incoming, drop = _video_batch(upload)
            kept = [item for item in previous_files.get(field.field_key, []) if item["pk"] not in drop]
            doomed.extend(item["pk"] for item in previous_files.get(field.field_key, []) if item["pk"] in drop)
            compressed = []
            for one in incoming:
                size = getattr(one, "size", 0) or 0
                if size > MAX_VIDEO:
                    errors[field.field_key] = "Each video must be 200 MB or smaller."
                    break
                compressed.append(compress_video(one))
            else:
                for one in compressed:
                    upload_error = _validate_upload(field, one)
                    if upload_error:
                        errors[field.field_key] = upload_error
                        break
            if field.field_key not in errors and len(compressed) + len(kept) > MAX_VIDEOS:
                errors[field.field_key] = f"Attach up to {MAX_VIDEOS} videos."
            elif field.field_key not in errors and must_fill(field) and not compressed and not kept:
                errors[field.field_key] = MISSING
            prepared[field.field_key] = (field, {}, compressed, kept)
            continue
        if field.field_type in FieldType.FILE_TYPES:
            if upload and field.field_type == FieldType.IMAGE:
                upload = compress_image(upload)
            uploads = [upload] if upload else []
            kept = previous_files.get(field.field_key, []) if not upload else []
            if upload:
                upload_error = _validate_upload(field, upload)
                if upload_error:
                    errors[field.field_key] = upload_error
                    continue
            elif must_fill(field) and not kept:
                errors[field.field_key] = MISSING
            prepared[field.field_key] = (field, {}, uploads, kept)
            continue
        if upload:
            upload_error = _validate_upload(field, upload)
            if upload_error:
                errors[field.field_key] = upload_error
                continue
        value = _prepare_value(field, raw, upload, must_fill, errors)
        prepared[field.field_key] = (field, value, [], [])

    if errors:
        raise JobCardError("Review the highlighted job card fields.", errors)

    with transaction.atomic():
        if status == JobCardSubmission.Status.SUBMITTED and not allow_existing:
            clash = JobCardSubmission.objects.filter(
                machine=machine,
                phase_code=phase_code,
                cycle=cycle,
                status=JobCardSubmission.Status.SUBMITTED,
            )
            if existing:
                clash = clash.exclude(pk=existing.pk)
            if clash.exists():
                raise JobCardError("A job card for this phase has already been submitted and cannot be overwritten.")

        if existing and doomed:
            for attachment in MachineAttachment.objects.filter(pk__in=doomed, submission=existing):
                if attachment.file:
                    attachment.file.delete(save=False)
        if existing:
            existing.responses.all().delete()
            submission = existing
            submission.template = template
            if replace is None:
                submission.operator = user
            submission.remarks = remarks or ""
            submission.corrective_action = corrective_action or ""
            submission.status = status
            if status == JobCardSubmission.Status.SUBMITTED and not submission.submitted_at:
                submission.submitted_at = timezone.now()
            submission.save()
        else:
            submission = JobCardSubmission.objects.create(
                machine=machine,
                template=template,
                phase_code=phase_code,
                cycle=cycle,
                revision=revision or (supersedes.revision + 1 if supersedes else 1),
                status=status,
                operator=user,
                remarks=remarks or "",
                corrective_action=corrective_action or "",
                correction_reason=correction_reason or "",
                supersedes=supersedes,
                submitted_at=timezone.now() if status == JobCardSubmission.Status.SUBMITTED else None,
            )

        for key, (field, value, uploads, kept) in prepared.items():
            uploads = uploads or []
            kept = kept or []
            if field.field_type in FieldType.FILE_TYPES and not uploads and not kept:
                continue
            if value is None and not uploads and not kept:
                continue
            response = JobCardResponse.objects.create(submission=submission, field=field, **(value or {}))
            for item in kept:
                _keep_previous_file(machine, submission, response, field, item, user)
            for upload in uploads:
                _store_upload(machine, submission, response, field, upload, user)
        return submission


def _prepare_value(field, raw, upload, must_fill, errors):
    ftype = field.field_type
    if ftype in FieldType.FILE_TYPES:
        if must_fill(field) and not upload:
            errors[field.field_key] = MISSING
        return {}
    if ftype == FieldType.SIGNATURE:
        data = raw if isinstance(raw, dict) else {"name": raw or "", "confirmed": False}
        name = str(data.get("name") or "").strip().upper()
        confirmed = bool(data.get("confirmed"))
        if must_fill(field) and (not name or not confirmed):
            errors[field.field_key] = MISSING
        if _empty(name) and not confirmed:
            return None
        return {"value_text": name, "value_bool": confirmed}
    if ftype == FieldType.CHECKBOX and field.options:
        selected = raw if isinstance(raw, list) else ([] if _empty(raw) else [raw])
        selected = [str(item) for item in selected if str(item) in field.options]
        if must_fill(field) and not selected:
            errors[field.field_key] = MISSING
        if not selected:
            return None
        return {"value_json": selected, "value_text": ", ".join(selected)}
    if ftype == FieldType.CHECKBOX:
        checked = raw is True or raw == "on" or raw == "Yes"
        if must_fill(field) and not checked:
            errors[field.field_key] = MISSING
        return {"value_bool": checked, "value_text": "Yes" if checked else "No"}
    if ftype == FieldType.PASS_FAIL:
        value = str(raw or "").strip()
        if value and value not in PASS_VALUES:
            errors[field.field_key] = "Choose Pass, Fail, or N/A."
        if must_fill(field) and not value:
            errors[field.field_key] = MISSING
        if not value:
            return None
        return {"value_text": value}
    if ftype == FieldType.YES_NO:
        value = str(raw or "").strip()
        if value and value not in YES_VALUES:
            errors[field.field_key] = "Choose Yes or No."
        if must_fill(field) and not value:
            errors[field.field_key] = MISSING
        if not value:
            return None
        return {"value_text": value, "value_bool": value == "Yes"}
    if ftype in {FieldType.DROPDOWN, FieldType.RADIO}:
        value = str(raw or "").strip()
        if value and field.options and value not in field.options:
            errors[field.field_key] = "Choose one of the listed options."
        if must_fill(field) and not value:
            errors[field.field_key] = MISSING
        if not value:
            return None
        return {"value_text": value}
    if ftype in {FieldType.MEASUREMENT, FieldType.DECIMAL, FieldType.INTEGER}:
        if _empty(raw):
            if must_fill(field):
                errors[field.field_key] = MISSING
            return None
        number = _decimal(raw)
        if number is None:
            errors[field.field_key] = "Enter a valid number."
            return None
        if ftype == FieldType.INTEGER and number != number.to_integral_value():
            errors[field.field_key] = "Enter a whole number."
            return None
        text = format(number.normalize(), "f")
        return {"value_decimal": number.quantize(Decimal("0.0001")), "value_text": text}
    if ftype == FieldType.DATE:
        if _empty(raw):
            if must_fill(field):
                errors[field.field_key] = MISSING
            return None
        try:
            parsed = datetime.strptime(str(raw).strip(), "%Y-%m-%d").date()
        except ValueError:
            errors[field.field_key] = "Enter a valid date."
            return None
        return {"value_date": parsed, "value_text": parsed.isoformat()}
    if ftype == FieldType.TIME:
        if _empty(raw):
            if must_fill(field):
                errors[field.field_key] = MISSING
            return None
        text = str(raw).strip()
        parsed = None
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt).time()
                break
            except ValueError:
                continue
        if parsed is None:
            errors[field.field_key] = "Enter a valid time."
            return None
        return {"value_time": parsed, "value_text": parsed.strftime("%H:%M")}
    text = "" if raw is None else str(raw).strip().upper()
    if must_fill(field) and not text:
        errors[field.field_key] = MISSING
        return None
    if not text:
        return None
    return {"value_text": text}


def submission_form_state(submission):
    values = {}
    files = {}
    if submission is None:
        return values, files
    responses = submission.responses.select_related("field").prefetch_related("attachments")
    for response in responses:
        key = response.field.field_key
        ftype = response.field.field_type
        if ftype == FieldType.SIGNATURE:
            values[key] = {"name": response.value_text, "confirmed": bool(response.value_bool)}
        elif ftype == FieldType.CHECKBOX and response.field.options:
            values[key] = response.value_json or []
        elif ftype == FieldType.CHECKBOX:
            values[key] = bool(response.value_bool)
        elif ftype == FieldType.YES_NO:
            text = (response.value_text or "").strip()
            if text in {"Yes", "No"}:
                values[key] = text
            elif response.value_bool is True:
                values[key] = "Yes"
            elif response.value_bool is False:
                values[key] = "No"
            else:
                values[key] = text
        elif response.value_decimal is not None:
            values[key] = format(response.value_decimal.normalize(), "f")
        elif response.value_date:
            values[key] = response.value_date.isoformat()
        elif response.value_time:
            values[key] = response.value_time.strftime("%H:%M")
        else:
            values[key] = response.value_text
        clips = list(response.attachments.order_by("pk"))
        if not clips:
            continue
        files[key] = clips if ftype in {FieldType.VIDEO, FieldType.IMAGE} else clips[0]
    return values, files


def answers_for_template(submission, target_template):
    """Map a saved submission onto another template version (match by field_key, then label)."""
    if submission is None:
        return {}, {}
    values, files = submission_form_state(submission)
    if not target_template or submission.template_id == getattr(target_template, "pk", None):
        return values, files
    by_label = {}
    for response in submission.responses.select_related("field"):
        label = (response.field.label or "").strip().casefold()
        if label:
            by_label[label] = response.field.field_key
    mapped = {}
    mapped_files = {}
    for field in target_template.active_fields():
        key = field.field_key
        if key in values:
            mapped[key] = values[key]
            if key in files:
                mapped_files[key] = files[key]
            continue
        prior_key = by_label.get((field.label or "").strip().casefold())
        if prior_key and prior_key in values:
            mapped[key] = values[prior_key]
            if prior_key in files:
                mapped_files[key] = files[prior_key]
    return mapped, mapped_files


def latest_phase_submission(machine, phase_code, *, before_cycle=None):
    """Most recent submitted/draft card for this phase (used to prefill rework cycles)."""
    query = JobCardSubmission.objects.filter(
        machine=machine,
        phase_code=phase_code,
    ).exclude(status=JobCardSubmission.Status.SUPERSEDED)
    if before_cycle is not None:
        query = query.filter(cycle__lt=before_cycle)
    return query.order_by("-cycle", "-revision", "-pk").first()


def ensure_phase_draft(machine, user, phase_code, cycle):
    """
    Return the working draft for this phase/cycle.
    On a new rework cycle, copy the previous answers/files so operators only change what needs fixing.
    Prefers the current active template and remaps answers by field key / label.
    """
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
    try:
        target_template = active_template(phase_code, machine)
    except JobCardError:
        target_template = None

    if draft is not None:
        # Empty draft left from an older mismatch — rebuild from the prior card.
        if not draft.responses.exists():
            draft.delete()
        elif target_template is not None and draft.template_id != target_template.id:
            # Word/Excel re-import created a newer checklist — move the open draft onto it.
            old_by_key = {response.field.field_key: response for response in draft.responses.select_related("field")}
            old_by_label = {
                (response.field.label or "").strip().casefold(): response
                for response in draft.responses.select_related("field")
                if (response.field.label or "").strip()
            }
            with transaction.atomic():
                draft.template = target_template
                draft.save(update_fields=["template", "updated_at"])
                draft.responses.all().delete()
                for field in target_template.active_fields():
                    source = old_by_key.get(field.field_key) or old_by_label.get(
                        (field.label or "").strip().casefold()
                    )
                    if source is None:
                        continue
                    JobCardResponse.objects.create(
                        submission=draft,
                        field=field,
                        value_text=source.value_text,
                        value_bool=source.value_bool,
                        value_decimal=source.value_decimal,
                        value_date=source.value_date,
                        value_time=source.value_time,
                        value_json=source.value_json,
                    )
            return draft, False
        else:
            return draft, False

    prior = latest_phase_submission(machine, phase_code, before_cycle=cycle)
    if prior is None:
        return None, False

    if target_template is None:
        target_template = prior.template

    prior_by_key = {}
    prior_by_label = {}
    for response in prior.responses.select_related("field").prefetch_related("attachments"):
        prior_by_key[response.field.field_key] = response
        label = (response.field.label or "").strip().casefold()
        if label:
            prior_by_label[label] = response

    with transaction.atomic():
        draft = JobCardSubmission.objects.create(
            machine=machine,
            template=target_template,
            phase_code=phase_code,
            cycle=cycle,
            revision=1,
            status=JobCardSubmission.Status.DRAFT,
            operator=user if getattr(user, "is_authenticated", False) else prior.operator,
            remarks=prior.remarks or "",
            corrective_action="",
        )
        for field in target_template.active_fields():
            source = prior_by_key.get(field.field_key) or prior_by_label.get((field.label or "").strip().casefold())
            if source is None:
                continue
            cloned = JobCardResponse.objects.create(
                submission=draft,
                field=field,
                value_text=source.value_text,
                value_bool=source.value_bool,
                value_decimal=source.value_decimal,
                value_date=source.value_date,
                value_time=source.value_time,
                value_json=source.value_json,
            )
            for attachment in source.attachments.order_by("pk"):
                MachineAttachment.objects.create(
                    machine=machine,
                    submission=draft,
                    response=cloned,
                    file=attachment.file.name if attachment.file else "",
                    original_name=attachment.original_name,
                    kind=attachment.kind,
                    caption=attachment.caption,
                    uploaded_by=user if getattr(user, "is_authenticated", False) else attachment.uploaded_by,
                )
        log_audit(
            user,
            "jobcard.prefill",
            instance=draft,
            changes={"from_cycle": prior.cycle, "from_submission": prior.pk, "template": target_template.pk},
        )
    return draft, True


def answers_from_request(template, post, files):
    answers = {}
    uploads = {}
    for field in template.active_fields():
        if field.field_type == FieldType.VIDEO:
            chosen = [
                item
                for item in files.getlist(f"file_{field.field_key}")
                if item and (getattr(item, "size", 0) or 0) > 0
            ]
            drop = []
            for value in post.getlist(f"drop_video_{field.field_key}"):
                try:
                    drop.append(int(value))
                except (TypeError, ValueError):
                    continue
            uploads[field.field_key] = {"files": chosen, "drop": drop}
            continue
        if field.field_type in FieldType.FILE_TYPES:
            upload = files.get(f"file_{field.field_key}")
            uploads[field.field_key] = upload if upload else None
            continue
        if field.field_type == FieldType.SIGNATURE:
            answers[field.field_key] = {
                "name": post.get(f"f_{field.field_key}", ""),
                "confirmed": post.get(f"sig_{field.field_key}") == "on",
            }
            continue
        if field.field_type == FieldType.CHECKBOX and field.options:
            answers[field.field_key] = post.getlist(f"f_{field.field_key}")
            continue
        if field.field_type == FieldType.CHECKBOX:
            answers[field.field_key] = post.get(f"f_{field.field_key}") == "on"
            continue
        answers[field.field_key] = post.get(f"f_{field.field_key}", "")
    return answers, uploads


def revise_submission(submission, user, answers, files, reason):
    if not user.is_management:
        raise PermissionDenied("Only an administrator can revise a submitted job card.")
    reason = (reason or "").strip()
    if not reason:
        raise JobCardError("Enter the reason for this correction.")
    if submission.status != JobCardSubmission.Status.SUBMITTED:
        raise JobCardError("Only a submitted job card can be revised.")
    with transaction.atomic():
        revised = persist_submission(
            machine=submission.machine,
            user=user,
            phase_code=submission.phase_code,
            cycle=submission.cycle,
            answers=answers,
            files=files,
            status=JobCardSubmission.Status.SUBMITTED,
            remarks=submission.remarks,
            corrective_action=submission.corrective_action,
            correction_reason=reason,
            supersedes=submission,
            template=submission.template,
            allow_existing=True,
        )
        submission.status = JobCardSubmission.Status.SUPERSEDED
        submission.save(update_fields=["status", "updated_at"])
        log_audit(
            user,
            "jobcard.revise",
            instance=revised,
            changes={"reason": reason, "previous": submission.pk, "revision": revised.revision},
        )
        from workflow.models import WorkflowEvent

        WorkflowEvent.objects.create(
            machine=submission.machine,
            event_type=EventType.REVISION,
            cycle=submission.cycle,
            actor=user,
            remarks=reason,
            metadata={"phase": submission.phase_code, "revision": revised.revision},
        )
        return revised


def _matrix_from_fields(fields, prefix, leader_check=None):
    """Build a labeled row×column grid from help_text like prefix|row|col."""
    columns = []
    rows = {}
    leader = None
    for field in fields:
        help_text = field.help_text or ""
        if leader_check and leader_check(field, help_text):
            leader = field
            continue
        row_name = None
        col_name = None
        if help_text.startswith(f"{prefix}|"):
            parts = help_text.split("|")
            if len(parts) >= 3:
                row_name, col_name = parts[1], parts[2]
        if not row_name or not col_name:
            match = re.match(r"^(.*?)\s*[—\-]\s*(.+?)(?:\s*\(CCN\))?\s*$", field.label)
            if match:
                row_name, col_name = match.group(1).strip(), match.group(2).strip()
        if not row_name or not col_name:
            continue
        if col_name not in columns:
            columns.append(col_name)
        rows.setdefault(row_name, {})[col_name] = field
    if not rows:
        return None
    matrix_rows = [{"name": name, "cells": [cells.get(col) for col in columns]} for name, cells in rows.items()]
    return {"bars": columns, "columns": columns, "rows": matrix_rows, "leader": leader}


def _pressure_matrix_from_fields(fields):
    """Build Belt/Pulley × Bar CCN grid from imported Word pressure fields."""
    return _matrix_from_fields(
        fields,
        "press",
        leader_check=lambda field, help_text: help_text.startswith("press|leader|")
        or bool(re.search(r"checked\s+by|team\s+leader", field.label, re.I)),
    )


def group_fields(fields):
    groups = []
    index = {}
    for field in fields:
        section = field.section or "General"
        if section not in index:
            index[section] = {"name": section, "fields": []}
            groups.append(index[section])
        index[section]["fields"].append(field)
    for group in groups:
        name = group["name"]
        if name == "Fill as per pressure rating":
            matrix = _pressure_matrix_from_fields(group["fields"])
            if matrix:
                group["pressure_matrix"] = matrix
        elif name == "Major parts details":
            matrix = _matrix_from_fields(group["fields"], "parts")
            if matrix:
                group["parts_matrix"] = matrix
        elif name in {"Vibration readings", "Vibration data", "During testing"}:
            vib_fields = [field for field in group["fields"] if (field.help_text or "").startswith("vib|")]
            if vib_fields:
                matrix = _matrix_from_fields(vib_fields, "vib")
                if matrix:
                    group["vibration_matrix"] = matrix
                    before, after, seen_vib = [], [], False
                    for field in group["fields"]:
                        if (field.help_text or "").startswith("vib|"):
                            seen_vib = True
                            continue
                        if seen_vib:
                            after.append(field)
                        else:
                            before.append(field)
                    group["fields"] = before
                    group["fields_after_vibration"] = after
        elif name == "Oil fill":
            matrix = _matrix_from_fields(group["fields"], "oil")
            if matrix:
                # Oil fill is a single-column LTR list (1ST/2ND/3RD/TOTAL).
                group["oil_matrix"] = {
                    "rows": [{"name": row["name"], "field": next((cell for cell in row["cells"] if cell), None)} for row in matrix["rows"]],
                    "unit": "LTR",
                }
        elif name == "General check":
            if group["fields"] and all(field.field_type == "yes_no" for field in group["fields"]):
                group["general_check_table"] = True
        elif name == "Belt tension reference":
            notes = []
            inputs = []
            for field in group["fields"]:
                help_text = field.help_text or ""
                if help_text.startswith("belt_chart|") or "chart" in field.field_key:
                    notes.append(field)
                else:
                    inputs.append(field)
            if notes:
                group["belt_notes"] = notes
                group["fields"] = inputs
    return groups
