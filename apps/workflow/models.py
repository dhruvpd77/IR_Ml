from django.db import models

from accounts.models import Department, User
from core.constants import EventType, PhaseStatus
from machines.models import Machine


class ProductionPhase(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    sequence = models.PositiveIntegerField()
    parallel_group = models.CharField(max_length=32, blank=True)
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="phases",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sequence", "name"]

    def __str__(self):
        return self.name


class MachinePhaseState(models.Model):
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name="phase_states")
    phase = models.ForeignKey(ProductionPhase, on_delete=models.PROTECT, related_name="machine_states")
    status = models.CharField(max_length=16, choices=PhaseStatus.CHOICES, default=PhaseStatus.PENDING)
    cycle = models.PositiveIntegerField(default=1)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    started_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="phases_started",
    )
    completed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="phases_completed",
    )
    rework_open = models.BooleanField(default=False)

    class Meta:
        unique_together = [("machine", "phase")]
        ordering = ["phase__sequence", "phase__name"]

    def __str__(self):
        return f"{self.machine.machine_id} · {self.phase.code} · {self.status}"


class WorkflowEvent(models.Model):
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name="events")
    phase = models.ForeignKey(ProductionPhase, null=True, blank=True, on_delete=models.SET_NULL, related_name="events")
    event_type = models.CharField(max_length=32, choices=EventType.CHOICES)
    cycle = models.PositiveIntegerField(default=1)
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="workflow_events")
    remarks = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [
            models.Index(fields=["machine", "created_at"]),
            models.Index(fields=["event_type", "created_at"]),
        ]

    def __str__(self):
        return f"{self.machine.machine_id} · {self.event_type}"
