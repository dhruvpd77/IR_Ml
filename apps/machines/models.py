from django.db import models
from django.utils import timezone

from accounts.models import User
from core.constants import MachineStatus, Priority, ShopLine, StationKind


class ProductionStation(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    line = models.CharField(max_length=16, choices=ShopLine.CHOICES, blank=True, default="", db_index=True)
    kind = models.CharField(max_length=16, choices=StationKind.CHOICES, blank=True, default="")
    sort_order = models.PositiveIntegerField(default=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["line", "sort_order", "code"]

    def __str__(self):
        if self.line:
            return f"{self.get_line_display()} · {self.name}"
        return f"{self.code} — {self.name}"

    @property
    def line_label(self):
        return self.get_line_display() if self.line else ""

    @property
    def kind_label(self):
        return self.get_kind_display() if self.kind else ""


class MachineSequence(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    last_number = models.PositiveIntegerField(default=0)


class Machine(models.Model):
    machine_id = models.CharField(max_length=32, unique=True, db_index=True)
    status = models.CharField(max_length=32, choices=MachineStatus.CHOICES, default=MachineStatus.DRAFT, db_index=True)
    current_phase = models.CharField(max_length=32, default="PLANNING", db_index=True)
    priority = models.CharField(max_length=16, choices=Priority.CHOICES, default=Priority.STANDARD, db_index=True)
    planner_serial = models.CharField(max_length=64, unique=True, null=True, blank=True)
    production_serial = models.CharField(max_length=64, unique=True, null=True, blank=True)
    station = models.ForeignKey(
        ProductionStation,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="machines",
    )
    production_remarks = models.TextField(blank=True)
    test_area = models.CharField(max_length=32, blank=True, default="")
    is_under_rework = models.BooleanField(default=False, db_index=True)
    rework_count = models.PositiveIntegerField(default=0)
    qc_approved_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="qc_approvals",
    )
    qc_approved_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="machines_created",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.machine_id

    @property
    def status_label(self):
        return MachineStatus.LABELS.get(self.status, self.status)

    @property
    def priority_label(self):
        return Priority.LABELS.get(self.priority, self.priority)

    def progress_percent(self):
        states = list(self.phase_states.all())
        if not states:
            return 0
        done = sum(1 for state in states if state.status == "COMPLETED")
        return round(done * 100 / len(states))


class MachinePlanningData(models.Model):
    machine = models.OneToOneField(Machine, on_delete=models.CASCADE, related_name="planning")
    company = models.CharField(max_length=160)
    work_order = models.CharField(max_length=80, db_index=True)
    ccn = models.CharField(max_length=80, blank=True, db_index=True)
    model_description = models.CharField(max_length=240, db_index=True)
    machine_name = models.CharField(
        max_length=160,
        blank=True,
        default="",
        db_index=True,
        help_text="Short name from Model Catalog (Excel machine NAME column).",
    )
    machine_type = models.CharField(max_length=120, blank=True)
    calibration = models.CharField(max_length=160, blank=True)
    shift = models.CharField(max_length=40, blank=True)
    test_report_bar = models.CharField(max_length=160, blank=True)
    export_packing_required = models.CharField(max_length=80, blank=True)
    customer_inspection = models.CharField(max_length=80, blank=True)
    customer_inspection_date = models.DateField(null=True, blank=True)
    raw_import = models.JSONField(default=dict, blank=True)
    submitted_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="planning_submissions",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Machine planning data"
        indexes = [
            models.Index(fields=["work_order", "ccn", "model_description"]),
        ]

    def __str__(self):
        return f"{self.work_order} · {self.model_description}"


class MonthlyTentativePlan(models.Model):
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField()
    machine_count = models.PositiveIntegerField(default=0)
    updated_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tentative_plans",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-year", "-month"]
        constraints = [
            models.UniqueConstraint(fields=["year", "month"], name="uniq_tentative_month"),
        ]

    def __str__(self):
        return f"{self.year}-{self.month:02d}: {self.machine_count}"

    @property
    def period_label(self):
        from calendar import month_name

        return f"{month_name[self.month]} {self.year}"


class MachineNote(models.Model):
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="machine_notes")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Note on {self.machine.machine_id}"


class PlanningCatalogItem(models.Model):
    company = models.CharField(max_length=160, db_index=True)
    machine_type = models.CharField(max_length=120, db_index=True)
    model_description = models.CharField(max_length=240)
    ccn = models.CharField(max_length=80)
    machine_name = models.CharField(
        max_length=160,
        blank=True,
        default="",
        db_index=True,
        help_text="Short machine name from Excel column machine NAME (e.g. ML37IE-A7.5).",
    )
    job_card_key = models.CharField(
        max_length=160,
        blank=True,
        default="",
        db_index=True,
        help_text="Checklist sheet name from Job Card Detail. Empty means no Assembly/Testing card.",
    )
    job_card_format = models.CharField(
        max_length=16,
        blank=True,
        default="",
        db_index=True,
        help_text="excel = Production Checklists workbook; word = file in jobcard_word_file/.",
    )
    uploaded_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="catalog_uploads",
    )
    uploaded_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["company", "machine_type", "model_description"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "machine_type", "model_description"],
                name="uniq_catalog_model",
            )
        ]

    def __str__(self):
        return f"{self.company} · {self.machine_type} · {self.model_description}"


class ImportBatch(models.Model):
    class Status(models.TextChoices):
        PREVIEW = "PREVIEW", "Preview"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    source_file = models.FileField(upload_to="imports/%Y/%m/")
    original_name = models.CharField(max_length=240, blank=True)
    uploaded_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="import_batches")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PREVIEW)
    total_rows = models.PositiveIntegerField(default=0)
    valid_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"Import {self.pk} · {self.original_name}"


class ImportRow(models.Model):
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField()
    raw_data = models.JSONField(default=dict, blank=True)
    normalized = models.JSONField(default=dict, blank=True)
    is_valid = models.BooleanField(default=False)
    is_duplicate = models.BooleanField(default=False)
    errors = models.JSONField(default=list, blank=True)
    machine = models.ForeignKey(Machine, null=True, blank=True, on_delete=models.SET_NULL, related_name="import_rows")

    class Meta:
        ordering = ["row_number"]
        unique_together = [("batch", "row_number")]
