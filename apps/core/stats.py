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
    PhaseCode.WAITING,
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
    PhaseCode.WAITING: "Waiting Area",
    PhaseCode.TESTING: "Testing",
    PhaseCode.EOL: "End of line",
    PhaseCode.QC: "Quality control",
}
CARD_META = {
    "all": {"label": "Total machines", "tone": "navy", "icon": "layers", "limit": None},
    "registered": {"label": "Registered", "tone": "blue", "icon": "clipboard-plus", "limit": None},
    "tentative": {"label": "Tentative planned machines", "tone": "navy", "icon": "calendar-range", "limit": None},
    "balance": {"label": "Yet to register", "tone": "amber", "icon": "circle-minus", "limit": None},
    "today": {"label": "Registered today", "tone": "blue", "icon": "calendar-plus", "limit": PhaseCode.PLANNING},
    "planning": {"label": "Planning and serial", "tone": "slate", "icon": "clipboard-list", "limit": PhaseCode.PRODUCTION},
    "production": {"label": "Planning and serial", "tone": "slate", "icon": "clipboard-list", "limit": PhaseCode.PRODUCTION},
    "line": {"label": "Under assembly", "tone": "amber", "icon": "wrench", "limit": PhaseCode.ELECTRICAL},
    "assembly": {"label": "In assembly", "tone": "amber", "icon": "wrench", "limit": PhaseCode.ASSEMBLY},
    "electrical": {"label": "In electrical", "tone": "amber", "icon": "zap", "limit": PhaseCode.ELECTRICAL},
    "waiting": {"label": "Waiting for test bay", "tone": "amber", "icon": "hourglass", "limit": PhaseCode.WAITING},
    "testing": {"label": "In testing", "tone": "blue", "icon": "gauge", "limit": PhaseCode.TESTING},
    "eol": {"label": "EOL under production", "tone": "blue", "icon": "package-check", "limit": PhaseCode.EOL},
    "qc": {"label": "EOL assigned to Quality", "tone": "red", "icon": "shield-check", "limit": PhaseCode.QC},
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


def scoped_machines(machine_type="", start=None, end=None, on_date=None, shift=""):
    machines = Machine.objects.all()
    if machine_type:
        machines = machines.filter(planning__machine_type=machine_type)
    if on_date is not None:
        machines = machines.filter(created_at__date=on_date)
    elif start is not None and end is not None:
        machines = machines.filter(created_at__gte=start, created_at__lt=end)
    if shift:
        machines = machines.filter(planning__shift=shift)
    return machines


def admin_stats(machine_type="", start=None, end=None, on_date=None, shift="", mode="", tentative=0, tentative_set=False):
    today = timezone.localdate()
    machines = scoped_machines(machine_type, start=start, end=end, on_date=on_date, shift=shift)
    machine_ids = machines.values("pk")
    reworks = ReworkRequest.objects.filter(machine__in=machine_ids)
    events = WorkflowEvent.objects.filter(machine__in=machine_ids)
    open_filter = Q(machine_states__status=PhaseStatus.IN_PROGRESS, machine_states__machine__in=machine_ids)
    done_filter = Q(machine_states__status=PhaseStatus.COMPLETED, machine_states__machine__in=machine_ids)
    phase_rows = ProductionPhase.objects.filter(is_active=True).annotate(
        open_count=Count("machine_states", filter=open_filter),
        done_count=Count("machine_states", filter=done_filter),
    )
    on_line = machines.filter(status=MachineStatus.IN_PRODUCTION)
    assembly_open = on_line.filter(
        phase_states__phase__code=PhaseCode.ASSEMBLY, phase_states__status=PhaseStatus.IN_PROGRESS
    ).distinct().count()
    electrical_open = on_line.filter(
        phase_states__phase__code=PhaseCode.ELECTRICAL, phase_states__status=PhaseStatus.IN_PROGRESS
    ).distinct().count()
    registered = machines.count()
    balance = tentative - registered
    if mode == "monthly":
        lead = [
            ("tentative", "Tentative planned machines", tentative, "navy", "calendar-range", None, "Entered by Super Admin" if tentative_set else "Not entered yet"),
            ("registered", "Registered", registered, "blue", "clipboard-plus", None, "Planning team"),
            ("balance", "Yet to register", balance, "red" if balance < 0 else "amber", "circle-minus", None, "Over the tentative plan" if balance < 0 else "Tentative minus registered"),
        ]
    elif mode == "daily":
        lead = [
            ("registered", "Registered", registered, "blue", "clipboard-plus", None, "Registered on this date"),
        ]
    else:
        lead = [
            ("all", "Total machines", registered, "navy", "layers", None, ""),
            ("today", "Registered today", machines.filter(created_at__date=today).count(), "blue", "calendar-plus", PhaseCode.PLANNING, "Already inside the total"),
        ]
    cards = lead + [
        (
            "planning",
            "Planning and serial",
            machines.filter(status__in=[MachineStatus.DRAFT, MachineStatus.WITH_PLANNER, MachineStatus.WITH_PRODUCTION]).count(),
            "slate",
            "clipboard-list",
            PhaseCode.PRODUCTION,
            "Serial number and station together",
        ),
        ("line", "Under assembly", on_line.count(), "amber", "wrench", PhaseCode.ELECTRICAL, f"Assembly open {assembly_open} · Electrical open {electrical_open}"),
        ("waiting", "Waiting for test bay", machines.filter(status=MachineStatus.IN_WAITING).count(), "amber", "hourglass", PhaseCode.WAITING, "Assembly done · awaiting Testing"),
        ("testing", "In testing", machines.filter(status=MachineStatus.IN_TESTING).count(), "blue", "gauge", PhaseCode.TESTING, ""),
        ("eol", "EOL under production", machines.filter(status=MachineStatus.IN_EOL).count(), "blue", "package-check", PhaseCode.EOL, ""),
        ("qc", "EOL assigned to Quality", machines.filter(status=MachineStatus.IN_QC).count(), "red", "shield-check", PhaseCode.QC, ""),
        ("completed", "Completed", machines.filter(status=MachineStatus.COMPLETED).count(), "green", "circle-check", None, ""),
        ("rework-open", "Open rework", reworks.filter(status=ReworkRequest.Status.OPEN).count(), "red", "rotate-ccw", "REWORK", "Already inside the total"),
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
        for row in reworks.values("assigned_phase__name").annotate(total=Count("id")).order_by("-total")
    ]
    performance = [
        {"name": row["phase__name"] or "Phase", "total": row["total"]}
        for row in events.filter(event_type="PHASE_COMPLETED")
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


def machines_for_card(key, machine_type="", start=None, end=None, on_date=None, shift=""):
    today = timezone.localdate()
    machines = scoped_machines(machine_type, start=start, end=end, on_date=on_date, shift=shift).select_related("planning", "station")
    if key in {"all", "registered"}:
        return machines.order_by("machine_id")
    if key == "today":
        return machines.filter(created_at__date=today).order_by("machine_id")
    if key in {"planning", "production"}:
        return machines.filter(
            status__in=[MachineStatus.DRAFT, MachineStatus.WITH_PLANNER, MachineStatus.WITH_PRODUCTION]
        ).order_by("machine_id")
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
    if key == "waiting":
        return machines.filter(status=MachineStatus.IN_WAITING).order_by("machine_id")
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


DEPARTMENT_CARDS = (
    ("assigned", "Reached this phase", "violet", "layers", "Every machine that has reached this phase."),
    ("awaiting", "Awaiting action", "amber", "clock", "Waiting for a job card. No draft has been saved."),
    ("drafts", "Draft job cards", "blue", "pencil", "A draft is saved and has not been submitted."),
    ("rework", "Rework", "red", "rotate-ccw", "Sent back to this phase and still open."),
    ("submitted", "Submitted", "green", "circle-check", "This phase is already complete."),
)


def _department_states(phase_code):
    from django.db.models import Exists, OuterRef

    drafts = JobCardSubmission.objects.filter(
        machine_id=OuterRef("machine_id"),
        phase_code=phase_code,
        cycle=OuterRef("cycle"),
        status=JobCardSubmission.Status.DRAFT,
    )
    return MachinePhaseState.objects.filter(phase__code=phase_code).annotate(has_draft=Exists(drafts))


def department_bucket(phase_code, key, machine_type=""):
    annotated = _department_states(phase_code)
    if machine_type:
        annotated = annotated.filter(machine__planning__machine_type=machine_type)
    if key == "awaiting":
        return annotated.filter(status=PhaseStatus.IN_PROGRESS, has_draft=False, rework_open=False)
    if key == "drafts":
        return annotated.filter(status=PhaseStatus.IN_PROGRESS, has_draft=True, rework_open=False)
    if key == "rework":
        return annotated.filter(status=PhaseStatus.IN_PROGRESS, rework_open=True)
    if key == "submitted":
        return annotated.filter(status=PhaseStatus.COMPLETED)
    if key == "assigned":
        return annotated.filter(status__in=[PhaseStatus.IN_PROGRESS, PhaseStatus.COMPLETED])
    return None


def department_stats(phase_code, machine_type=""):
    return {key: department_bucket(phase_code, key, machine_type).count() for key, *_rest in DEPARTMENT_CARDS}


def department_cards(phase_code, machine_type=""):
    stats = department_stats(phase_code, machine_type)
    return [
        {"key": key, "label": label, "tone": tone, "icon": icon, "note": note, "value": stats[key]}
        for key, label, tone, icon, note in DEPARTMENT_CARDS
    ]


def machines_for_department_card(phase_code, key, machine_type=""):
    states = department_bucket(phase_code, key, machine_type)
    if states is None:
        return None
    return (
        Machine.objects.filter(pk__in=states.values("machine_id"))
        .select_related("planning", "station")
        .order_by("machine_id")
    )


def _bar_rows(rows, label_key, value_key="total", limit=12):
    items = [
        {"label": (row.get(label_key) or "—"), "value": row[value_key]}
        for row in rows
        if row.get(value_key)
    ][:limit]
    peak = max((item["value"] for item in items), default=0) or 1
    for item in items:
        item["pct"] = round((item["value"] / peak) * 100)
    return items


def details_analytics(machine_type="", company="", start=None, end=None, on_date=None, shift=""):
    """Deep shop analytics for the Details Analytics page."""
    today = timezone.localdate()
    machines = scoped_machines(machine_type, start=start, end=end, on_date=on_date, shift=shift)
    if company:
        machines = machines.filter(planning__company=company)
    machine_ids = machines.values("pk")

    total = machines.count()
    completed = machines.filter(status=MachineStatus.COMPLETED).count()
    open_rework = ReworkRequest.objects.filter(machine__in=machine_ids, status=ReworkRequest.Status.OPEN).count()
    under_rework = machines.filter(is_under_rework=True).exclude(status=MachineStatus.COMPLETED).count()
    in_waiting = machines.filter(status=MachineStatus.IN_WAITING).count()
    in_testing = machines.filter(status=MachineStatus.IN_TESTING).count()
    in_qc = machines.filter(status=MachineStatus.IN_QC).count()
    on_floor = machines.filter(
        status__in=[
            MachineStatus.IN_PRODUCTION,
            MachineStatus.IN_WAITING,
            MachineStatus.IN_TESTING,
            MachineStatus.IN_EOL,
            MachineStatus.IN_QC,
            MachineStatus.UNDER_REWORK,
        ]
    ).count()

    finished = list(
        machines.filter(qc_approved_at__isnull=False).only("pk", "created_at", "qc_approved_at")
    )
    if finished:
        average = sum((item.qc_approved_at - item.created_at).total_seconds() for item in finished) / len(finished)
    else:
        average = 0

    open_filter = Q(machine_states__status=PhaseStatus.IN_PROGRESS, machine_states__machine__in=machine_ids)
    done_filter = Q(machine_states__status=PhaseStatus.COMPLETED, machine_states__machine__in=machine_ids)
    phase_rows = list(
        ProductionPhase.objects.filter(is_active=True)
        .annotate(
            open_count=Count("machine_states", filter=open_filter),
            done_count=Count("machine_states", filter=done_filter),
        )
        .order_by("sequence", "pk")
    )
    phase_peak = max((max(row.open_count, row.done_count) for row in phase_rows), default=0) or 1
    pipeline = [
        {
            "code": row.code,
            "name": row.name,
            "open": row.open_count,
            "done": row.done_count,
            "open_pct": round((row.open_count / phase_peak) * 100),
            "done_pct": round((row.done_count / phase_peak) * 100),
        }
        for row in phase_rows
    ]

    status_map = {row["status"]: row["total"] for row in machines.values("status").annotate(total=Count("id"))}
    status_rows = [
        {"label": label, "value": status_map.get(code, 0)}
        for code, label in MachineStatus.CHOICES
        if status_map.get(code, 0)
    ]
    status_peak = max((row["value"] for row in status_rows), default=0) or 1
    for row in status_rows:
        row["pct"] = round((row["value"] / status_peak) * 100)

    brand_rows = _bar_rows(
        machines.values("planning__company").annotate(total=Count("id")).order_by("-total"),
        "planning__company",
    )
    type_rows = _bar_rows(
        machines.values("planning__machine_type").annotate(total=Count("id")).order_by("-total"),
        "planning__machine_type",
    )
    shift_rows = _bar_rows(
        machines.values("planning__shift").annotate(total=Count("id")).order_by("-total"),
        "planning__shift",
    )
    priority_map = {row["priority"]: row["total"] for row in machines.values("priority").annotate(total=Count("id"))}
    priority_rows = [
        {"label": label, "value": priority_map.get(code, 0), "pct": 0}
        for code, label in Priority.CHOICES
    ]
    priority_peak = max((row["value"] for row in priority_rows), default=0) or 1
    for row in priority_rows:
        row["pct"] = round((row["value"] / priority_peak) * 100)

    station_raw = list(
        machines.exclude(station__isnull=True)
        .values("station__name", "station__line")
        .annotate(total=Count("id"))
        .order_by("-total")[:10]
    )
    station_peak = max((row["total"] for row in station_raw), default=0) or 1
    station_rows = []
    for row in station_raw:
        name = row.get("station__name") or "—"
        line = row.get("station__line") or ""
        label = f"{name} · {line}" if line else name
        station_rows.append(
            {
                "label": label,
                "value": row["total"],
                "pct": round((row["total"] / station_peak) * 100),
            }
        )

    reworks = ReworkRequest.objects.filter(machine__in=machine_ids)
    rework_by_phase = _bar_rows(
        reworks.filter(status=ReworkRequest.Status.OPEN)
        .values("assigned_phase__name")
        .annotate(total=Count("id"))
        .order_by("-total"),
        "assigned_phase__name",
    )
    rework_open_list = list(
        reworks.filter(status=ReworkRequest.Status.OPEN)
        .select_related("machine", "machine__planning", "assigned_phase")
        .order_by("-rejected_at")[:8]
    )
    recent_completed = list(
        machines.filter(status=MachineStatus.COMPLETED)
        .select_related("planning")
        .order_by("-qc_approved_at", "-updated_at")[:8]
    )

    submissions = JobCardSubmission.objects.filter(
        machine__in=machine_ids,
        status=JobCardSubmission.Status.SUBMITTED,
    )
    jobcard_rows = _bar_rows(
        submissions.values("phase_code").annotate(total=Count("id")).order_by("-total"),
        "phase_code",
    )
    for row in jobcard_rows:
        row["label"] = STAGE_LABELS.get(row["label"], row["label"])

    days = _span_labels(14)
    trend = [
        {
            "label": day.strftime("%d %b"),
            "registered": machines.filter(created_at__date=day).count(),
            "completed": machines.filter(qc_approved_at__date=day).count(),
        }
        for day in days
    ]
    trend_peak = max((max(item["registered"], item["completed"]) for item in trend), default=0) or 1
    for item in trend:
        item["reg_pct"] = round((item["registered"] / trend_peak) * 100)
        item["done_pct"] = round((item["completed"] / trend_peak) * 100)

    top_models = _bar_rows(
        machines.values("planning__model_description")
        .annotate(total=Count("id"))
        .order_by("-total"),
        "planning__model_description",
        limit=8,
    )

    return {
        "kpis": [
            {"label": "Total machines", "value": total, "tone": "navy", "note": "In selected scope"},
            {"label": "On the floor", "value": on_floor, "tone": "amber", "note": "Assembly → QC"},
            {"label": "Completed", "value": completed, "tone": "green", "note": f"{round((completed / total) * 100) if total else 0}% of scope"},
            {"label": "Waiting for bay", "value": in_waiting, "tone": "amber", "note": "Ready for Testing"},
            {"label": "In testing", "value": in_testing, "tone": "blue", "note": "Active test stations"},
            {"label": "In QC", "value": in_qc, "tone": "red", "note": "Quality review"},
            {"label": "Open rework", "value": open_rework, "tone": "red", "note": f"{under_rework} machines flagged"},
            {
                "label": "Avg cycle time",
                "value": format_seconds(average) if average else "—",
                "tone": "navy",
                "note": "Register → QC approve",
            },
        ],
        "pipeline": pipeline,
        "status_rows": status_rows,
        "brand_rows": brand_rows,
        "type_rows": type_rows,
        "shift_rows": shift_rows,
        "priority_rows": priority_rows,
        "station_rows": station_rows,
        "rework_by_phase": rework_by_phase,
        "rework_open_list": rework_open_list,
        "recent_completed": recent_completed,
        "jobcard_rows": jobcard_rows,
        "trend": trend,
        "top_models": top_models,
        "totals": {
            "machines": total,
            "completed": completed,
            "open_rework": open_rework,
            "job_cards": submissions.count(),
            "today_registered": machines.filter(created_at__date=today).count() if not on_date else total,
        },
    }
