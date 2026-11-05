from django.db import models

from accounts.models import User
from machines.models import Machine
from workflow.models import ProductionPhase


class ReworkRequest(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        AWAITING_REINSPECTION = "AWAITING_REINSPECTION", "Awaiting reinspection"
        CLOSED = "CLOSED", "Closed"

    rework_code = models.CharField(max_length=32, unique=True, blank=True)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name="reworks")
    rejected_phase = models.ForeignKey(
        ProductionPhase,
        on_delete=models.PROTECT,
        related_name="reworks_from",
    )
    assigned_phase = models.ForeignKey(
        ProductionPhase,
        on_delete=models.PROTECT,
        related_name="reworks_to",
    )
    reason = models.TextField()
    rejected_by = models.ForeignKey(
        User,
        null=True,
        on_delete=models.SET_NULL,
        related_name="reworks_raised",
    )
    rejected_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OPEN)
    cycle_number = models.PositiveIntegerField(default=1)
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


class ReworkAction(models.Model):
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
