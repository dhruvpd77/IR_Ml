from django import template

from core.constants import EventType, MachineStatus, PhaseStatus, Priority

register = template.Library()

BADGES = {
    MachineStatus.COMPLETED: "badge badge-green",
    MachineStatus.IN_PRODUCTION: "badge badge-blue",
    MachineStatus.IN_TESTING: "badge badge-blue",
    MachineStatus.IN_EOL: "badge badge-blue",
    MachineStatus.IN_QC: "badge badge-amber",
    MachineStatus.WITH_PLANNER: "badge badge-amber",
    MachineStatus.WITH_PRODUCTION: "badge badge-amber",
    MachineStatus.UNDER_REWORK: "badge badge-red",
    MachineStatus.DRAFT: "badge badge-slate",
    PhaseStatus.COMPLETED: "badge badge-green",
    PhaseStatus.IN_PROGRESS: "badge badge-blue",
    PhaseStatus.PENDING: "badge badge-slate",
    Priority.FIRST: "badge badge-red",
    Priority.SECOND: "badge badge-amber",
    Priority.STANDARD: "badge badge-slate",
    "CRITICAL": "badge badge-red",
    "HIGH": "badge badge-red",
    "MEDIUM": "badge badge-amber",
    "LOW": "badge badge-slate",
    "Pass": "badge badge-green",
    "Fail": "badge badge-red",
    "N/A": "badge badge-slate",
    "OPEN": "badge badge-red",
    "AWAITING_REINSPECTION": "badge badge-amber",
    "CLOSED": "badge badge-green",
    "SUBMITTED": "badge badge-green",
    "SUPERSEDED": "badge badge-slate",
    "DRAFT": "badge badge-amber",
}


@register.filter
def badge_class(value):
    return BADGES.get(value, "badge badge-slate")


@register.filter
def getitem(mapping, key):
    if isinstance(mapping, dict):
        value = mapping.get(key, "")
        return "" if value is None else value
    return ""


@register.filter
def event_title(event):
    label = dict(EventType.CHOICES).get(event.event_type, event.event_type)
    if getattr(event, "phase_id", None):
        return f"{label} · {event.phase.name}"
    return label
