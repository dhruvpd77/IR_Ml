from django.db import models

from accounts.models import User
from machines.models import Machine
from workflow.models import ProductionPhase


class ReworkRequest(models.Model):
    """Open shop-floor rework: always Production station first, then a fixed path back to the origin phase."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"
        # Kept for older rows created before the path-based rework redesign.
        AWAITING_REINSPECTION = "AWAITING_REINSPECTION", "Awaiting reinspection"

    rework_code = models.CharField(max_length=32, unique=True, blank=True)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name="reworks")
    rejected_phase = models.ForeignKey(
        ProductionPhase,
        on_delete=models.PROTECT,
        related_name="reworks_from",
        help_text="Origin phase where rework was raised.",
    )
    assigned_phase = models.ForeignKey(
        ProductionPhase,
        on_delete=models.PROTECT,
        related_name="reworks_to",
        help_text="Phase currently working this rework.",
    )
    reason = models.TextField(help_text="Problem description entered when rework was raised.")
    rejected_by = models.ForeignKey(
        User,
        null=True,
        on_delete=models.SET_NULL,
        related_name="reworks_raised",
    )
    rejected_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OPEN)
    cycle_number = models.PositiveIntegerField(default=1)
    path_codes = models.CharField(
        max_length=120,
        blank=True,
        help_text="Comma-separated phase codes, starting with PRODUCTION and ending at the origin.",
    )
    path_index = models.PositiveIntegerField(default=0)
    reinspection_status = models.CharField(max_length=32, default="PENDING")
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-rejected_at"]

    def __str__(self):
        return self.rework_code or f"Rework {self.pk}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.rework_code:
            self.rework_code = f"IR-RW-{self.pk:06d}"
            super().save(update_fields=["rework_code"])

    @property
    def path_list(self):
        return [code for code in (self.path_codes or "").split(",") if code]

    @property
    def origin_code(self):
        return self.rejected_phase.code if self.rejected_phase_id else ""

    @property
    def current_code(self):
        path = self.path_list
        if not path:
            return self.assigned_phase.code if self.assigned_phase_id else ""
        index = min(self.path_index, len(path) - 1)
        return path[index]

    @property
    def is_return_step(self):
        path = self.path_list
        return bool(path) and self.path_index >= len(path) - 1

    @property
    def is_intermediate_step(self):
        path = self.path_list
        return bool(path) and 0 < self.path_index < len(path) - 1


class ReworkNote(models.Model):
    class NoteType(models.TextChoices):
        PROBLEM = "PROBLEM", "Problem"
        RESOLUTION = "RESOLUTION", "Resolution"

    request = models.ForeignKey(ReworkRequest, on_delete=models.CASCADE, related_name="notes")
    phase_code = models.CharField(max_length=32)
    note_type = models.CharField(max_length=16, choices=NoteType.choices)
    text = models.TextField()
    author = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rework_notes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.note_type} · {self.phase_code}"


class ReworkAction(models.Model):
    """Legacy corrective-action rows; new flow stores comments on ReworkNote."""

    request = models.ForeignKey(ReworkRequest, on_delete=models.CASCADE, related_name="actions")
    corrective_action = models.TextField()
    resolution_remarks = models.TextField(blank=True)
    corrected_by = models.ForeignKey(
        User,
        null=True,
        on_delete=models.SET_NULL,
        related_name="rework_actions",
    )
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["completed_at"]

    def __str__(self):
        return f"Action for {self.request.rework_code}"
