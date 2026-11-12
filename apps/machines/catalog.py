import io
import re

from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from machines.forms import COMPANY_CHOICES, TYPE_CHOICES
from machines.models import PlanningCatalogItem


class CatalogError(ValueError):
    pass


BRAND_ALIASES = {
    "ir": "Ingersoll Rand",
    "ingersoll rand": "Ingersoll Rand",
    "ingersoll": "Ingersoll Rand",
    "comp": "Compair",
    "compair": "Compair",
    "fmb": "Champion",
    "champion": "Champion",
    "airend": "Ingersoll Rand",
}


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def normalize_job_card_key(value):
    return re.sub(r"\s+", " ", _cell(value)).strip()


# Catalog Job Card Detail names that have no sheet of their own, but share an
# existing checklist sheet in UPDATED Production Checklists.
# Only used for Excel-backed rows. Word-backed keys keep their own name and
# load from jobcard_word_file/ instead.
CHECKLIST_ALIASES = {
    "fmb7-11 kw": "FMb7-22",
}


def normalize_job_card_format(value):
    text = _cell(value).lower()
    if text in {"excel", "xlsx", "xls"}:
        return "excel"
    if text in {"word", "doc", "docx"}:
        return "word"
    return ""


def resolve_checklist_key(job_card_key, source_format=""):
    """Normalize catalog key and apply Excel sheet aliases when needed.

    Word-backed keys are never aliased — they match a filename in jobcard_word_file/.
    """
    key = normalize_job_card_key(job_card_key)
    if not key:
        return ""
    fmt = normalize_job_card_format(source_format)
    if fmt == "word":
        return key
    alias = CHECKLIST_ALIASES.get(key.lower())
    return normalize_job_card_key(alias) if alias else key


def _canonical(value, choices):
    text = _cell(value)
    lookup = {label.lower(): label for label, _display in choices}
    return lookup.get(text.lower(), text)


def _canonical_company(value):
    text = _cell(value)
    if not text:
        return ""
    mapped = BRAND_ALIASES.get(text.lower())
    if mapped:
        return mapped
    return _canonical(text, COMPANY_CHOICES)


def _canonical_type(value):
    return _canonical(value, TYPE_CHOICES)


def _header_map(header):
    columns = {}
    for index, name in enumerate(header):
        key = _cell(name).lower()
        if not key:
            continue
        columns[key] = index
        if "brand" in key or "ingersoll" in key or key in {"ir / comp / fmb", "company"}:
            columns.setdefault("company", index)
        if key in {"description", "model description", "model"}:
            columns.setdefault("model description", index)
        if key in {"type", "machine type"}:
            columns.setdefault("type", index)
        if key in {"ccn", "package ccn"}:
            columns.setdefault("ccn", index)
        if key in {"machine name", "machinename", "machine_name", "name"} or (
            "machine" in key and "name" in key
        ):
            columns.setdefault("machine name", index)
        if "job card" in key and "word" not in key and "excel" not in key:
            columns.setdefault("job card detail", index)
        if key in {"word/excel", "word excel", "format", "job card format", "source"}:
            columns.setdefault("word/excel", index)
        if "word" in key and "excel" in key:
            columns.setdefault("word/excel", index)
    if "brand" in columns and "company" not in columns:
        columns["company"] = columns["brand"]
    return columns


def models_for(company, machine_type):
    """Return (model_description, ccn, job_card_key, job_card_format) rows for planning dropdowns."""
    company = _cell(company)
    machine_type = _cell(machine_type)
    if not company or not machine_type:
        return []
    return list(
        PlanningCatalogItem.objects.filter(company=company, machine_type=machine_type)
        .order_by("model_description")
        .values_list("model_description", "ccn", "job_card_key", "job_card_format")
    )


def find_model(company, machine_type, model_description):
    company = _cell(company)
    machine_type = _cell(machine_type)
    model_description = _cell(model_description)
    if not company or not machine_type or not model_description:
        return None
    return PlanningCatalogItem.objects.filter(
        company=company,
        machine_type=machine_type,
        model_description=model_description,
    ).first()


def find_by_ccn(ccn):
    ccn = _cell(ccn)
    if not ccn:
        return None
    return PlanningCatalogItem.objects.filter(ccn=ccn).order_by("pk").first()


def catalog_item_for_machine(machine):
    """Return the PlanningCatalogItem for this machine's planning row, if any."""
    planning = getattr(machine, "planning", None)
    if planning is None:
        return None
    item = find_model(planning.company, planning.machine_type, planning.model_description)
    if item is None and planning.ccn:
        item = find_by_ccn(planning.ccn)
    return item


def job_card_key_for_machine(machine):
    """Resolve checklist key from catalog for this machine's planning row."""
    item = catalog_item_for_machine(machine)
    if item is None:
        return ""
    return normalize_job_card_key(item.job_card_key)


def job_card_format_for_machine(machine):
    item = catalog_item_for_machine(machine)
    if item is None:
        return ""
    return normalize_job_card_format(item.job_card_format)


def catalog_machine_name(company, machine_type, model_description, ccn=""):
    item = find_model(company, machine_type, model_description)
    if item is None and ccn:
        item = find_by_ccn(ccn)
    if item is None:
        return ""
    return _cell(item.machine_name)


def display_name_for_machine(machine):
    """Floor/layout label: catalog machine name, else IR-MCH id."""
    planning = getattr(machine, "planning", None)
    if planning is not None:
        stored = _cell(getattr(planning, "machine_name", ""))
        if stored:
            return stored
        looked_up = catalog_machine_name(
            planning.company,
            planning.machine_type,
            planning.model_description,
            planning.ccn,
        )
        if looked_up:
            return looked_up
    return machine.machine_id


def extra_companies():
    return list(PlanningCatalogItem.objects.order_by("company").values_list("company", flat=True).distinct())


def extra_types():
    return list(PlanningCatalogItem.objects.order_by("machine_type").values_list("machine_type", flat=True).distinct())


def replace_catalog(upload, user):
    try:
        workbook = load_workbook(io.BytesIO(upload.read()), data_only=True)
    except Exception as exc:
        raise CatalogError("That workbook could not be read. Upload an Excel .xlsx file.") from exc
    sheet = workbook.active
    rows = sheet.iter_rows(values_only=True)
    header = next(rows, None)
    if not header:
        raise CatalogError("The workbook is empty.")
    columns = _header_map(header)
    required = ("company", "ccn", "type", "model description")
    missing = [name for name in required if name not in columns]
    if missing:
        raise CatalogError("Missing columns: " + ", ".join(missing) + ".")

    seen = set()
    items = []
    skipped = 0
    now = timezone.now()
    for row in rows:
        def value(name, row=row):
            index = columns[name]
            return row[index] if index < len(row) else ""

        company = _canonical_company(value("company"))
        machine_type = _canonical_type(value("type"))
        model = _cell(value("model description"))
        ccn = _cell(value("ccn"))
        job_card_key = ""
        if "job card detail" in columns:
            job_card_key = normalize_job_card_key(value("job card detail"))
        job_card_format = ""
        if "word/excel" in columns:
            job_card_format = normalize_job_card_format(value("word/excel"))
        machine_name = ""
        if "machine name" in columns:
            machine_name = _cell(value("machine name"))
        if not company or not machine_type or not model or not ccn:
            if any((company, machine_type, model, ccn)):
                skipped += 1
            continue
        key = (company.lower(), machine_type.lower(), model.lower())
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        items.append(
            PlanningCatalogItem(
                company=company[:160],
                machine_type=machine_type[:120],
                model_description=model[:240],
                ccn=ccn[:80],
                machine_name=machine_name[:160],
                job_card_key=job_card_key[:160],
                job_card_format=job_card_format[:16],
                uploaded_by=user if getattr(user, "is_authenticated", False) else None,
                uploaded_at=now,
            )
        )
    if not items:
        raise CatalogError("No model rows were found. Each row needs Brand, Type, Model Description, and CCN.")
    with transaction.atomic():
        PlanningCatalogItem.objects.all().delete()
        PlanningCatalogItem.objects.bulk_create(items)
        _sync_planning_machine_names(items)
    return {"created": len(items), "skipped": skipped}


def _sync_planning_machine_names(items):
    """Refresh machine_name on existing planning rows from the newly uploaded catalog."""
    from machines.models import MachinePlanningData

    by_model = {
        (item.company.lower(), item.machine_type.lower(), item.model_description.lower()): item.machine_name
        for item in items
        if item.machine_name
    }
    by_ccn = {item.ccn: item.machine_name for item in items if item.ccn and item.machine_name}
    if not by_model and not by_ccn:
        return
    updates = []
    for planning in MachinePlanningData.objects.all().only(
        "pk", "company", "machine_type", "model_description", "ccn", "machine_name"
    ):
        name = by_model.get((planning.company.lower(), planning.machine_type.lower(), planning.model_description.lower()))
        if not name and planning.ccn:
            name = by_ccn.get(planning.ccn)
        if name and planning.machine_name != name:
            planning.machine_name = name[:160]
            updates.append(planning)
    if updates:
        MachinePlanningData.objects.bulk_update(updates, ["machine_name"], batch_size=200)
