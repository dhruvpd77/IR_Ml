import os
import uuid

from django.db import models

from accounts.models import User
from core.constants import FieldType, PhaseCode
from machines.models import Machine


def attachment_upload(instance, filename):
    base = os.path.basename(filename).replace("\x00", "")[:120] or "upload"
    return f"attachments/{instance.machine.machine_id}/{uuid.uuid4().hex}_{base}"


class JobCardTemplate(models.Model):
    phase_code = models.CharField(max_length=32, choices=PhaseCode.CHOICES)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="job_card_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["phase_code", "-version"]
        unique_together = [("phase_code", "version")]

    def __str__(self):
        return f"{self.name} v{self.version}"

    def active_fields(self):
        return self.fields.filter(is_active=True).order_by("sort_order", "pk")


class JobCardField(models.Model):
    template = models.ForeignKey(JobCardTemplate, on_delete=models.CASCADE, related_name="fields")
    field_key = models.SlugField(max_length=80)
    label = models.CharField(max_length=200)
    field_type = models.CharField(max_length=32, choices=FieldType.CHOICES)
    section = models.CharField(max_length=120, blank=True)
    help_text = models.CharField(max_length=240, blank=True)
    placeholder = models.CharField(max_length=160, blank=True)
    unit = models.CharField(max_length=32, blank=True)
    options = models.JSONField(default=list, blank=True)
    required = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "pk"]
        unique_together = [("template", "field_key")]

    def __str__(self):
        return self.label


class JobCardSubmission(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        SUPERSEDED = "SUPERSEDED", "Superseded"

    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name="job_card_submissions")
    template = models.ForeignKey(JobCardTemplate, on_delete=models.PROTECT, related_name="submissions")
    phase_code = models.CharField(max_length=32, choices=PhaseCode.CHOICES)
    cycle = models.PositiveIntegerField(default=1)
    revision = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    operator = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="job_card_submissions",
    )
    remarks = models.TextField(blank=True)
    corrective_action = models.TextField(blank=True)
    correction_reason = models.TextField(blank=True)
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="later_revisions",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-submitted_at", "-pk"]
        indexes = [
            models.Index(fields=["machine", "phase_code", "cycle", "status"]),
        ]

    def __str__(self):
        return f"{self.machine.machine_id} · {self.phase_code} · r{self.revision}"


class JobCardResponse(models.Model):
    submission = models.ForeignKey(JobCardSubmission, on_delete=models.CASCADE, related_name="responses")
    field = models.ForeignKey(JobCardField, on_delete=models.PROTECT, related_name="responses")
    value_text = models.TextField(blank=True)
    value_decimal = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    value_bool = models.BooleanField(null=True, blank=True)
    value_date = models.DateField(null=True, blank=True)
    value_time = models.TimeField(null=True, blank=True)
    value_json = models.JSONField(null=True, blank=True)

    class Meta:
        unique_together = [("submission", "field")]

    def display_value(self):
        field = self.field
        if field.field_type == FieldType.SIGNATURE:
            confirmed = "Confirmed" if self.value_bool else "Not confirmed"
            return f"{self.value_text} ({confirmed})" if self.value_text else confirmed
        if field.field_type == FieldType.CHECKBOX and self.value_json:
            return ", ".join(self.value_json)
        if field.field_type in {FieldType.MEASUREMENT, FieldType.DECIMAL, FieldType.INTEGER} and self.value_decimal is not None:
            unit = f" {field.unit}" if field.unit else ""
            number = self.value_decimal
            if field.field_type == FieldType.INTEGER:
                number = int(number)
            return f"{number}{unit}"
        if self.value_date:
            return self.value_date.strftime("%d %b %Y")
        if self.value_time:
            return self.value_time.strftime("%H:%M")
        if self.value_bool is not None and field.field_type == FieldType.YES_NO:
            return "Yes" if self.value_bool else "No"
        if self.value_text:
            return self.value_text
        return "—"


class MachineAttachment(models.Model):
    class Kind(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"
        DOCUMENT = "document", "Document"

    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name="attachments")
    submission = models.ForeignKey(
        JobCardSubmission,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    response = models.ForeignKey(
        JobCardResponse,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    rework = models.ForeignKey(
        "rework.ReworkRequest",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(upload_to=attachment_upload)
    original_name = models.CharField(max_length=240, blank=True)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.DOCUMENT)
    caption = models.CharField(max_length=240, blank=True)
    uploaded_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="uploads")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.original_name or self.file.name
