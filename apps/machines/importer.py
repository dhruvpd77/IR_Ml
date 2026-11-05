import io

import pandas as pd
from django.db import transaction
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from core.constants import PLANNING_COLUMNS, Priority
from machines.models import ImportBatch, ImportRow
from machines.services import (
    clean_text,
    duplicate_fields,
    duplicate_key,
    existing_duplicate_keys,
    normalize_priority,
    register_machine,
)

HEADER_MAP = {}
for key, label, _required in PLANNING_COLUMNS:
    HEADER_MAP[label.strip().lower()] = key
    HEADER_MAP[key.lower()] = key
    HEADER_MAP[key.replace("_", " ").lower()] = key


def planning_template_workbook():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Planning Data"
    headers = [label for _key, label, _required in PLANNING_COLUMNS]
    sheet.append(headers)
    sheet.append(
        [
            "Ingersoll Rand",
            "WO-26101",
            "CCN-1001",
            "R90n Contact-Cooled Rotary 90 kW",
            "OF",
            "Yes",
            "7",
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
    fields = duplicate_fields()
    seen = set()
    existing = existing_duplicate_keys(fields)
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
        key = duplicate_key(normalized, fields)
        duplicate = False
        if not errors:
            if key in seen or key in existing:
                duplicate = True
                errors.append("Duplicate of an existing machine or another row in this file.")
            else:
                seen.add(key)
        rows.append(
            ImportRow(
                batch=batch,
                row_number=offset,
                raw_data=raw,
                normalized=normalized,
                is_valid=not errors and not duplicate,
                is_duplicate=duplicate,
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
    if not data.get("company"):
        data["company"] = "Ingersoll Rand"
        errors = [error for error in errors if not error.startswith("Company")]
    priority = normalize_priority(raw.get("priority"))
    if not clean_text(raw.get("priority")):
        errors.append("Priority is required.")
    elif priority is None:
        errors.append("Priority must be 1st Priority, 2nd Priority, or standard.")
    else:
        data["priority"] = priority
    return data, errors


def confirm_import(batch, user, submit=False):
    if batch.status != ImportBatch.Status.PREVIEW:
        raise ValueError("This import has already been confirmed.")
    valid_rows = list(batch.rows.filter(is_valid=True).order_by("row_number"))
    if not valid_rows:
        raise ValueError("There are no valid rows to import.")
    created = []
    with transaction.atomic():
        for row in valid_rows:
            machine = register_machine(row.normalized, user, submit=submit, raw=row.raw_data)
            row.machine = machine
            row.save(update_fields=["machine"])
            created.append(machine)
        batch.status = ImportBatch.Status.COMPLETED
        batch.created_count = len(created)
        batch.confirmed_at = timezone.now()
        batch.save(update_fields=["status", "created_count", "confirmed_at"])
    return created


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
