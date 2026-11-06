import io

import pandas as pd
from django.db import transaction
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from core.constants import PLANNING_COLUMNS, Priority
from machines.catalog import _canonical
from machines.forms import COMPANY_CHOICES, TYPE_CHOICES
from machines.models import ImportBatch, ImportRow, PlanningCatalogItem
from machines.services import clean_text

HEADER_MAP = {}
for key, label, _required in PLANNING_COLUMNS:
    HEADER_MAP[label.strip().lower()] = key
    HEADER_MAP[key.lower()] = key
    HEADER_MAP[key.replace("_", " ").lower()] = key
HEADER_MAP["company"] = "company"
HEADER_MAP["machine id"] = "machine_id"
HEADER_MAP["machine_id"] = "machine_id"
HEADER_MAP["cnn"] = "ccn"


def planning_template_workbook():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Planning Data"
    headers = ["Machine ID"] + [label for _key, label, _required in PLANNING_COLUMNS]
    sheet.append(headers)
    sheet.append(
        [
            "",
            "Ingersoll Rand",
            "CCN-1001",
            "R90n Contact-Cooled Rotary 90 kW",
            "OF",
            "WO-26101",
            "Yes",
            "1st shift",
            "Standard",
            "No",
            "No",
            "1st Priority",
        ]
    )
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="0B1D36")
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def _mapped_frame(uploaded):
    frame = pd.read_excel(uploaded, dtype=str)
    frame = frame.dropna(how="all")
    frame.columns = [str(column).strip() for column in frame.columns]
    unknown = [column for column in frame.columns if column.strip().lower() not in HEADER_MAP and column.strip()]
    rename = {column: HEADER_MAP[column.strip().lower()] for column in frame.columns if column.strip().lower() in HEADER_MAP}
    frame = frame.rename(columns=rename)
    return frame, unknown


def build_import_preview(uploaded, user):
    frame, unknown = _mapped_frame(uploaded)
    uploaded.seek(0)
    seen_models = set()
    batch = ImportBatch.objects.create(
        source_file=uploaded,
        original_name=getattr(uploaded, "name", "import.xlsx"),
        uploaded_by=user,
        total_rows=0,
    )
    rows = []
    for offset, record in enumerate(frame.to_dict(orient="records"), start=2):
        raw = {str(key): "" if value is None or str(value) == "nan" else str(value).strip() for key, value in record.items()}
        if not any(raw.get(key) for key, _label, _required in PLANNING_COLUMNS):
            continue
        normalized, errors = _normalize_row(raw)
        if not errors:
            model_key = (
                clean_text(normalized.get("company")).lower(),
                clean_text(normalized.get("machine_type")).lower(),
                clean_text(normalized.get("model_description")).lower(),
            )
            normalized["action"] = "catalog"
            if model_key in seen_models:
                normalized["note"] = "Same model as an earlier row. The later CCN is kept."
            seen_models.add(model_key)
        rows.append(
            ImportRow(
                batch=batch,
                row_number=offset,
                raw_data=raw,
                normalized=normalized,
                is_valid=not errors,
                is_duplicate=False,
                errors=errors,
            )
        )
    if rows:
        ImportRow.objects.bulk_create(rows)
    batch.total_rows = len(rows)
    batch.valid_count = sum(1 for row in rows if row.is_valid)
    batch.duplicate_count = sum(1 for row in rows if row.is_duplicate)
    batch.error_count = sum(1 for row in rows if not row.is_valid)
    batch.save()
    return batch, unknown


def _normalize_row(raw):
    errors = []
    data = {}
    for key, _label, required in PLANNING_COLUMNS:
        if key == "priority":
            continue
        data[key] = clean_text(raw.get(key))
        if required and not data[key]:
            errors.append(f"{_label} is required.")
    if data.get("company"):
        data["company"] = _canonical(data["company"], COMPANY_CHOICES)
    if data.get("machine_type"):
        data["machine_type"] = _canonical(data["machine_type"], TYPE_CHOICES)
    return data, errors


def _upsert_catalog(normalized, user):
    company = clean_text(normalized.get("company"))
    machine_type = clean_text(normalized.get("machine_type"))
    model = clean_text(normalized.get("model_description"))
    ccn = clean_text(normalized.get("ccn"))
    if not (company and machine_type and model and ccn):
        return
    PlanningCatalogItem.objects.update_or_create(
        company=company[:160],
        machine_type=machine_type[:120],
        model_description=model[:240],
        defaults={
            "ccn": ccn[:80],
            "uploaded_by": user if getattr(user, "is_authenticated", False) else None,
            "uploaded_at": timezone.now(),
        },
    )


def confirm_import(batch, user, submit=False):
    if batch.status != ImportBatch.Status.PREVIEW:
        raise ValueError("This import has already been confirmed.")
    valid_rows = list(batch.rows.filter(is_valid=True).order_by("row_number"))
    if not valid_rows:
        raise ValueError("There are no valid rows to import.")
    keys = set()
    with transaction.atomic():
        for row in valid_rows:
            normalized = row.normalized or {}
            _upsert_catalog(normalized, user)
            keys.add(
                (
                    clean_text(normalized.get("company")).lower(),
                    clean_text(normalized.get("machine_type")).lower(),
                    clean_text(normalized.get("model_description")).lower(),
                )
            )
        batch.status = ImportBatch.Status.COMPLETED
        batch.created_count = len(keys)
        batch.confirmed_at = timezone.now()
        batch.save(update_fields=["status", "created_count", "confirmed_at"])
    return len(keys)


def error_workbook(batch):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Import errors"
    headers = ["Row"] + [label for _key, label, _required in PLANNING_COLUMNS] + ["Errors"]
    sheet.append(headers)
    for row in batch.rows.filter(is_valid=False):
        values = [row.row_number]
        for key, _label, _required in PLANNING_COLUMNS:
            source = row.raw_data or {}
            values.append(source.get(key, ""))
        values.append("; ".join(row.errors or []))
        sheet.append(values)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
