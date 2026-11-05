from datetime import datetime

from django.db.models import Q
from django.utils import timezone

from core.formatters import format_seconds
from jobcards.models import JobCardSubmission
from machines.models import Machine
from rework.models import ReworkRequest
from workflow.models import WorkflowEvent


REPORTS = [
    ("production", "Machine production report"),
    ("department", "Department-wise production report"),
    ("daily", "Daily production report"),
    ("monthly", "Monthly production report"),
    ("completed", "Completed machine report"),
    ("pending", "Pending machine report"),
    ("rework", "Rework report"),
    ("rejection", "Rejection report"),
    ("jobcard", "Job card report"),
    ("station", "Station-wise machine report"),
    ("duration", "Production duration report"),
]


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _text(value):
    if value in (None, ""):
        return "—"
    return str(value)


def _machine_queryset(params):
    queryset = Machine.objects.select_related("planning", "station", "created_by", "qc_approved_by")
    if params.get("status"):
        queryset = queryset.filter(status=params["status"])
    if params.get("priority"):
        queryset = queryset.filter(priority=params["priority"])
    if params.get("station"):
        queryset = queryset.filter(station_id=params["station"])
    if params.get("q"):
        query = params["q"].strip()
        queryset = queryset.filter(
            Q(machine_id__icontains=query)
            | Q(planning__work_order__icontains=query)
            | Q(planning__model_description__icontains=query)
            | Q(planner_serial__icontains=query)
        )
    start = parse_date(params.get("date_from"))
    end = parse_date(params.get("date_to"))
    if start:
        queryset = queryset.filter(created_at__date__gte=start)
    if end:
        queryset = queryset.filter(created_at__date__lte=end)
    return queryset


def _machine_headers():
    return [
        "Machine ID",
        "Work Order",
        "CCN",
        "Model",
        "Type",
        "Serial",
        "Production Serial",
        "Station",
        "Phase",
        "Priority",
        "Status",
        "Created",
    ]


def _machine_row(machine):
    planning = getattr(machine, "planning", None)
    return [
        machine.machine_id,
        _text(planning.work_order if planning else ""),
        _text(planning.ccn if planning else ""),
        _text(planning.model_description if planning else ""),
        _text(planning.machine_type if planning else ""),
        _text(machine.planner_serial),
        _text(machine.production_serial),
        _text(machine.station.name if machine.station_id else ""),
        machine.current_phase,
        machine.priority_label,
        machine.status_label,
        timezone.localtime(machine.created_at).strftime("%d %b %Y %H:%M"),
    ]


def build_report(key, params):
    title = dict(REPORTS).get(key, "Machine production report")
    if key == "rework":
        return title, *_rework_rows(params, open_only=False)
    if key == "rejection":
        return title, *_rework_rows(params, open_only=False)
    if key == "jobcard":
        return title, *_job_cards(params)
    if key == "duration":
        return title, *_durations(params)
    if key == "daily":
        return title, *_completions(params, default="day")
    if key == "monthly":
        return title, *_completions(params, default="month")
    queryset = _machine_queryset(params)
    if key == "completed":
        queryset = queryset.filter(status="COMPLETED")
    elif key == "pending":
        queryset = queryset.exclude(status="COMPLETED")
    elif key == "station":
        queryset = queryset.exclude(station__isnull=True).order_by("station__code", "-created_at")
    elif key == "department" and params.get("phase"):
        queryset = queryset.filter(phase_states__phase__code=params["phase"]).distinct()
    else:
        queryset = queryset.order_by("-created_at")
    if key != "station":
        queryset = queryset.order_by("-created_at")
    rows = [_machine_row(machine) for machine in queryset[:2000]]
    return title, _machine_headers(), rows


def _rework_rows(params, open_only):
    queryset = ReworkRequest.objects.select_related("machine", "assigned_phase", "rejected_phase", "rejected_by")
    if open_only:
        queryset = queryset.filter(status=ReworkRequest.Status.OPEN)
    if params.get("phase"):
        queryset = queryset.filter(assigned_phase__code=params["phase"])
    start = parse_date(params.get("date_from"))
    end = parse_date(params.get("date_to"))
    if start:
        queryset = queryset.filter(rejected_at__date__gte=start)
    if end:
        queryset = queryset.filter(rejected_at__date__lte=end)
    headers = ["Rework", "Machine", "From", "Assigned to", "Reason", "Status", "Reinspection", "Rejected by", "Rejected at"]
    rows = []
    for item in queryset[:2000]:
        rows.append(
            [
                item.rework_code,
                item.machine.machine_id,
                item.rejected_phase.name,
                item.assigned_phase.name,
                item.reason,
                item.get_status_display(),
                item.reinspection_status,
                item.rejected_by.display_name if item.rejected_by_id else "—",
                timezone.localtime(item.rejected_at).strftime("%d %b %Y %H:%M"),
            ]
        )
    return headers, rows


def _job_cards(params):
    queryset = JobCardSubmission.objects.select_related("machine", "operator").exclude(status="DRAFT")
    if params.get("phase"):
        queryset = queryset.filter(phase_code=params["phase"])
    start = parse_date(params.get("date_from"))
    end = parse_date(params.get("date_to"))
    if start:
        queryset = queryset.filter(submitted_at__date__gte=start)
    if end:
        queryset = queryset.filter(submitted_at__date__lte=end)
    headers = ["Machine", "Phase", "Cycle", "Revision", "Status", "Operator", "Submitted"]
    rows = []
    for item in queryset[:2000]:
        rows.append(
            [
                item.machine.machine_id,
                item.phase_code,
                item.cycle,
                item.revision,
                item.get_status_display(),
                item.operator.display_name if item.operator_id else "—",
                timezone.localtime(item.submitted_at).strftime("%d %b %Y %H:%M") if item.submitted_at else "—",
            ]
        )
    return headers, rows


def _durations(params):
    queryset = WorkflowEvent.objects.filter(event_type="PHASE_COMPLETED").select_related("machine", "phase", "actor")
    if params.get("phase"):
        queryset = queryset.filter(phase__code=params["phase"])
    start = parse_date(params.get("date_from"))
    end = parse_date(params.get("date_to"))
    if start:
        queryset = queryset.filter(created_at__date__gte=start)
    if end:
        queryset = queryset.filter(created_at__date__lte=end)
    headers = ["Machine", "Phase", "Cycle", "Started", "Completed", "Duration", "Operator"]
    rows = []
    for event in queryset.order_by("-created_at")[:2000]:
        meta = event.metadata or {}
        rows.append(
            [
                event.machine.machine_id,
                event.phase.name if event.phase_id else "—",
                event.cycle,
                _text(meta.get("started_at")),
                _text(meta.get("completed_at")),
                format_seconds(meta.get("duration_seconds")),
                event.actor.display_name if event.actor_id else "—",
            ]
        )
    return headers, rows


def _completions(params, default):
    today = timezone.localdate()
    start = parse_date(params.get("date_from"))
    end = parse_date(params.get("date_to"))
    queryset = WorkflowEvent.objects.filter(event_type="PHASE_COMPLETED").select_related("machine", "phase", "actor")
    if default == "day" and not start and not end:
        start = end = today
    if default == "month" and not start and not end:
        start = today.replace(day=1)
        end = today
    if start:
        queryset = queryset.filter(created_at__date__gte=start)
    if end:
        queryset = queryset.filter(created_at__date__lte=end)
    if params.get("phase"):
        queryset = queryset.filter(phase__code=params["phase"])
    headers = ["Machine", "Phase", "Completed at", "Operator", "Duration"]
    rows = []
    for event in queryset.order_by("-created_at")[:2000]:
        rows.append(
            [
                event.machine.machine_id,
                event.phase.name if event.phase_id else "—",
                timezone.localtime(event.created_at).strftime("%d %b %Y %H:%M"),
                event.actor.display_name if event.actor_id else "—",
                format_seconds((event.metadata or {}).get("duration_seconds")),
            ]
        )
    return headers, rows
