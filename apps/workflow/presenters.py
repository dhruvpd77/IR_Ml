from django.urls import reverse
from django.utils import timezone

from core.constants import EventType, MachineStatus, PhaseCode, PhaseStatus
from core.formatters import format_duration
from workflow.models import ProductionPhase, WorkflowEvent

PHASE_SHEET = (
    ("ASSEMBLY", "Assembly", "#1D4ED8"),
    ("ELECTRICAL", "Electrical", "#B45309"),
    ("TESTING", "Testing", "#047857"),
    ("EOL", "End of line", "#6D28D9"),
    ("QC", "Quality control", "#E10600"),
)
GRID_SECTIONS = {
    "assembly parts",
    "assembly sign off",
    "testing sign off",
    "end of line",
    "general check",
}


def pipeline_label(machine):
    if machine.status in {MachineStatus.IN_PRODUCTION, MachineStatus.UNDER_REWORK} or machine.current_phase == PhaseCode.BUILD:
        states = {state.phase.code: state for state in machine.phase_states.all()}
        assembly = states.get(PhaseCode.ASSEMBLY)
        electrical = states.get(PhaseCode.ELECTRICAL)
        if assembly or electrical:
            return f"Assembly {_word(assembly)} · Electrical {_word(electrical)}"
    if machine.status == MachineStatus.UNDER_REWORK:
        return f"Rework · {machine.current_phase.replace('_', ' ').title()}"
    return machine.status_label


def _word(state):
    if state is None:
        return "Pending"
    return {
        PhaseStatus.COMPLETED: "Done",
        PhaseStatus.IN_PROGRESS: "In progress",
        PhaseStatus.PENDING: "Pending",
    }.get(state.status, state.status.title())


def tracking_steps(machine):
    phases = list(ProductionPhase.objects.filter(is_active=True).order_by("sequence", "name"))
    states = {state.phase_id: state for state in machine.phase_states.select_related("phase", "completed_by", "started_by")}
    groups = []
    for phase in phases:
        state = states.get(phase.id)
        entry = {
            "code": phase.code,
            "name": phase.name,
            "status": state.status if state else PhaseStatus.PENDING,
            "status_label": state.get_status_display() if state else "Pending",
            "started_at": state.started_at if state else None,
            "completed_at": state.completed_at if state else None,
            "actor": (state.completed_by or state.started_by) if state else None,
            "duration": format_duration(state.started_at, state.completed_at) if state and state.started_at else "—",
            "cycle": state.cycle if state else 1,
            "rework_open": bool(state and state.rework_open),
        }
        if groups and phase.parallel_group and groups[-1]["parallel"] and groups[-1]["sequence"] == phase.sequence:
            groups[-1]["phases"].append(entry)
        else:
            groups.append(
                {
                    "sequence": phase.sequence,
                    "parallel": bool(phase.parallel_group),
                    "phases": [entry],
                }
            )
    return groups


def _field(label, value, wide=False):
    text = str(value).strip() if value not in (None, "") else ""
    return {"label": label, "value": text or "—", "wide": wide}


def _person(user):
    if not user:
        return ""
    return user.display_name


def filled_record(machine, submissions):
    planning = machine.planning
    inspection = planning.customer_inspection or "—"
    if planning.customer_inspection == "Yes" and planning.customer_inspection_date:
        inspection = f"Yes · {planning.customer_inspection_date.strftime('%d %b %Y')}"
    states = {state.phase.code: state for state in machine.phase_states.all()}
    sections = [
        {
            "role": "Planning data entry",
            "title": "Machine registration",
            "person": _person(planning.submitted_by or machine.created_by),
            "when": planning.submitted_at or machine.created_at,
            "groups": [
                {
                    "title": "Identity",
                    "fields": [
                        _field("Company", planning.company),
                        _field("Type", planning.machine_type),
                        _field("Model description", planning.model_description, wide=True),
                        _field("CCN", planning.ccn),
                        _field("Work order", planning.work_order),
                    ],
                },
                {
                    "title": "Requirements",
                    "fields": [
                        _field("Calibration", planning.calibration),
                        _field("Test report required at bar", planning.test_report_bar),
                        _field("Export packing required", planning.export_packing_required),
                        _field("Customer inspection", inspection),
                        _field("Priority", machine.priority_label),
                    ],
                },
            ],
        }
    ]
    planner_state = states.get(PhaseCode.PLANNER)
    if machine.planner_serial or (planner_state and planner_state.status == PhaseStatus.COMPLETED):
        sections.append(
            {
                "role": "Production leader",
                "title": "Serial number",
                "person": _person(planner_state.completed_by) if planner_state else "",
                "when": planner_state.completed_at if planner_state else None,
                "groups": [{"title": "", "fields": [_field("Serial number", machine.planner_serial)]}],
            }
        )
    production_state = states.get(PhaseCode.PRODUCTION)
    if (
        machine.station_id
        or machine.production_serial
        or machine.production_remarks
        or (production_state and production_state.status == PhaseStatus.COMPLETED)
    ):
        station = machine.station
        sections.append(
            {
                "role": "Production leader",
                "title": "Station release",
                "person": _person(production_state.completed_by) if production_state else "",
                "when": production_state.completed_at if production_state else None,
                "groups": [
                    {
                        "title": "",
                        "fields": [
                            _field(
                                "Station",
                                f"{station.line_label} · {station.name}" if station and station.line else (station.name if station else ""),
                            ),
                            _field("Production serial", machine.production_serial),
                            _field("Remarks", machine.production_remarks, wide=True),
                        ],
                    }
                ],
            }
        )
    phase_names = dict(PhaseCode.CHOICES)
    phase_order = {code: index for index, (code, _label) in enumerate(PhaseCode.CHOICES)}
    cards = [card for card in submissions if card.status == "SUBMITTED"]
    cards.sort(key=lambda card: (phase_order.get(card.phase_code, 99), card.cycle, card.revision))
    for card in cards:
        responses = sorted(card.responses.all(), key=lambda item: (item.field.sort_order, item.field.pk))
        groups = []
        for response in responses:
            title = response.field.section or "Checks"
            if not groups or groups[-1]["title"] != title:
                groups.append({"title": title, "fields": []})
            groups[-1]["fields"].append(_field(response.field.label, response.display_value(), wide=True))
        if card.remarks:
            groups.append({"title": "Remarks", "fields": [_field("Remarks", card.remarks, wide=True)]})
        if card.corrective_action:
            groups.append({"title": "Corrective action", "fields": [_field("Corrective action", card.corrective_action, wide=True)]})
        sections.append(
            {
                "role": phase_names.get(card.phase_code, card.phase_code),
                "title": f"Job card · revision {card.revision} · cycle {card.cycle}",
                "person": _person(card.operator),
                "when": card.submitted_at,
                "groups": groups or [{"title": "", "fields": [_field("Answers", "No answers recorded")]}],
            }
        )
    return sections


def station_label(machine):
    station = machine.station
    if not station:
        return "—"
    if station.line:
        return f"{station.line_label} · {station.name}"
    return station.name


def _gujarati(text):
    return any("\u0a80" <= char <= "\u0aff" for char in text or "")


def _answer_tone(value):
    if value in {"Yes", "હા", "OK", "Pass"}:
        return "yes"
    if value in {"No", "ના", "NOT OK", "Fail"}:
        return "no"
    return ""


def shown_answer(response):
    field = response.field
    if field.field_type == "yes_no":
        if response.value_bool is True:
            return "હા" if _gujarati(field.label) else "Yes"
        if response.value_bool is False:
            return "ના" if _gujarati(field.label) else "No"
    return response.display_value()


def card_items(template, submission=None):
    """Every field on the active card, with a dash where nothing was saved."""
    answered = {}
    if submission is not None:
        for response in submission.responses.select_related("field").prefetch_related("attachments"):
            answered[response.field.field_key] = response
    items = []
    for field in template.active_fields():
        response = answered.get(field.field_key)
        value = shown_answer(response) if response is not None else "—"
        if not value:
            value = "—"
        media_urls = []
        if response is not None and field.field_type == "video":
            for attachment in response.attachments.order_by("pk"):
                media_urls.append(reverse("jobcards:attachment", args=[attachment.pk]))
            if len(media_urls) == 1:
                value = "Video attached"
            elif media_urls:
                value = f"{len(media_urls)} videos attached"
        items.append(
            {
                "section": field.section or "Details",
                "key": field.field_key,
                "label": field.label,
                "kind": field.field_type,
                "value": value,
                "tone": _answer_tone(value),
                "gujarati": _gujarati(field.label),
                "media_url": media_urls[0] if media_urls else "",
                "media_urls": media_urls,
            }
        )
    if submission is not None and submission.remarks:
        items.append({"section": "Submission", "label": "Remarks", "kind": "long_text", "value": submission.remarks, "tone": "", "gujarati": False})
    if submission is not None and submission.corrective_action:
        items.append(
            {
                "section": "Submission",
                "label": "Corrective action",
                "kind": "long_text",
                "value": submission.corrective_action,
                "tone": "",
                "gujarati": False,
            }
        )
    return items


def _pair_rows(items):
    rows = []
    pending = None
    for item in items:
        wide = item["kind"] in {"long_text", "remarks"}
        if wide:
            if pending is not None:
                rows.append({"cells": [pending], "span": True})
                pending = None
            rows.append({"cells": [item], "span": True, "long": True})
            continue
        if pending is None:
            pending = item
            continue
        rows.append({"cells": [pending, item], "span": False})
        pending = None
    if pending is not None:
        rows.append({"cells": [pending], "span": True})
    return rows


def electrical_rows(items):
    rows = []
    chunk = []
    for item in items:
        key = item.get("key") or ""
        if not key.startswith("elec_") or key.rsplit("_", 1)[-1] not in {"ok", "value", "remark"}:
            return None
        chunk.append(item)
        if len(chunk) == 3:
            rows.append({"result": chunk[0], "value": chunk[1], "remark": chunk[2]})
            chunk = []
    if chunk or not rows:
        return None
    return rows


def _section_groups(items):
    groups = []
    for item in items:
        name = item["section"]
        if not groups or groups[-1]["name"] != name:
            groups.append(
                {
                    "name": name,
                    "layout": "grid" if name.strip().lower() in GRID_SECTIONS else "lines",
                    "items": [],
                }
            )
        groups[-1]["items"].append(item)
    for group in groups:
        bundled = electrical_rows(group["items"])
        if bundled:
            group["layout"] = "electrical"
            group["rows"] = bundled
        elif group["layout"] == "grid":
            group["rows"] = _pair_rows(group["items"])
    return groups


def _stamp(submission):
    if submission is None:
        return "Not submitted"
    when = timezone.localtime(submission.submitted_at).strftime("%d %b %Y %H:%M") if submission.submitted_at else "Saved"
    who = submission.operator.display_name if submission.operator_id else "—"
    return f"{who} · {when} · cycle {submission.cycle}"


def _sheet_phase(code, title, color, submission, earlier):
    from jobcards.services import JobCardError, active_template

    sections = []
    try:
        template = active_template(code)
    except JobCardError:
        template = None
    if template is not None:
        sections = _section_groups(card_items(template, submission))
    old_cards = []
    for old in earlier:
        old_cards.append(
            {
                "stamp": _stamp(old),
                "sections": _section_groups(card_items(old.template, old)),
            }
        )
    return {
        "code": code,
        "title": title,
        "color": color,
        "stamp": _stamp(submission),
        "sections": sections,
        "earlier": old_cards,
    }


def job_card_view(machine, submissions, steps, reworks=None, until=None):
    planning = machine.planning
    planning_date = planning.submitted_at or machine.created_at
    date_text = timezone.localtime(planning_date).strftime("%d-%b-%Y") if planning_date else "—"
    inspection = planning.customer_inspection or "—"
    if planning.customer_inspection_date:
        inspection = f"{inspection} · {planning.customer_inspection_date.strftime('%d %b %Y')}"
    entered = planning.submitted_by.display_name if planning.submitted_by_id else "—"
    chips = []
    for group in steps or []:
        for phase in group.get("phases", []):
            status = phase.get("status_label") or "Pending"
            if status == "Completed":
                tone = "done"
            elif status == "In Progress":
                tone = "open"
            else:
                tone = "wait"
            if until is not None and phase.get("code") not in until:
                continue
            chips.append({"name": phase["name"], "status": status, "tone": tone, "code": phase.get("code")})
    grouped = {}
    for submission in submissions:
        if submission.status == "DRAFT":
            continue
        grouped.setdefault(submission.phase_code, []).append(submission)
    phases = []
    for code, title, color in PHASE_SHEET:
        if until is not None and code not in until:
            continue
        records = sorted(grouped.get(code, []), key=lambda item: (item.cycle, item.revision, item.pk))
        current = records[-1] if records else None
        phases.append(_sheet_phase(code, title, color, current, records[:-1]))
    rework_rows = []
    if until is None:
        for item in reworks or []:
            rework_rows.append(
                {
                    "label": f"{item.rework_code} · back to {item.assigned_phase.name} · {item.get_status_display()}",
                    "value": item.reason or "—",
                }
            )
    production = None
    if until is None or PhaseCode.PRODUCTION in until:
        production = _pair_rows(
            [
                {"label": "Production serial", "kind": "short_text", "value": machine.production_serial or "—", "tone": "", "gujarati": False},
                {"label": "Station", "kind": "short_text", "value": station_label(machine), "tone": "", "gujarati": False},
                {"label": "Production remarks", "kind": "long_text", "value": machine.production_remarks or "—", "tone": "", "gujarati": False},
                {"label": "Status", "kind": "short_text", "value": machine.status_label, "tone": "", "gujarati": False},
            ]
        )
    return {
        "machine_id": machine.machine_id,
        "entered_by": entered,
        "identity": [
            {"label": "Planning date", "value": date_text},
            {"label": "Model", "value": planning.model_description or "—"},
            {"label": "Machine serial number", "value": machine.planner_serial or "—"},
            {"label": "Work order number", "value": planning.work_order or "—"},
            {"label": "CCN", "value": planning.ccn or "—"},
            {"label": "Company", "value": planning.company or "—"},
            {"label": "Type", "value": planning.machine_type or "—"},
            {"label": "Priority", "value": machine.priority_label or "—"},
            {"label": "Calibration", "value": planning.calibration or "—"},
            {"label": "Test report bar", "value": planning.test_report_bar or "—"},
            {"label": "Export packing", "value": planning.export_packing_required or "—"},
            {"label": "Customer inspection", "value": inspection},
        ],
        "chips": chips,
        "production": production,
        "phases": phases,
        "reworks": rework_rows,
    }


def recent_events(machine, limit=80):
    return list(machine.events.select_related("actor", "phase").order_by("created_at", "pk")[:limit])


def event_label(event):
    labels = dict(EventType.CHOICES)
    phase = f" · {event.phase.name}" if event.phase_id else ""
    return f"{labels.get(event.event_type, event.event_type)}{phase}"
