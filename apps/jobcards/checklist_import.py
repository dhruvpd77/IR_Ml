"""Import model-wise Assembly/Testing templates from production checklist workbooks."""

from __future__ import annotations

import re
from pathlib import Path

from django.db import transaction
from django.utils.text import slugify
from openpyxl import load_workbook

from core.constants import PhaseCode
from jobcards.models import JobCardField, JobCardTemplate
from machines.catalog import normalize_job_card_key

ASSEMBLY_HEADER = re.compile(r"એસેમ્બલી|assembly\s*check", re.I)
TESTING_HEADER = re.compile(r"ટેસ્ટિંગ|testing\s*check", re.I)
AUDIT_HEADER = re.compile(r"final\s+self|sequential\s+audit", re.I)
EOL_HEADER = re.compile(r"end\s+of\s+line", re.I)
BEFORE = re.compile(r"before\s+testing", re.I)
DURING = re.compile(r"during\s+testing", re.I)
AFTER = re.compile(r"after\s+testing", re.I)
GENERAL = re.compile(r"general\s+check", re.I)
SIGN_OFF = re.compile(
    r"assembled\s+by|sub\s+assembled|pkg\s+assembled|tested\s+by|testing\s+result|tesitng\s+result|if\s+not\s+ok",
    re.I,
)
PARTISH = re.compile(
    r"part\s*number|serial\s*number|ccn|pulley|belt|cooler|dryer|receiver|controller|vfd|motor|airend|panel|valve|gear\s*set|seperator|separator|combi",
    re.I,
)
SKIP_ROW = re.compile(r"owner of document|planning date|stock date|name of customer|fill below|apex|small industrial|ultra coolant|fluidforce|aeon", re.I)
NUM = re.compile(r"^\d+[a-zA-Z]?$")


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    return str(value).replace("\n", " ").strip()


def _nonempty(row):
    return [_text(value) for value in row if _text(value)]


def _field_key(prefix, label, used):
    base = slugify(label)[:50] or "field"
    key = f"{prefix}_{base}"[:80]
    if key not in used:
        used.add(key)
        return key
    index = 2
    while True:
        candidate = f"{key[:70]}_{index}"[:80]
        if candidate not in used:
            used.add(candidate)
            return candidate
        index += 1


def _yes_no(prefix, number, section, label, used):
    shown = f"{number}. {label}" if number and not str(label).startswith(str(number)) else label
    key_src = f"{prefix}_{number}_{label}" if number else label
    return (_field_key(prefix, key_src, used), section, shown[:200], "yes_no", False, "", "")


def _short(prefix, label, section, used, unit=""):
    return (_field_key(prefix, label, used), section, label[:200], "short_text", False, unit, "")


def _split_number_label(cells):
    """Find a checklist number + label pair anywhere in the row."""
    for index, value in enumerate(cells):
        if NUM.match(value) or (value.isdigit()):
            label = ""
            for later in cells[index + 1 :]:
                if later and not NUM.match(later):
                    label = later
                    break
            return value, label
    return "", ""


def parse_sheet(worksheet, sheet_name):
    """Return Assembly/Testing field lists for one checklist sheet."""
    checklist_key = normalize_job_card_key(sheet_name)
    mode = "parts"  # parts | assembly | audit | testing | done
    test_section = "Before testing"
    assembly_fields = []
    testing_fields = []
    used = set()

    for row in worksheet.iter_rows(values_only=True):
        cells = _nonempty(row)
        if not cells:
            continue
        joined = " | ".join(cells)
        if SKIP_ROW.search(joined):
            continue

        if EOL_HEADER.search(joined):
            mode = "done"
            continue
        if mode == "done":
            continue

        # Section headers (Gujarati/English often start mid-row).
        if any(ASSEMBLY_HEADER.search(cell) for cell in cells) and (
            "check" in joined.lower() or "ચેક" in joined or "લિસ્ટ" in joined
        ):
            mode = "assembly"
            continue
        if any(AUDIT_HEADER.search(cell) for cell in cells):
            if mode in {"parts", "assembly", "audit"}:
                mode = "audit"
            continue
        def _section_header(pattern, max_len=48):
            """True only when a cell is mainly the section title (not a long checklist line)."""
            for cell in cells:
                if pattern.search(cell) and len(cell) <= max_len:
                    return True
            return False

        # Sheet title rows only — checklist lines can contain ટેસ્ટિંગ / testing.
        if mode != "testing" and _section_header(TESTING_HEADER):
            mode = "testing"
            test_section = "Before testing"
            continue

        if mode in {"testing", "audit", "assembly", "parts"} and _section_header(BEFORE):
            mode = "testing"
            test_section = "Before testing"
        elif mode in {"testing", "audit", "assembly", "parts"} and _section_header(DURING):
            mode = "testing"
            test_section = "During testing"
        elif mode in {"testing", "audit", "assembly", "parts"} and _section_header(AFTER):
            mode = "testing"
            test_section = "After testing"
        elif _section_header(GENERAL):
            mode = "testing"
            test_section = "General check"
            continue

        if mode == "parts":
            for cell in cells:
                if PARTISH.search(cell):
                    assembly_fields.append(_short("part", cell, "Assembly parts", used))
            continue

        if mode in {"assembly", "audit"}:
            section = "Assembly checklist" if mode == "assembly" else "Final audit"
            if any(SIGN_OFF.search(cell) for cell in cells):
                for cell in cells:
                    clean = cell.rstrip(":").strip()
                    if re.search(r"assembled\s+by|sub\s+assembled", clean, re.I):
                        assembly_fields.append(_short("sign", clean, "Assembly sign off", used))
                continue
            number, label = _split_number_label(cells)
            if label:
                if re.search(r"લિટર|liter|mm|ltr", label, re.I) and re.search(r"ઓઈલ|oil|ગેપ|gap", label, re.I):
                    unit = "LTR" if re.search(r"લિટર|liter|ltr", label, re.I) else "mm"
                    assembly_fields.append(
                        (_field_key("asm", f"{number}_{label}", used), section, f"{number}. {label}"[:200], "decimal", False, unit, "")
                    )
                else:
                    prefix = "asm" if mode == "assembly" else "aud"
                    assembly_fields.append(_yes_no(prefix, number, section, label, used))
            continue

        if mode == "testing":
            if any(SIGN_OFF.search(cell) for cell in cells) and test_section != "General check":
                for cell in cells:
                    clean = cell.rstrip(":").strip()
                    if re.search(r"tested\s+by", clean, re.I):
                        testing_fields.append(_short("test", clean, "Testing sign off", used))
                    elif re.search(r"testing\s+result|tesitng\s+result", clean, re.I):
                        testing_fields.append(
                            (
                                _field_key("test", "test_result", used),
                                "Testing sign off",
                                "Testing result",
                                "radio",
                                True,
                                "",
                                "OK|NOT OK",
                            )
                        )
                    elif re.search(r"if\s+not\s+ok|report\s+problem", clean, re.I):
                        testing_fields.append(
                            (_field_key("test", "report_problem", used), "If not OK", "If not OK — report problem", "short_text", False, "", "")
                        )
                continue
            if test_section == "General check":
                for cell in cells:
                    if re.search(r"checked|earth|temp|amp|moisture|axial|vertical|horizontal|load|unload|vibration|oil fill", cell, re.I):
                        if cell.upper() in {"Y/N", "YN"}:
                            continue
                        testing_fields.append(_short("gen", cell, "General check", used))
                continue
            number, label = _split_number_label(cells)
            # BEFORE TESTING row often has section title + number + label
            if not label:
                continue
            if re.search(r"લખવું|reading|rating|cfm|power|rpm|program|value|નું", label, re.I):
                testing_fields.append(_short("tst", f"{number}_{label}", test_section, used))
            else:
                prefix = {"Before testing": "bef", "During testing": "dur", "After testing": "aft"}.get(test_section, "tst")
                testing_fields.append(_yes_no(prefix, number, test_section, label, used))
            continue

    return {
        "checklist_key": checklist_key,
        "sheet_name": sheet_name,
        PhaseCode.ASSEMBLY: assembly_fields,
        PhaseCode.TESTING: testing_fields,
    }


def _pack_field_extra(field_type, extra=""):
    extra = extra or ""
    if field_type == "radio":
        return [item.strip() for item in extra.split("|") if item.strip()], ""
    if extra.startswith("help:"):
        return [], extra[5:][:240]
    if extra.startswith("belt_chart|") or extra.startswith("press|"):
        return [], extra[:240]
    return [], ""


def _write_fields(template, fields):
    created = []
    for index, (key, section, label, field_type, required, unit, extra) in enumerate(fields, start=1):
        options, help_text = _pack_field_extra(field_type, extra)
        created.append(
            JobCardField(
                template=template,
                field_key=key,
                section=section,
                label=label,
                field_type=field_type,
                required=required,
                unit=unit,
                options=options,
                help_text=help_text,
                sort_order=index,
            )
        )
    JobCardField.objects.bulk_create(created)


def _field_extra_for_fingerprint(field_type, options=None, help_text="", extra=""):
    if field_type == "radio":
        if extra:
            return extra
        return "|".join(options or [])
    if extra:
        return extra
    if help_text:
        if help_text.startswith("press|") or help_text.startswith("belt_chart|"):
            return help_text
        return f"help:{help_text}"
    return ""


def _field_fingerprint(fields):
    """Compare key/section/label/type so Excel edits (new rows or renamed labels) bump the template."""
    return [
        (key, section, label, field_type, bool(required), unit or "", extra or "")
        for key, section, label, field_type, required, unit, extra in fields
    ]


def upsert_phase_template(phase_code, checklist_key, name, fields, description=""):
    if not fields:
        return None
    existing = (
        JobCardTemplate.objects.filter(phase_code=phase_code, checklist_key=checklist_key, is_active=True)
        .order_by("-version")
        .first()
    )
    if existing:
        current = []
        for field in existing.fields.filter(is_active=True).order_by("sort_order"):
            if field.field_key == "testing_video":
                continue
            extra = _field_extra_for_fingerprint(field.field_type, field.options, field.help_text)
            current.append(
                (field.field_key, field.section, field.label, field.field_type, bool(field.required), field.unit or "", extra)
            )
        if current == _field_fingerprint(fields):
            return existing
        existing.is_active = False
        existing.save(update_fields=["is_active"])
        version = existing.version + 1
    else:
        version = 1
    template = JobCardTemplate.objects.create(
        phase_code=phase_code,
        checklist_key=checklist_key,
        name=name[:160],
        description=description[:500] if description else f"Imported from checklist sheet {checklist_key}",
        version=version,
        is_active=True,
    )
    _write_fields(template, fields)
    return template


def import_checklists_workbook(path):
    path = Path(path)
    workbook = load_workbook(path, data_only=True)
    created = 0
    updated = 0
    empty = 0
    results = []
    with transaction.atomic():
        for sheet_name in workbook.sheetnames:
            parsed = parse_sheet(workbook[sheet_name], sheet_name)
            key = parsed["checklist_key"]
            for phase_code, title in (
                (PhaseCode.ASSEMBLY, f"Assembly · {key}"),
                (PhaseCode.TESTING, f"Testing · {key}"),
            ):
                fields = parsed[phase_code]
                if not fields:
                    empty += 1
                    results.append({"sheet": sheet_name, "phase": phase_code, "status": "empty"})
                    continue
                before = JobCardTemplate.objects.filter(phase_code=phase_code, checklist_key=key, is_active=True).exists()
                template = upsert_phase_template(phase_code, key, title, fields)
                if template is None:
                    empty += 1
                    results.append({"sheet": sheet_name, "phase": phase_code, "status": "empty"})
                    continue
                if phase_code == PhaseCode.TESTING and not template.fields.filter(field_key="testing_video").exists():
                    last = template.fields.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0
                    JobCardField.objects.create(
                        template=template,
                        field_key="testing_video",
                        section="Inspection video",
                        label="Inspection video",
                        field_type="video",
                        required=False,
                        sort_order=last + 1,
                    )
                if before:
                    updated += 1
                    results.append({"sheet": sheet_name, "phase": phase_code, "status": "updated", "fields": len(fields)})
                else:
                    created += 1
                    results.append({"sheet": sheet_name, "phase": phase_code, "status": "created", "fields": len(fields)})
    return {"created": created, "updated": updated, "empty": empty, "sheets": len(workbook.sheetnames), "details": results}


def find_checklist_sheet_name(workbook, job_card_key):
    wanted = normalize_job_card_key(job_card_key).lower()
    if not wanted:
        return None
    for name in workbook.sheetnames:
        if normalize_job_card_key(name).lower() == wanted:
            return name
    return None
