from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import get_setting
from audit.utils import log_audit
from core.constants import MachineStatus, Priority
from machines.models import Machine, MachinePlanningData, MachineSequence


def next_machine_id():
    prefix = get_setting("machine_id_prefix", "IR-MCH-")
    with transaction.atomic():
        MachineSequence.objects.get_or_create(pk=1, defaults={"last_number": 0})
        sequence = MachineSequence.objects.select_for_update().get(pk=1) if _supports_lock() else MachineSequence.objects.get(pk=1)
        sequence.last_number += 1
        sequence.save(update_fields=["last_number"])
        number = sequence.last_number
    return f"{prefix}{number:06d}"


def _supports_lock():
    from django.db import connection

    features = connection.features
    return bool(
        getattr(features, "has_select_for_update", False)
        or getattr(features, "supports_select_for_update", False)
    )


def normalize_priority(value):
    key = str(value or "").strip().lower()
    return Priority.NORMALIZE.get(key)


def clean_text(value):
    return str(value or "").strip()


def register_machine(data, user, submit=False, raw=None):
    from workflow.engine import initialize_machine, submit_planning

    priority = normalize_priority(data.get("priority")) or Priority.STANDARD
    with transaction.atomic():
        machine = Machine.objects.create(
            machine_id=next_machine_id(),
            priority=priority,
            status=MachineStatus.DRAFT,
            current_phase="PLANNING",
            created_by=user,
        )
        MachinePlanningData.objects.create(
            machine=machine,
            company=clean_text(data.get("company")) or "Ingersoll Rand",
            work_order=clean_text(data.get("work_order")),
            ccn=clean_text(data.get("ccn")),
            model_description=clean_text(data.get("model_description")),
            machine_type=clean_text(data.get("machine_type")),
            calibration=clean_text(data.get("calibration")),
            test_report_bar=clean_text(data.get("test_report_bar")),
            export_packing_required=clean_text(data.get("export_packing_required")),
            customer_inspection=clean_text(data.get("customer_inspection")),
            customer_inspection_date=data.get("customer_inspection_date") or None,
            raw_import=raw or {},
        )
        initialize_machine(machine, user)
        log_audit(user, "machine.create", instance=machine, changes={"work_order": machine.planning.work_order})
        if submit:
            submit_planning(machine, user)
    return machine


def update_planning(machine, data, user):
    planning = machine.planning
    planning.company = clean_text(data.get("company")) or planning.company
    planning.work_order = clean_text(data.get("work_order"))
    planning.ccn = clean_text(data.get("ccn"))
    planning.model_description = clean_text(data.get("model_description"))
    planning.machine_type = clean_text(data.get("machine_type"))
    planning.calibration = clean_text(data.get("calibration"))
    planning.test_report_bar = clean_text(data.get("test_report_bar"))
    planning.export_packing_required = clean_text(data.get("export_packing_required"))
    planning.customer_inspection = clean_text(data.get("customer_inspection"))
    planning.customer_inspection_date = data.get("customer_inspection_date") or None
    planning.save()
    priority = normalize_priority(data.get("priority")) or machine.priority
    machine.priority = priority
    machine.save(update_fields=["priority", "updated_at"])
    log_audit(user, "planning.update", instance=machine, changes={"work_order": planning.work_order})
    return machine


def visible_machines(user):
    queryset = Machine.objects.select_related("planning", "station", "created_by", "qc_approved_by")
    if getattr(user, "is_management", False):
        return queryset
    return queryset.filter(Q(status=MachineStatus.DRAFT, created_by=user) | ~Q(status=MachineStatus.DRAFT))


def apply_machine_filters(queryset, params):
    query = (params.get("q") or "").strip()
    if query:
        queryset = queryset.filter(
            Q(machine_id__icontains=query)
            | Q(planner_serial__icontains=query)
            | Q(production_serial__icontains=query)
            | Q(planning__work_order__icontains=query)
            | Q(planning__ccn__icontains=query)
            | Q(planning__model_description__icontains=query)
            | Q(planning__company__icontains=query)
            | Q(station__name__icontains=query)
            | Q(station__code__icontains=query)
        )
    if params.get("status"):
        queryset = queryset.filter(status=params.get("status"))
    if params.get("priority"):
        queryset = queryset.filter(priority=params.get("priority"))
    if params.get("station"):
        queryset = queryset.filter(station_id=params.get("station"))
    if params.get("phase"):
        phase = params.get("phase")
        queryset = queryset.filter(
            Q(current_phase=phase) | Q(phase_states__phase__code=phase, phase_states__status="IN_PROGRESS")
        )
    if params.get("rework") == "yes":
        queryset = queryset.filter(is_under_rework=True).exclude(status=MachineStatus.COMPLETED)
    if params.get("created_from"):
        queryset = queryset.filter(created_at__date__gte=params.get("created_from"))
    if params.get("created_to"):
        queryset = queryset.filter(created_at__date__lte=params.get("created_to"))
    return queryset.distinct()


SORT_FIELDS = {
    "machine_id": "machine_id",
    "work_order": "planning__work_order",
    "model": "planning__model_description",
    "serial": "planner_serial",
    "priority": "priority",
    "status": "status",
    "created": "created_at",
    "updated": "updated_at",
}


def apply_sort(queryset, params):
    field = SORT_FIELDS.get(params.get("sort") or "created", "created_at")
    if (params.get("dir") or "desc") == "asc":
        return queryset.order_by(field, "-pk")
    return queryset.order_by(f"-{field}", "-pk")


def duplicate_fields():
    raw = get_setting("duplicate_fields", "work_order,ccn,model_description")
    allowed = {
        "company",
        "work_order",
        "ccn",
        "model_description",
        "machine_type",
        "calibration",
        "test_report_bar",
        "export_packing_required",
        "customer_inspection",
    }
    fields = [part.strip() for part in raw.split(",") if part.strip() in allowed]
    return fields or ["work_order", "ccn", "model_description"]


def duplicate_key(data, fields):
    return tuple(clean_text(data.get(field)).lower() for field in fields)


def existing_duplicate_keys(fields):
    keys = set()
    for row in MachinePlanningData.objects.values(*fields):
        keys.add(duplicate_key(row, fields))
    return keys
