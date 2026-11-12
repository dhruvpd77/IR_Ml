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
VIBRATION_HDR = re.compile(r"vai?bration\s+data", re.I)
OIL_FILL_HDR = re.compile(r"oil\s+fill", re.I)
AIREND_TEMP_HDR = re.compile(r"airend\s+dis\.?\s*temp", re.I)
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
GEN_CHECK_ITEM = re.compile(r"earth\s+checked|temp\.?\s*trip|amp\s+trip|moisture\s+checked", re.I)
VIB_AXIS = re.compile(r"^(axial|vertical|horizontal)$", re.I)
OIL_STEP = re.compile(r"^(1st|2nd|3rd|first|second|third|total)$", re.I)


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


def _field_tuple(key, section, label, field_type="short_text", required=False, unit="", extra=""):
    return (key, section, label, field_type, required, unit, extra)


RUNOUT_AXIS = ("Axial", "Radial", "Angular")
_RUNOUT_HINT = re.compile(
    r"run[\s\-]*out|રન\s*આઉટ|coupling|કપલિંગ|લખવી|લખવું|લખો|value|_{3,}",
    re.I,
)


def _runout_axes_in_label(label: str) -> list[str]:
    """Detect Axial/Radial/Angular even when glued to underscores (Axial______)."""
    found = []
    for axis in RUNOUT_AXIS:
        if re.search(rf"(?<![A-Za-z]){axis}(?![A-Za-z])", label or "", re.I):
            found.append(axis)
    return found


def _is_combined_runout_label(label: str) -> bool:
    """True when one checklist line asks for Axial + Radial + Angular values together."""
    axes = _runout_axes_in_label(label)
    if len(axes) < 2:
        return False
    return bool(_RUNOUT_HINT.search(label or "")) or len(axes) >= 3


def _runout_base_label(label: str) -> str:
    text = label or ""
    text = re.split(r"(?<![A-Za-z])Axial(?![A-Za-z])", text, maxsplit=1, flags=re.I)[0]
    text = re.sub(r"^\d+[a-zA-Z]?\.\s*", "", text)
    text = re.sub(r"_{2,}|…|\.{3,}", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .-–,/")
    return text


def runout_decimal_fields(prefix, number, section, label, used):
    """Split a combined Axial/Radial/Angular line into decimal value inputs."""
    axes = _runout_axes_in_label(label)
    if len(axes) < 2:
        return []
    base = _runout_base_label(label)
    short_base = "SIERRA run-out" if re.search(r"sierra", label or "", re.I) else "Coupling run-out"
    fields = []
    for axis in axes:
        # Keep labels short so Axial/Radial/Angular stay visible (label max 200).
        if number:
            shown = f"{number}. {short_base} — {axis}"
        else:
            shown = f"{short_base} — {axis}"
        key_src = f"{number}_runout_{axis}" if number else f"runout_{axis}_{base or axis}"
        fields.append(
            (
                _field_key(prefix, key_src, used),
                section,
                shown[:200],
                "decimal",
                False,
                "",
                "",
            )
        )
    return fields


def repair_general_check_tables(template=None):
    """Fix General check rows: Y/N types, and move lone AXIAL/VERTICAL/HORIZONTAL into Vibration data."""
    qs = JobCardField.objects.filter(is_active=True, section__iexact="General check").select_related("template")
    if template is not None:
        qs = qs.filter(template=template)
    else:
        qs = qs.filter(template__is_active=True)

    fixed = 0
    axis_pat = re.compile(r"^(axial|vertical|horizontal)$", re.I)
    gen_pat = re.compile(r"earth\s+checked|temp\.?\s*trip|amp\s+trip|moisture\s+checked", re.I)
    vib_cols = ("LOAD 1", "LOAD 2", "UNLOAD 1", "UNLOAD 2")

    for field in list(qs.order_by("template_id", "sort_order", "pk")):
        label = (field.label or "").strip()
        if gen_pat.search(label) and field.field_type != "yes_no":
            field.field_type = "yes_no"
            field.save(update_fields=["field_type"])
            fixed += 1
            continue
        if not axis_pat.match(label):
            continue
        axis = label.upper()
        used = set(field.template.fields.values_list("field_key", flat=True))
        sort = field.sort_order
        with transaction.atomic():
            field.is_active = False
            field.save(update_fields=["is_active"])
            for offset, col in enumerate(vib_cols):
                key = _field_key("vib", f"{axis}_{col}", used)
                JobCardField.objects.update_or_create(
                    template=field.template,
                    field_key=key,
                    defaults={
                        "section": "Vibration data",
                        "label": f"{axis} — {col}",
                        "field_type": "decimal",
                        "required": False,
                        "unit": "mm/s",
                        "help_text": f"vib|{axis}|{col}",
                        "options": [],
                        "sort_order": sort + offset,
                        "is_active": True,
                    },
                )
        fixed += 1
    return fixed


def repair_runout_value_fields(template=None):
    """Replace combined Axial/Radial/Angular yes/no (or text) lines with decimal inputs."""
    qs = JobCardField.objects.filter(
        is_active=True,
        field_type__in=["yes_no", "short_text", "long_text"],
    ).select_related("template")
    if template is not None:
        qs = qs.filter(template=template)
    else:
        qs = qs.filter(template__is_active=True)

    fixed = 0
    for field in qs.order_by("template_id", "sort_order", "pk"):
        label = field.label or ""
        if not _is_combined_runout_label(label):
            continue
        number_match = re.match(r"^(\d+[a-zA-Z]?)\.\s*", label)
        number = number_match.group(1) if number_match else ""
        prefix = (field.field_key.split("_", 1)[0] if field.field_key else "aft") or "aft"
        used = set(field.template.fields.values_list("field_key", flat=True))
        specs = runout_decimal_fields(prefix, number, field.section or "", label, used)
        if not specs:
            continue
        with transaction.atomic():
            field.is_active = False
            field.save(update_fields=["is_active"])
            for offset, (key, section, shown, ftype, required, unit, _extra) in enumerate(specs):
                JobCardField.objects.update_or_create(
                    template=field.template,
                    field_key=key,
                    defaults={
                        "section": section,
                        "label": shown,
                        "field_type": ftype,
                        "required": required,
                        "unit": unit,
                        "help_text": "",
                        "options": [],
                        "sort_order": field.sort_order + offset,
                        "is_active": True,
                    },
                )
        fixed += 1

    # Shorten expanded run-out labels that were truncated or still carry the long Gujarati line.
    # Never touch vibration matrix fields (help_text vib|...) or official single-axis keys.
    decimal_qs = JobCardField.objects.filter(is_active=True, field_type="decimal")
    if template is not None:
        decimal_qs = decimal_qs.filter(template=template)
    else:
        decimal_qs = decimal_qs.filter(template__is_active=True)
    for field in decimal_qs:
        label = field.label or ""
        help_text = field.help_text or ""
        key = field.field_key or ""
        if help_text.startswith("vib|"):
            continue
        if key in {"runout_axial", "runout_radial", "runout_angular"}:
            continue
        if "runout" not in key and "— " not in label and not _is_combined_runout_label(label):
            continue
        axis = next((name for name in RUNOUT_AXIS if re.search(rf"(?<![A-Za-z]){name}(?![A-Za-z])", label, re.I)), "")
        if not axis:
            if re.search(r"—\s*Axi", label) and "Axial" not in label:
                axis = "Axial"
            elif re.search(r"—\s*Rad", label) and "Radial" not in label:
                axis = "Radial"
            elif re.search(r"—\s*Ang", label) and "Angular" not in label:
                axis = "Angular"
        if not axis:
            continue
        # Only rewrite long/truncated/combined labels from Word expansion.
        needs_shorten = (
            _is_combined_runout_label(label)
            or len(label) > 70
            or (re.search(r"—\s*Axi", label) and "Axial" not in label)
            or (re.search(r"—\s*Rad", label) and "Radial" not in label)
            or (re.search(r"—\s*Ang", label) and "Angular" not in label)
        )
        if not needs_shorten:
            continue
        number_match = re.match(r"^(\d+[a-zA-Z]?)\.\s*", label)
        number = number_match.group(1) if number_match else ""
        short = "SIERRA run-out" if re.search(r"sierra", label, re.I) else "Coupling run-out"
        shown = f"{number}. {short} — {axis}" if number else f"{short} — {axis}"
        if field.label != shown:
            field.label = shown
            field.save(update_fields=["label"])
            fixed += 1
    return fixed


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


def _cell(ws, row, col):
    return _text(ws.cell(row, col).value)


def _row_values(ws, row, max_col=20):
    return [_cell(ws, row, col) for col in range(1, max_col + 1)]


def _find_col(values, pattern):
    for index, value in enumerate(values, start=1):
        if value and pattern.search(value):
            return index
    return None


def _parse_post_testing_tables(ws, header_row, testing_fields, used):
    """Parse GENERAL CHECK + VIBRATION DATA + OIL FILL (+ airend temp) block from Excel."""
    header = _row_values(ws, header_row, 20)
    if not any(GENERAL.search(value) for value in header if value):
        return False

    oil_col = _find_col(header, OIL_FILL_HDR) or 14
    temp_col = _find_col(header, AIREND_TEMP_HDR)
    has_vib = any(VIBRATION_HDR.search(value) for value in header if value)

    # Sub-header row usually has LOAD/UNLOAD 1/2 markers.
    sub = _row_values(ws, header_row + 1, 20)
    load_cols = []
    unload_cols = []
    # Prefer numeric 1/2 under LOAD / UNLOAD bands (cols 8-11 on shop sheets).
    for col in range(7, 13):
        value = sub[col - 1] if col - 1 < len(sub) else ""
        if value in {"1", "2"}:
            if col <= 9 and len(load_cols) < 2:
                load_cols.append(col)
            elif col >= 10 and len(unload_cols) < 2:
                unload_cols.append(col)
    if len(load_cols) < 2:
        load_cols = [8, 9]
    if len(unload_cols) < 2:
        unload_cols = [10, 11]

    vib_cols = [
        ("LOAD 1", load_cols[0]),
        ("LOAD 2", load_cols[1]),
        ("UNLOAD 1", unload_cols[0]),
        ("UNLOAD 2", unload_cols[1]),
    ]

    general_fields = []
    vibration_fields = []
    oil_fields = []
    temp_fields = []

    if temp_col:
        temp_fields.append(
            _field_tuple(
                _field_key("temp", "airend_dis_temp", used),
                "Airend discharge temp",
                "AIREND DIS. TEMP. (°C)",
                field_type="decimal",
                unit="°C",
            )
        )

    for offset in range(1, 6):
        row = header_row + offset
        values = _row_values(ws, row, 20)
        if not any(values):
            continue
        joined = " | ".join(value for value in values if value)
        if EOL_HEADER.search(joined):
            break

        left = values[0]
        if left and GEN_CHECK_ITEM.search(left):
            general_fields.append(
                (
                    _field_key("gen", left, used),
                    "General check",
                    left[:200],
                    "yes_no",
                    False,
                    "",
                    "",
                )
            )

        axis = ""
        for value in values:
            if value and VIB_AXIS.match(value.strip()):
                axis = value.strip().upper()
                break
        if has_vib and axis:
            for col_name, _col in vib_cols:
                vibration_fields.append(
                    _field_tuple(
                        _field_key("vib", f"{axis}_{col_name}", used),
                        "Vibration data",
                        f"{axis} — {col_name}",
                        field_type="decimal",
                        unit="mm/s",
                        extra=f"vib|{axis}|{col_name}",
                    )
                )

        oil_label = ""
        oil_value = values[oil_col - 1] if oil_col - 1 < len(values) else ""
        if oil_value and OIL_STEP.match(oil_value.strip()):
            oil_label = oil_value.strip().upper()
            if oil_label == "FIRST":
                oil_label = "1ST"
            elif oil_label == "SECOND":
                oil_label = "2ND"
            elif oil_label == "THIRD":
                oil_label = "3RD"
        if oil_label:
            oil_fields.append(
                _field_tuple(
                    _field_key("oil", oil_label, used),
                    "Oil fill",
                    oil_label,
                    field_type="decimal",
                    unit="LTR",
                    extra=f"oil|{oil_label}|LTR",
                )
            )

    # Same left-to-right order as the Excel block.
    testing_fields.extend(general_fields)
    testing_fields.extend(vibration_fields)
    testing_fields.extend(temp_fields)
    testing_fields.extend(oil_fields)
    return True


def parse_sheet(worksheet, sheet_name):
    """Return Assembly/Testing field lists for one checklist sheet."""
    checklist_key = normalize_job_card_key(sheet_name)
    mode = "parts"  # parts | assembly | audit | testing | done
    test_section = "Before testing"
    assembly_fields = []
    testing_fields = []
    used = set()
    skip_until = 0
    max_row = worksheet.max_row or 0

    for row_idx in range(1, max_row + 1):
        if row_idx <= skip_until:
            continue
        raw = _row_values(worksheet, row_idx, 20)
        cells = [value for value in raw if value]
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

        # Post-testing Excel block: GENERAL CHECK + vibration + oil fill tables.
        if _section_header(GENERAL) or (
            any(GENERAL.search(cell) for cell in cells)
            and any(VIBRATION_HDR.search(cell) or OIL_FILL_HDR.search(cell) for cell in cells)
        ):
            if _parse_post_testing_tables(worksheet, row_idx, testing_fields, used):
                skip_until = row_idx + 5
                mode = "testing"
                continue

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
                prefix = "asm" if mode == "assembly" else "aud"
                if _is_combined_runout_label(label):
                    assembly_fields.extend(runout_decimal_fields(prefix, number, section, label, used))
                elif re.search(r"લિટર|liter|mm|ltr", label, re.I) and re.search(r"ઓઈલ|oil|ગેપ|gap", label, re.I):
                    unit = "LTR" if re.search(r"લિટર|liter|ltr", label, re.I) else "mm"
                    assembly_fields.append(
                        (_field_key("asm", f"{number}_{label}", used), section, f"{number}. {label}"[:200], "decimal", False, unit, "")
                    )
                else:
                    assembly_fields.append(_yes_no(prefix, number, section, label, used))
            continue

        if mode == "testing":
            if any(SIGN_OFF.search(cell) for cell in cells):
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
            number, label = _split_number_label(cells)
            # BEFORE TESTING row often has section title + number + label
            if not label:
                continue
            prefix = {"Before testing": "bef", "During testing": "dur", "After testing": "aft"}.get(test_section, "tst")
            if _is_combined_runout_label(f"{number}. {label}" if number else label):
                testing_fields.extend(
                    runout_decimal_fields(prefix, number, test_section, f"{number}. {label}" if number else label, used)
                )
            elif re.search(r"લખવું|લખવી|reading|rating|cfm|power|rpm|program|value|નું", label, re.I):
                testing_fields.append(_short("tst", f"{number}_{label}", test_section, used))
            else:
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
    if extra.startswith(("belt_chart|", "press|", "parts|", "vib|", "oil|")):
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
        if help_text.startswith(("press|", "belt_chart|", "parts|", "vib|", "oil|")):
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
    repaired = repair_runout_value_fields() + repair_general_check_tables()
    return {
        "created": created,
        "updated": updated,
        "empty": empty,
        "sheets": len(workbook.sheetnames),
        "details": results,
        "runout_repaired": repaired,
    }


def find_checklist_sheet_name(workbook, job_card_key):
    wanted = normalize_job_card_key(job_card_key).lower()
    if not wanted:
        return None
    for name in workbook.sheetnames:
        if normalize_job_card_key(name).lower() == wanted:
            return name
    return None
