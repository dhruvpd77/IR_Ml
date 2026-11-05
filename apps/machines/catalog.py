import io

from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from machines.forms import COMPANY_CHOICES, TYPE_CHOICES
from machines.models import PlanningCatalogItem


class CatalogError(ValueError):
    pass


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _canonical(value, choices):
    text = _cell(value)
    lookup = {label.lower(): label for label, _display in choices}
    return lookup.get(text.lower(), text)


def models_for(company, machine_type):
    company = _cell(company)
    machine_type = _cell(machine_type)
    if not company or not machine_type:
        return []
    return list(
        PlanningCatalogItem.objects.filter(company=company, machine_type=machine_type)
        .order_by("model_description")
        .values_list("model_description", "ccn")
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
    columns = {_cell(name).lower(): index for index, name in enumerate(header) if _cell(name)}
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

        company = _canonical(value("company"), COMPANY_CHOICES)
        machine_type = _canonical(value("type"), TYPE_CHOICES)
        model = _cell(value("model description"))
        ccn = _cell(value("ccn"))
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
                uploaded_by=user if getattr(user, "is_authenticated", False) else None,
                uploaded_at=now,
            )
        )
    if not items:
        raise CatalogError("No model rows were found. Each row needs Company, Type, Model Description, and CCN.")
    with transaction.atomic():
        PlanningCatalogItem.objects.all().delete()
        PlanningCatalogItem.objects.bulk_create(items)
    return {"created": len(items), "skipped": skipped}
