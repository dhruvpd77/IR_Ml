from django.db.utils import OperationalError, ProgrammingError

from accounts.models import Department, SystemSetting, User
from core.constants import DEPARTMENTS, PHASE_DEFINITIONS, Roles, ShopLine, StationKind
from jobcards.defaults import DEFAULT_TEMPLATES
from jobcards.models import JobCardField, JobCardTemplate
from machines.models import ProductionStation
from workflow.models import ProductionPhase

LEGACY_STATIONS = ["BAY-01", "BAY-02", "ELEC-01", "TEST-01", "EOL-01"]

def _floor(code, name, line, kind, sort_order, description):
    return {
        "code": code,
        "name": name,
        "line": line,
        "kind": kind,
        "sort_order": sort_order,
        "description": description,
    }


def _line_stations(prefix, line):
    return [
        _floor(f"{prefix}-S4", "Station 4", line, StationKind.FINAL, 10, "Assembly"),
        _floor(f"{prefix}-S3", "Station 3", line, StationKind.ASSEMBLY, 20, "Assembly"),
        _floor(f"{prefix}-S2", "Station 2", line, StationKind.ASSEMBLY, 30, "Assembly"),
        _floor(f"{prefix}-SA1", "Station 1 – SA-1", line, StationKind.SUB, 40, "Sub assembly"),
        _floor(f"{prefix}-SA2", "Station 1 – SA-2", line, StationKind.SUB, 50, "Sub assembly"),
    ]


FLOOR_STATIONS = [
    *_line_stations("LM1", ShopLine.LM1),
    *_line_stations("LM2", ShopLine.LM2),
    _floor("SM-S3", "Station 3", ShopLine.SMALL, StationKind.ASSEMBLY, 10, "Assembly"),
    _floor("SM-S2", "Station 2", ShopLine.SMALL, StationKind.ASSEMBLY, 20, "Assembly"),
    _floor("SM-S1", "Station 1", ShopLine.SMALL, StationKind.ASSEMBLY, 30, "Assembly"),
    _floor("SM-B2", "Station Build 2", ShopLine.SMALL, StationKind.ASSEMBLY, 40, "Assembly"),
    _floor("SM-B1", "Station Build 1", ShopLine.SMALL, StationKind.ASSEMBLY, 50, "Assembly"),
]

SETTINGS = [
    ("company_name", "Ingersoll Rand", "Company name"),
    ("machine_id_prefix", "IR-MCH-", "Machine ID prefix"),
    ("duplicate_fields", "work_order,ccn,model_description", "Duplicate check fields"),
    (
        "retention_note",
        "Submitted job cards are retained permanently. Corrections create a new revision and never overwrite history.",
        "Retention note",
    ),
]


def ensure_reference_data():
    try:
        _ensure()
    except (OperationalError, ProgrammingError):
        return


def _ensure():
    departments = {}
    for order, (code, name, description) in enumerate(DEPARTMENTS, start=1):
        department, _created = Department.objects.get_or_create(
            code=code,
            defaults={"name": name, "description": description, "sort_order": order},
        )
        departments[code] = department
    User.objects.filter(role=Roles.PLANNER).update(
        role=Roles.PRODUCTION_LEADER,
        department=departments["PRODUCTION"],
    )
    # Serial assignment and station allocation are one job, held by planner1.
    User.objects.filter(username__in=["leader1", "leader2", "planner2"]).update(is_active=False)
    Department.objects.filter(code="PLANNER").update(
        is_active=False,
        description="Serial assignment is done by the production leader.",
    )
    for code, name, description, sequence, group, department_code in PHASE_DEFINITIONS:
        phase, created = ProductionPhase.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "description": description,
                "sequence": sequence,
                "parallel_group": group,
                "department": departments.get(department_code),
                "is_active": True,
            },
        )
        if created:
            continue
        updates = []
        if phase.name != name:
            phase.name = name
            updates.append("name")
        if phase.description != description:
            phase.description = description
            updates.append("description")
        if phase.sequence != sequence:
            phase.sequence = sequence
            updates.append("sequence")
        if phase.parallel_group != group:
            phase.parallel_group = group
            updates.append("parallel_group")
        department = departments.get(department_code)
        if department and phase.department_id != department.id:
            phase.department = department
            updates.append("department")
        if not phase.is_active:
            phase.is_active = True
            updates.append("is_active")
        if updates:
            phase.save(update_fields=updates)
    serial = ProductionPhase.objects.filter(code="PLANNER").first()
    production = departments.get("PRODUCTION")
    if serial and production and (
        serial.name != "Serial assignment" or serial.department_id != production.id
    ):
        serial.name = "Serial assignment"
        serial.description = "Production leader assigns the machine serial."
        serial.department = production
        serial.save(update_fields=["name", "description", "department"])
    for spec in FLOOR_STATIONS:
        code = spec["code"]
        station, created = ProductionStation.objects.get_or_create(
            code=code,
            defaults={**spec, "is_active": True},
        )
        if created:
            continue
        changed = []
        for field in ("line", "kind", "sort_order"):
            if not getattr(station, field):
                setattr(station, field, spec[field])
                changed.append(field)
        if changed:
            station.save(update_fields=changed)
    ProductionStation.objects.filter(code__in=["SM-B1", "SM-B2"]).update(kind=StationKind.ASSEMBLY, description="Assembly")
    ProductionStation.objects.filter(code__in=["LM1-S4", "LM2-S4"]).update(description="Assembly")
    ProductionStation.objects.filter(code__in=LEGACY_STATIONS).update(is_active=False)
    for key, value, label in SETTINGS:
        SystemSetting.objects.get_or_create(key=key, defaults={"value": value, "label": label})
    for phase_code, spec in DEFAULT_TEMPLATES.items():
        template, _created = JobCardTemplate.objects.get_or_create(
            phase_code=phase_code,
            version=1,
            defaults={
                "name": spec["name"],
                "description": spec["description"],
                "is_active": True,
            },
        )
        if not template.fields.exists():
            _write_fields(template, spec["fields"])
    _upgrade_job_cards()
    _ensure_waiting_phase_states()
    _close_passed_phases()


def _ensure_waiting_phase_states():
    """Machines registered before Waiting Area existed need a WAITING phase row."""
    from core.constants import PhaseCode, PhaseStatus
    from machines.models import Machine
    from workflow.models import MachinePhaseState

    waiting = ProductionPhase.objects.filter(code=PhaseCode.WAITING, is_active=True).first()
    if waiting is None:
        return
    missing = Machine.objects.exclude(phase_states__phase=waiting).values_list("pk", flat=True)
    MachinePhaseState.objects.bulk_create(
        [
            MachinePhaseState(machine_id=machine_id, phase=waiting, status=PhaseStatus.PENDING, cycle=1)
            for machine_id in missing
        ],
        ignore_conflicts=True,
    )


def _field_options(field_type, extra):
    if field_type not in {"dropdown", "radio"} or not extra:
        return []
    separator = "|" if "|" in extra else ","
    return [item.strip() for item in extra.split(separator) if item.strip()]


def _write_fields(template, fields):
    JobCardField.objects.bulk_create(
        [
            JobCardField(
                template=template,
                field_key=key,
                section=section,
                label=label,
                field_type=field_type,
                required=required,
                unit=unit,
                options=_field_options(field_type, extra),
                sort_order=index,
            )
            for index, (key, section, label, field_type, required, unit, extra) in enumerate(fields, start=1)
        ]
    )


def _upgrade_job_cards():
    from jobcards.defaults import TEMPLATE_MARKERS

    for phase_code, spec in DEFAULT_TEMPLATES.items():
        marker = TEMPLATE_MARKERS[phase_code]
        active = JobCardTemplate.objects.filter(phase_code=phase_code, is_active=True).order_by("-version").first()
        if active and active.fields.filter(field_key=marker).exists():
            continue
        if active and active.submissions.exists():
            active.is_active = False
            active.save(update_fields=["is_active"])
            template = JobCardTemplate.objects.create(
                phase_code=phase_code,
                name=spec["name"],
                description=spec["description"],
                version=active.version + 1,
                is_active=True,
            )
        elif active:
            active.name = spec["name"]
            active.description = spec["description"]
            active.is_active = True
            active.save()
            active.fields.all().delete()
            template = active
        else:
            template = JobCardTemplate.objects.create(
                phase_code=phase_code,
                name=spec["name"],
                description=spec["description"],
                version=1,
                is_active=True,
            )
        _write_fields(template, spec["fields"])
    _ensure_media_fields()


def _ensure_media_fields():
    """Testing keeps the inspection video. Quality Control keeps compressed photos."""
    extras = (
        ("TESTING", "testing_video", "Inspection video", "Inspection video", "video"),
        ("QC", "qc_photo", "Inspection photos", "Inspection photos", "image"),
    )
    for phase_code, key, section, label, field_type in extras:
        template = JobCardTemplate.objects.filter(phase_code=phase_code, is_active=True).order_by("-version").first()
        if template is None or template.fields.filter(field_key=key).exists():
            continue
        last = template.fields.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0
        JobCardField.objects.create(
            template=template,
            field_key=key,
            section=section,
            label=label,
            field_type=field_type,
            required=False,
            sort_order=last + 1,
        )
    JobCardField.objects.filter(
        template__phase_code="QC",
        template__is_active=True,
        field_key="qc_video",
    ).update(is_active=False)


def _close_passed_phases():
    """A phase left open after the machine has moved on must not count as current work."""
    from core.constants import PhaseCode, PhaseStatus
    from workflow.models import MachinePhaseState

    sequences = {phase.code: phase.sequence for phase in ProductionPhase.objects.all()}
    build_sequence = sequences.get(PhaseCode.ASSEMBLY, 4)
    for state in MachinePhaseState.objects.filter(status=PhaseStatus.IN_PROGRESS).select_related("machine", "phase"):
        machine = state.machine
        if machine.status == "COMPLETED":
            behind = True
        elif machine.current_phase == PhaseCode.BUILD:
            behind = state.phase.sequence < build_sequence
        else:
            behind = state.phase.sequence < sequences.get(machine.current_phase, 0)
        if not behind:
            continue
        state.status = PhaseStatus.COMPLETED
        if state.completed_at is None:
            state.completed_at = machine.updated_at
        state.save(update_fields=["status", "completed_at"])
