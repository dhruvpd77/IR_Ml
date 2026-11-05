from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncMonth, TruncWeek
from django.utils import timezone

from core.constants import MachineStatus, PhaseCode, PhaseStatus, Priority
from core.formatters import format_seconds

STAGE_ORDER = (
    PhaseCode.PLANNING,
    PhaseCode.PLANNER,
    PhaseCode.PRODUCTION,
    PhaseCode.ASSEMBLY,
    PhaseCode.ELECTRICAL,
    PhaseCode.TESTING,
    PhaseCode.EOL,
    PhaseCode.QC,
)
STAGE_LABELS = {
    PhaseCode.PLANNING: "Planning data entry",
    PhaseCode.PLANNER: "Serial assignment",
    PhaseCode.PRODUCTION: "Production",
    PhaseCode.ASSEMBLY: "Assembly",
    PhaseCode.ELECTRICAL: "Electrical",
    PhaseCode.TESTING: "Testing",
    PhaseCode.EOL: "End of line",
    PhaseCode.QC: "Quality control",
}
CARD_META = {
    "all": {"label": "Total machines", "tone": "navy", "icon": "layers", "limit": None},
    "today": {"label": "Registered today", "tone": "blue", "icon": "calendar-plus", "limit": PhaseCode.PLANNING},
    "planning": {"label": "Planning and serial", "tone": "slate", "icon": "clipboard-list", "limit": PhaseCode.PLANNER},
    "production": {"label": "With production", "tone": "blue", "icon": "map-pin", "limit": PhaseCode.PRODUCTION},
    "line": {"label": "Assembly and electrical", "tone": "amber", "icon": "wrench", "limit": PhaseCode.ELECTRICAL},
    "assembly": {"label": "In assembly", "tone": "amber", "icon": "wrench", "limit": PhaseCode.ASSEMBLY},
    "electrical": {"label": "In electrical", "tone": "amber", "icon": "zap", "limit": PhaseCode.ELECTRICAL},
    "testing": {"label": "In testing", "tone": "blue", "icon": "gauge", "limit": PhaseCode.TESTING},
    "eol": {"label": "In EOL", "tone": "blue", "icon": "package-check", "limit": PhaseCode.EOL},
    "qc": {"label": "In QC", "tone": "red", "icon": "shield-check", "limit": PhaseCode.QC},
    "completed": {"label": "Completed", "tone": "green", "icon": "circle-check", "limit": None},
    "rework-open": {"label": "Open rework", "tone": "red", "icon": "rotate-ccw", "limit": "REWORK"},
    "rework": {"label": "Under rework", "tone": "red", "icon": "rotate-ccw", "limit": "REWORK"},
}

from jobcards.models import JobCardSubmission
from machines.models import Machine
from rework.models import ReworkRequest
from workflow.models import MachinePhaseState, ProductionPhase, WorkflowEvent


def _span_labels(days):
    today = timezone.localdate()
    return [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def admin_stats():
    today = timezone.localdate()
    machines = Machine.objects.all()
    phase_rows = ProductionPhase.objects.filter(is_active=True).annotate(
        open_count=Count("machine_states", filter=Q(machine_states__status=PhaseStatus.IN_PROGRESS)),
        done_count=Count("machine_states", filter=Q(machine_states__status=PhaseStatus.COMPLETED)),
    )
    on_line = machines.filter(status=MachineStatus.IN_PRODUCTION)
    assembly_open = on_line.filter(
        phase_states__phase__code=PhaseCode.ASSEMBLY, phase_states__status=PhaseStatus.IN_PROGRESS
    ).distinct().count()
    electrical_open = on_line.filter(
        phase_states__phase__code=PhaseCode.ELECTRICAL, phase_states__status=PhaseStatus.IN_PROGRESS
    ).distinct().count()
    cards = [
        ("all", "Total machines", machines.count(), "navy", "layers", None, ""),
        ("today", "Registered today", machines.filter(created_at__date=today).count(), "blue", "calendar-plus", PhaseCode.PLANNING, "Already inside the total"),
        ("planning", "Planning and serial", machines.filter(status__in=[MachineStatus.DRAFT, MachineStatus.WITH_PLANNER]).count(), "slate", "clipboard-list", PhaseCode.PLANNER, ""),
        ("production", "With production", machines.filter(status=MachineStatus.WITH_PRODUCTION).count(), "blue", "map-pin", PhaseCode.PRODUCTION, ""),
        ("line", "Assembly and electrical", on_line.count(), "amber", "wrench", PhaseCode.ELECTRICAL, f"Assembly open {assembly_open} · Electrical open {electrical_open}"),
        ("testing", "In testing", machines.filter(status=MachineStatus.IN_TESTING).count(), "blue", "gauge", PhaseCode.TESTING, ""),
        ("eol", "In EOL", machines.filter(status=MachineStatus.IN_EOL).count(), "blue", "package-check", PhaseCode.EOL, ""),
        ("qc", "In QC", machines.filter(status=MachineStatus.IN_QC).count(), "red", "shield-check", PhaseCode.QC, ""),
        ("completed", "Completed", machines.filter(status=MachineStatus.COMPLETED).count(), "green", "circle-check", None, ""),
        ("rework-open", "Open rework", ReworkRequest.objects.filter(status=ReworkRequest.Status.OPEN).count(), "red", "rotate-ccw", "REWORK", "Already inside the total"),
        ("rework", "Under rework", machines.filter(is_under_rework=True).exclude(status=MachineStatus.COMPLETED).count(), "red", "rotate-ccw", "REWORK", "Already inside the total"),
    ]
    days = _span_labels(14)
    daily = {
        "labels": [day.strftime("%d %b") for day in days],
        "registered": [machines.filter(created_at__date=day).count() for day in days],
        "completed": [machines.filter(qc_approved_at__date=day).count() for day in days],
    }
    priority = {row["priority"]: row["total"] for row in machines.values("priority").annotate(total=Count("id"))}
    rework = [
        {"name": row["assigned_phase__name"] or "Unassigned", "total": row["total"]}
        for row in ReworkRequest.objects.values("assigned_phase__name").annotate(total=Count("id")).order_by("-total")
    ]
    performance = [
        {"name": row["phase__name"] or "Phase", "total": row["total"]}
        for row in WorkflowEvent.objects.filter(event_type="PHASE_COMPLETED")
        .values("phase__name")
        .annotate(total=Count("id"))
        .order_by("-total")
    ]
    completed = list(machines.filter(qc_approved_at__isnull=False).only("created_at", "qc_approved_at"))
    if completed:
        average = sum((item.qc_approved_at - item.created_at).total_seconds() for item in completed) / len(completed)
    else:
        average = 0
    weeks = (
        machines.annotate(bucket=TruncWeek("created_at"))
        .values("bucket")
        .annotate(total=Count("id"))
        .order_by("bucket")
    )
    months = (
        machines.annotate(bucket=TruncMonth("qc_approved_at"))
        .filter(qc_approved_at__isnull=False)
        .values("bucket")
        .annotate(total=Count("id"))
        .order_by("bucket")
    )
    return {
        "cards": [
            {"key": key, "label": label, "value": value, "tone": tone, "icon": icon, "limit": limit, "note": note}
            for key, label, value, tone, icon, limit, note in cards
        ],
        "charts": {
            "phases": {
                "labels": [row.name for row in phase_rows],
                "open": [row.open_count for row in phase_rows],
                "done": [row.done_count for row in phase_rows],
            },
            "daily": daily,
            "priority": {
                "labels": [label for _key, label in Priority.CHOICES],
                "values": [priority.get(key, 0) for key, _label in Priority.CHOICES],
            },
            "rework": {"labels": [row["name"] for row in rework], "values": [row["total"] for row in rework]},
            "performance": {
                "labels": [row["name"] for row in performance],
                "values": [row["total"] for row in performance],
            },
            "weekly": {
                "labels": [row["bucket"].strftime("%d %b") if row["bucket"] else "" for row in weeks],
                "values": [row["total"] for row in weeks],
            },
            "monthly": {
                "labels": [row["bucket"].strftime("%b %Y") if row["bucket"] else "" for row in months],
                "values": [row["total"] for row in months],
            },
            "average_hours": round(average / 3600, 1) if average else 0,
            "average_label": format_seconds(average) if average else "—",
        },
    }


def phases_until(code):
    if code not in STAGE_ORDER:
        return None
    index = STAGE_ORDER.index(code)
    return set(STAGE_ORDER[: index + 1])


def card_catalog():
    return CARD_META


def machines_for_card(key):
    today = timezone.localdate()
    machines = Machine.objects.select_related("planning", "station")
    if key == "all":
        return machines.order_by("machine_id")
    if key == "today":
        return machines.filter(created_at__date=today).order_by("machine_id")
    if key == "planning":
        return machines.filter(status__in=[MachineStatus.DRAFT, MachineStatus.WITH_PLANNER]).order_by("machine_id")
    if key == "production":
        return machines.filter(status=MachineStatus.WITH_PRODUCTION).order_by("machine_id")
    if key == "line":
        return machines.filter(status=MachineStatus.IN_PRODUCTION).order_by("machine_id")
    if key == "assembly":
        return machines.filter(
            status=MachineStatus.IN_PRODUCTION,
            phase_states__phase__code=PhaseCode.ASSEMBLY,
            phase_states__status=PhaseStatus.IN_PROGRESS,
        ).distinct().order_by("machine_id")
    if key == "electrical":
        return machines.filter(
            status=MachineStatus.IN_PRODUCTION,
            phase_states__phase__code=PhaseCode.ELECTRICAL,
            phase_states__status=PhaseStatus.IN_PROGRESS,
        ).distinct().order_by("machine_id")
    if key == "testing":
        return machines.filter(status=MachineStatus.IN_TESTING).order_by("machine_id")
    if key == "eol":
        return machines.filter(status=MachineStatus.IN_EOL).order_by("machine_id")
    if key == "qc":
        return machines.filter(status=MachineStatus.IN_QC).order_by("machine_id")
    if key == "completed":
        return machines.filter(status=MachineStatus.COMPLETED).order_by("machine_id")
    if key == "rework-open":
        return machines.filter(reworks__status=ReworkRequest.Status.OPEN).distinct().order_by("machine_id")
    if key == "rework":
        return machines.filter(is_under_rework=True).exclude(status=MachineStatus.COMPLETED).order_by("machine_id")
    return None


def limit_for_card(card, machine):
    limit = card.get("limit")
    if limit == "REWORK":
        rework = machine.reworks.filter(status=ReworkRequest.Status.OPEN).select_related("assigned_phase").order_by("-pk").first()
        code = rework.assigned_phase.code if rework and rework.assigned_phase_id else None
        return phases_until(code)
    return phases_until(limit) if limit else None


def department_stats(phase_code):
    base = MachinePhaseState.objects.filter(phase__code=phase_code)
    from django.db.models import Exists, OuterRef

    drafts = JobCardSubmission.objects.filter(
        machine_id=OuterRef("machine_id"),
        phase_code=phase_code,
        cycle=OuterRef("cycle"),
        status=JobCardSubmission.Status.DRAFT,
    )
    annotated = base.annotate(has_draft=Exists(drafts))
    pending = annotated.filter(status=PhaseStatus.IN_PROGRESS, has_draft=False, rework_open=False).count()
    drafts_count = annotated.filter(status=PhaseStatus.IN_PROGRESS, has_draft=True, rework_open=False).count()
    rework = annotated.filter(status=PhaseStatus.IN_PROGRESS, rework_open=True).count()
    submitted = annotated.filter(status=PhaseStatus.COMPLETED).count()
    return {
        "awaiting": pending,
        "drafts": drafts_count,
        "rework": rework,
        "submitted": submitted,
        "assigned": pending + drafts_count + rework + submitted,
    }
