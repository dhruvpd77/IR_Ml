"""Import model-wise Assembly/Testing templates from Word job cards in jobcard_word_file/."""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.db import transaction

from core.constants import PhaseCode
from jobcards.checklist_import import (
    _field_key,
    _short,
    _yes_no,
    upsert_phase_template,
)
from jobcards.models import JobCardField, JobCardTemplate
from machines.catalog import normalize_job_card_key

PARTS_HEADER = re.compile(r"list\s+of\s+major\s+parts|major\s+parts\s+details|મુખ્ય\s+ભાગ", re.I)
AUDIT_HEADER = re.compile(r"final\s+self|sequential\s+audit", re.I)
BEFORE_HEADER = re.compile(r"ટેસ્ટિંગ\s+પહેલાં|before\s+testing", re.I)
DURING_HEADER = re.compile(r"ટેસ્ટિંગ\s+દરમિયાન|during\s+testing", re.I)
AFTER_HEADER = re.compile(r"ટેસ્ટિંગ\s+પછી|after\s+testing", re.I)
SIGN_DATE = re.compile(r"sign\s*/?\s*date|name\s*/?\s*sign", re.I)
SKIP_TABLE = re.compile(
    r"revision\s+level|brief\s+description\s+of\s+changes|"
    r"model\s*#|model\s*№|pack(?:age|ge)?\s*ccn|stock\s*dt|"
    r"^model\s*\||^work\s+order\s+number",
    re.I,
)
PRESSURE_FILL = re.compile(r"pressure\s+rating|fill\s+the\s+below\s+table|pulley\s*ccn|as\s+per\s+pressure", re.I)
BELT_TENSION = re.compile(r"belt\s+tension|frequency\s+in\s+hz|press?ure\s*\(\s*bar\s*\)", re.I)
SPOT_AUDIT = re.compile(r"random\s*/?\s*spot\s+audit", re.I)
PROBLEM_LOG = re.compile(r"problem\s+description", re.I)
VIBRATION = re.compile(r"vibration\s+reading|mm\s*/\s*sec|conformance\s+to\s+engg", re.I)
KW_AMP = re.compile(r"^\s*kw\s*$|^\s*amp\s*$", re.I)
BAR_COL = re.compile(r"(\d+(?:\.\d+)?)\s*bar", re.I)
VALUE_BLANK = re.compile(r"_{3,}|\bvalues?\b|લખો|લખવું|reading|hz\b|ltr|liter", re.I)
FILL_LINE = re.compile(r"_{3,}|:{0,1}\s*$")


def default_word_folder() -> Path:
    return Path(settings.BASE_DIR) / "jobcard_word_file"


def _stem_key(name: str) -> str:
    """Normalize a filename stem or catalog key for matching."""
    text = Path(name).stem if "." in Path(name).name and Path(name).suffix.lower() in {".doc", ".docx"} else name
    text = normalize_job_card_key(text)
    text = re.sub(r"\s*\(\d+\)\s*$", "", text).strip()
    return re.sub(r"\s+", " ", text).casefold()


def _iter_word_dirs(folder: Path):
    """Search the folder plus committed/local conversion caches."""
    yield folder
    for name in ("_converted", ".converted"):
        nested = folder / name
        if nested.is_dir():
            yield nested


def find_word_file(folder: Path, job_card_key: str) -> Path | None:
    wanted = _stem_key(job_card_key)
    if not wanted or not folder.is_dir():
        return None
    candidates = []
    for search in _iter_word_dirs(folder):
        for path in search.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".doc", ".docx"}:
                continue
            if path.name.startswith("~"):
                continue
            if _stem_key(path.name) == wanted:
                candidates.append(path)
    if not candidates:
        return None
    # Prefer .docx (works on Linux/PythonAnywhere) over legacy .doc.
    candidates.sort(
        key=lambda p: (
            0 if p.suffix.lower() == ".docx" else 1,
            0 if p.parent.name in {"_converted", ".converted"} else 1,
            len(p.name),
            p.name.lower(),
        )
    )
    return candidates[0]


def _convert_doc_to_docx(src: Path, dest: Path) -> Path:
    """Convert legacy .doc → .docx via Microsoft Word (Windows)."""
    try:
        import win32com.client  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Reading .doc files needs Microsoft Word and pywin32. "
            "Install pywin32, or save the job card as .docx in jobcard_word_file/."
        ) from exc

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime and dest.stat().st_size > 0:
        return dest

    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        document = word.Documents.Open(str(src.resolve()))
        try:
            # 16 = wdFormatXMLDocument (.docx)
            document.SaveAs2(str(dest.resolve()), FileFormat=16)
        finally:
            document.Close(False)
    finally:
        word.Quit()
    return dest


def _find_cached_docx(path: Path, folders: list[Path | None]) -> Path | None:
    """Match converted .docx by stem, ignoring trailing (1) copy suffixes."""
    wanted = _stem_key(path.stem)
    for folder in folders:
        if not folder:
            continue
        folder = Path(folder)
        if not folder.is_dir():
            continue
        exact = folder / f"{path.stem}.docx"
        if exact.exists() and exact.stat().st_size > 0:
            return exact
        clean = re.sub(r"\s*\(\d+\)\s*$", "", path.stem).strip()
        if clean and clean != path.stem:
            cleaned = folder / f"{clean}.docx"
            if cleaned.exists() and cleaned.stat().st_size > 0:
                return cleaned
        for candidate in folder.glob("*.docx"):
            if _stem_key(candidate.stem) == wanted and candidate.stat().st_size > 0:
                return candidate
    return None


def ensure_docx(path: Path, cache_dir: Path | None = None) -> Path:
    path = Path(path)
    if path.suffix.lower() == ".docx":
        return path
    if path.suffix.lower() != ".doc":
        raise RuntimeError(f"Unsupported Word file type: {path.suffix}")
    # Prefer already-converted .docx (needed on Linux / PythonAnywhere — no Word COM).
    root = path.parent if path.parent.name not in {"_converted", ".converted"} else path.parent.parent
    cached = _find_cached_docx(
        path,
        [
            cache_dir,
            root / "_converted",
            root / ".converted",
            path.parent,
        ],
    )
    if cached is not None:
        return cached
    cache = Path(cache_dir) if cache_dir else (root / "_converted")
    clean_stem = re.sub(r"\s*\(\d+\)\s*$", "", path.stem).strip() or path.stem
    return _convert_doc_to_docx(path, cache / f"{clean_stem}.docx")


def _unique_cells(row) -> list[str]:
    values = []
    for cell in row.cells:
        text = (cell.text or "").replace("\r", "\n").replace("\xa0", " ").strip()
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n+", " / ", text).strip(" /")
        if not values or values[-1] != text:
            values.append(text)
    return [value for value in values if value]


def _table_heading(table) -> str:
    if not table.rows:
        return ""
    return " | ".join(_unique_cells(table.rows[0]))


def _is_parts_table(table) -> bool:
    if len(table.rows) < 2:
        return False
    heading = _table_heading(table)
    if PROBLEM_LOG.search(heading) or re.search(r"revision\s+level", heading, re.I):
        return False
    if PARTS_HEADER.search(heading):
        return True
    # English Nirvana cards: Description / CCN / Make /Brand / Serial No./Batch Code
    probe = " | ".join(_unique_cells(table.rows[0]) + _unique_cells(table.rows[1])).lower()
    if "revision" in probe or "brief description of changes" in probe:
        return False
    has_description = "description" in probe
    has_part = any(token in probe for token in ("part no", "part number", "part/ccn", "part no."))
    has_ccn = bool(re.search(r"\bccn\b", probe)) and "package" not in probe
    has_serial = bool(re.search(r"\bsr\.?\b|serial|batch", probe))
    has_make = "make" in probe or "brand" in probe
    return has_description and (has_part or has_ccn or has_serial or has_make)


def _is_kw_amp_table(table) -> bool:
    if len(table.rows) != 1:
        return False
    cells = [cell.strip().upper() for cell in _unique_cells(table.rows[0])]
    return "KW" in cells and "AMP" in cells


def _is_vibration_table(table) -> bool:
    probe = " | ".join(_unique_cells(table.rows[0])).lower() if table.rows else ""
    if "position" in probe and ("load" in probe or "unload" in probe):
        return True
    if len(table.rows) > 1:
        body = " | ".join(_unique_cells(table.rows[1])).lower()
        if "axial" in body or "vertical" in body or "horizontal" in body:
            return True
    return bool(VIBRATION.search(probe))


def _iter_nested_tables(table):
    """Yield nested Word tables inside cells (vibration / coolant grids)."""
    seen = set()
    for row in table.rows:
        for cell in row.cells:
            for nested in getattr(cell, "tables", []) or []:
                marker = id(nested._tbl)
                if marker in seen:
                    continue
                seen.add(marker)
                yield nested


def _parse_parts_table(table, assembly_fields, used):
    """Major parts grid: Description + CCN / Make / Serial columns when present."""
    section = "Major parts details"
    header_cells = _unique_cells(table.rows[0])
    header_l = [cell.casefold() for cell in header_cells]
    # Simple L03-style list (# / Description / Part No / Sr. No.) → one text per part.
    simple_list = (
        any("#" == cell or cell.startswith("sr") for cell in header_l)
        and not any("make" in cell or "brand" in cell or "batch" in cell for cell in header_l)
        and not (len(header_cells) >= 3 and any("ccn" == cell or cell.endswith("ccn") for cell in header_l))
    )
    # Detect column roles from the header row.
    columns = []
    for cell in header_cells:
        low = cell.casefold().strip()
        if low in {"#", "no.", "no"} or re.fullmatch(r"#+", low):
            columns.append(None)
        elif "description" in low:
            columns.append("name")
        elif "ccn" in low or "part no" in low or "part number" in low:
            columns.append("CCN")
        elif "make" in low or "brand" in low:
            columns.append("Make / Brand")
        elif "serial" in low or "batch" in low or re.match(r"sr\.?\s*no", low):
            columns.append("Serial No. / Batch Code")
        else:
            columns.append(cell.strip() or None)

    if simple_list or ("name" not in columns and len([c for c in columns if c]) <= 1):
        for row in table.rows:
            cells = _unique_cells(row)
            if not cells:
                continue
            joined = " | ".join(cells).lower()
            if PARTS_HEADER.search(joined):
                continue
            if cells[0].strip().lower() in {"#", "sr.", "sr. no.", "sr. no", "no.", "description"}:
                continue
            if "description" in joined and ("part" in joined or "ccn" in joined):
                continue
            description = ""
            if len(cells) >= 2 and re.match(r"^\d+[a-zA-Z]?$", cells[0].strip()):
                description = cells[1]
            elif not re.match(r"^\d+[a-zA-Z]?$", cells[0].strip()):
                description = cells[0]
            description = description.strip()
            if description:
                assembly_fields.append(_short("part", description, "Assembly parts", used))
        return

    value_cols = [col for col in columns if col and col != "name"]
    if not value_cols:
        value_cols = ["CCN", "Make / Brand", "Serial No. / Batch Code"]
        columns = ["name"] + value_cols

    for row in table.rows[1:]:
        raw_cells = []
        for cell in row.cells:
            text = (cell.text or "").replace("\r", "\n").replace("\xa0", " ").strip()
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n+", " / ", text).strip(" /")
            if not raw_cells or raw_cells[-1] != text:
                raw_cells.append(text)
        if not raw_cells:
            continue
        # Align with header width when Word merges empty cells.
        while len(raw_cells) < len(columns):
            raw_cells.append("")
        name = ""
        values = {}
        for index, role in enumerate(columns):
            if role is None or index >= len(raw_cells):
                continue
            value = raw_cells[index].strip()
            if role == "name":
                name = value
            else:
                values[role] = value
        if not name or name.casefold() in {"description", "ccn"}:
            continue
        if PARTS_HEADER.search(name):
            continue
        for col in value_cols:
            assembly_fields.append(
                _field_tuple(
                    _field_key("part", f"{name}_{col}", used),
                    section,
                    f"{name} — {col}",
                    required=False,
                    extra=f"parts|{name}|{col}",
                )
            )


def _parse_kw_amp_table(table, assembly_fields, used):
    section = "Ultra Coolant Oil"
    for label in ("KW", "AMP"):
        assembly_fields.append(
            _field_tuple(
                _field_key("oil", f"ultra_coolant_{label.lower()}", used),
                section,
                label,
                required=False,
                unit=label,
            )
        )


def _parse_vibration_table(table, testing_fields, used, section="Vibration readings"):
    headers = _unique_cells(table.rows[0]) if table.rows else []
    header_l = [cell.casefold() for cell in headers]
    col_roles = []
    for cell in header_l:
        if "position" in cell:
            col_roles.append("name")
        elif "unload" in cell:
            col_roles.append("Unload (mm/sec)")
        elif "load" in cell:
            col_roles.append("Load (mm/sec)")
        else:
            col_roles.append(cell.strip() or "Value")
    if "name" not in col_roles:
        col_roles = ["name", "Load (mm/sec)", "Unload (mm/sec)"]
    value_cols = [col for col in col_roles if col != "name"]
    start = 1
    if table.rows and "position" not in header_l[0]:
        start = 0
    for row in table.rows[start:]:
        cells = _unique_cells(row)
        if not cells:
            continue
        name = cells[0].strip()
        if not name or name.casefold() in {"position", "load", "unload"}:
            continue
        if VIBRATION.search(name):
            continue
        for index, col in enumerate(value_cols, start=1):
            testing_fields.append(
                _field_tuple(
                    _field_key("vib", f"{name}_{col}", used),
                    section,
                    f"{name} — {col}",
                    required=False,
                    unit="mm/sec",
                    extra=f"vib|{name}|{col}",
                )
            )


def _is_skip_table(heading: str) -> bool:
    if BEFORE_HEADER.search(heading) or DURING_HEADER.search(heading) or AFTER_HEADER.search(heading):
        return False
    if AUDIT_HEADER.search(heading) or SPOT_AUDIT.search(heading):
        return False
    if PRESSURE_FILL.search(heading) or BELT_TENSION.search(heading):
        return False
    if SIGN_DATE.search(heading):
        return False
    if PARTS_HEADER.search(heading):
        return False
    if PROBLEM_LOG.search(heading):
        return True
    return bool(SKIP_TABLE.search(heading))


def _matrix_bar_columns(table) -> list[str]:
    """Return unique BAR labels found in header rows (7 Bar, 10 Bar, 13 Bar…)."""
    found = []
    for row in table.rows[:3]:
        for cell in _unique_cells(row):
            match = BAR_COL.search(cell)
            if not match:
                continue
            label = f"{match.group(1)} Bar"
            if label not in found:
                found.append(label)
    return found


def _field_tuple(key, section, label, field_type="short_text", required=False, unit="", extra=""):
    return (key, section, label, field_type, required, unit, extra)


def _has_section(fields, section: str) -> bool:
    return any(item[1] == section for item in fields)


def _add_pressure_rating_fields(
    assembly_fields,
    used,
    bars: list[str] | None = None,
    rows: list[str] | None = None,
):
    """Fillable CCN table: Belt / pulleys by pressure — matches shop Word job cards."""
    if _has_section(assembly_fields, "Fill as per pressure rating"):
        return
    bars = bars or ["7 Bar", "10 Bar", "13 Bar"]
    rows = rows or [
        "Belt",
        "Air end side Pulley",
        "Motor side Pulley",
    ]
    section = "Fill as per pressure rating"
    for row in rows:
        if re.search(r"checked\s+by|team\s+leader", row, re.I):
            continue
        for bar in bars:
            key = _field_key("press", f"{row}_{bar}", used)
            assembly_fields.append(
                _field_tuple(key, section, f"{row} — {bar} (CCN)", required=False, extra=f"press|{row}|{bar}")
            )
    assembly_fields.append(
        _field_tuple(
            _field_key("press", "checked_by_team_leader", used),
            section,
            "Checked by Team Leader",
            required=True,
            extra="press|leader|",
        )
    )


def _belt_reference_text(table) -> str:
    """Human-readable belt-tension chart copied from the Word table."""
    lines = []
    for row in table.rows:
        cells = _unique_cells(row)
        if not cells:
            continue
        if BELT_TENSION.search(cells[0]) and len(cells) <= 2:
            lines.append(cells[0])
            continue
        lines.append(" · ".join(cells))
    return "\n".join(lines)


def _parse_belt_tension_table(table, assembly_fields, used):
    """Keep belt-tension reference visible and capture actual Hz reading."""
    section = "Belt tension reference"
    bars = _matrix_bar_columns(table)
    chart = re.sub(r"\s+", " ", _belt_reference_text(table)).strip()
    assembly_fields.append(
        _field_tuple(
            _field_key("belt", "chart_note", used),
            section,
            "Belt tension chart (from Word job card)",
            field_type="short_text",
            required=False,
            extra=f"belt_chart|{chart}",
        )
    )
    assembly_fields.append(
        _field_tuple(
            _field_key("belt", "actual_belt_tension_hz", used),
            section,
            "Actual belt tension value written on card",
            required=False,
            unit="Hz",
        )
    )
    return bars


def _parse_pressure_fill_table(table, assembly_fields, used):
    section = "Fill as per pressure rating"
    if _has_section(assembly_fields, section):
        return
    bars = _matrix_bar_columns(table) or ["7 Bar", "10 Bar", "13 Bar"]
    row_labels = []
    for row in table.rows[1:]:
        cells = _unique_cells(row)
        if not cells:
            continue
        label = cells[0].strip()
        if not label or BAR_COL.search(label) or label.lower() in {"ccn", "description"}:
            continue
        if PRESSURE_FILL.search(label):
            continue
        row_labels.append(label)
    if not row_labels:
        _add_pressure_rating_fields(assembly_fields, used, bars)
        return
    fill_rows = [label for label in row_labels if not re.search(r"checked\s+by|team\s+leader", label, re.I)]
    _add_pressure_rating_fields(assembly_fields, used, bars, fill_rows or None)


def _parse_spot_audit_table(table, testing_fields, used):
    section = "Spot audit"
    for index, row in enumerate(table.rows):
        cells = _unique_cells(row)
        if not cells:
            continue
        joined = " | ".join(cells)
        if index == 0 or SPOT_AUDIT.search(joined):
            continue
        if "type of check" in joined.lower() and "checked by" in joined.lower():
            continue
        label = cells[0].strip()
        if not label:
            continue
        testing_fields.append(
            _as_yes_no_or_text("spot", str(index), section, label, used)
        )


def _checklist_label(cells: list[str]) -> str:
    """Pick the instruction text from a Sign/Date checklist row."""
    if not cells:
        return ""
    label = cells[0].strip()
    if SIGN_DATE.fullmatch(label) or label.lower() in {"sign/date", "name/sign"}:
        return ""
    return label


def _as_yes_no_or_text(prefix: str, number: str, section: str, label: str, used: set):
    if VALUE_BLANK.search(label) or "______" in label or "----" in label:
        clean = re.sub(r"_{3,}", "…", label).strip()
        return _short(prefix, f"{number}_{clean}" if number else clean, section, used)
    return _yes_no(prefix, number, section, label, used)


def parse_word_document(docx_path: Path, checklist_key: str):
    """Return Assembly/Testing field lists from one Word job card (.docx)."""
    from docx import Document

    document = Document(str(docx_path))
    key = normalize_job_card_key(checklist_key)
    assembly_fields = []
    testing_fields = []
    used = set()
    asm_number = 0
    aud_number = 0
    test_number = 0
    pressure_bars = None
    found_pressure_or_belt = False

    for table in document.tables:
        heading = _table_heading(table)
        if not heading:
            continue
        joined_probe = " | ".join(
            cell for row in table.rows[:3] for cell in _unique_cells(row)
        )

        if _is_kw_amp_table(table):
            _parse_kw_amp_table(table, assembly_fields, used)
            continue

        if _is_vibration_table(table):
            _parse_vibration_table(table, testing_fields, used)
            continue

        if _is_skip_table(heading) and not (
            PRESSURE_FILL.search(heading)
            or BELT_TENSION.search(heading)
            or SPOT_AUDIT.search(heading)
            or AUDIT_HEADER.search(heading)
            or BEFORE_HEADER.search(heading)
            or DURING_HEADER.search(heading)
            or AFTER_HEADER.search(heading)
            or PARTS_HEADER.search(heading)
            or _is_parts_table(table)
        ):
            continue

        if _is_parts_table(table):
            _parse_parts_table(table, assembly_fields, used)
            continue

        if PRESSURE_FILL.search(heading) or PRESSURE_FILL.search(joined_probe):
            found_pressure_or_belt = True
            _parse_pressure_fill_table(table, assembly_fields, used)
            continue

        if BELT_TENSION.search(heading) or BELT_TENSION.search(joined_probe):
            found_pressure_or_belt = True
            bars = _parse_belt_tension_table(table, assembly_fields, used)
            if bars:
                pressure_bars = bars
            continue

        if SPOT_AUDIT.search(heading):
            _parse_spot_audit_table(table, testing_fields, used)
            continue

        if _is_skip_table(heading):
            continue

        if AUDIT_HEADER.search(heading):
            for row in table.rows[1:]:
                label = _checklist_label(_unique_cells(row))
                if not label:
                    continue
                aud_number += 1
                assembly_fields.append(_yes_no("aud", str(aud_number), "Final audit", label, used))
            continue

        test_section = None
        if BEFORE_HEADER.search(heading):
            test_section = "Before testing"
            prefix = "bef"
        elif DURING_HEADER.search(heading):
            test_section = "During testing"
            prefix = "dur"
        elif AFTER_HEADER.search(heading):
            test_section = "After testing"
            prefix = "aft"

        if test_section:
            pending_vib = []
            already_vib = any((f[6] or "").startswith("vib|") for f in testing_fields)
            if not already_vib:
                for nested in _iter_nested_tables(table):
                    if _is_vibration_table(nested):
                        _parse_vibration_table(nested, pending_vib, used, section=test_section)
            for row in table.rows[1:]:
                cells = _unique_cells(row)
                label = _checklist_label(cells)
                if not label:
                    continue
                # Place the Word vibration grid where the placeholder row sits.
                if VIBRATION.search(label) and pending_vib:
                    testing_fields.extend(pending_vib)
                    pending_vib = []
                    continue
                if VIBRATION.search(label) and any((f[6] or "").startswith("vib|") for f in testing_fields):
                    continue
                test_number += 1
                testing_fields.append(
                    _as_yes_no_or_text(prefix, str(test_number), test_section, label, used)
                )
            testing_fields.extend(pending_vib)
            continue

        # Assembly section tables (Gujarati/English), usually with Sign/Date column.
        heading_l = heading.lower()
        if (
            SIGN_DATE.search(heading)
            or "એસેમ્બલી" in heading
            or "assembly" in heading_l
            or "canopy" in heading_l
            or "starter" in heading_l
            or "cooler" in heading_l
            or "motor" in heading_l
            or "separator" in heading_l
            or "cooling" in heading_l
        ):
            section_title = heading.split("|")[0].strip() or "Assembly checklist"
            # Keep section names distinct so later Word blocks do not merge into earlier ones.
            if len(section_title) > 72:
                lowered = section_title.casefold()
                if "starter" in lowered or "સ્ટાર્ટર" in section_title or "કંટ્રોલ" in section_title:
                    section_title = "Starter / control panel assembly"
                elif "cooler" in lowered or "કુલર" in section_title or "કેનોપી" in section_title or "canopy" in lowered:
                    section_title = "Cooler / sep tank / canopy assembly"
                elif "મોટર" in section_title or "motor" in lowered:
                    section_title = "Motor and air-end assembly"
                elif "એર એન્ડ" in section_title or "air end" in lowered:
                    section_title = "Air end assembly"
                else:
                    section_title = section_title[:72].rstrip(" /-,")
            for index, row in enumerate(table.rows):
                cells = _unique_cells(row)
                if not cells:
                    continue
                if index == 0 and SIGN_DATE.search(" | ".join(cells)):
                    # Header only — skip unless there is a real checklist line besides Sign/Date.
                    label = cells[0]
                    if SIGN_DATE.search(label) and len(cells) <= 2:
                        continue
                label = _checklist_label(cells)
                if not label or SIGN_DATE.fullmatch(label):
                    continue
                if index == 0 and (
                    "એસેમ્બલી" in label
                    or "assembly" in label.lower()
                    or "canopy" in label.lower()
                    or "starter" in label.lower()
                    or "cooler" in label.lower()
                    or "motor" in label.lower()
                    or "separator" in label.lower()
                    or "cooling" in label.lower()
                ):
                    # Section title row, not a check item.
                    if len(label) > 24:
                        continue
                asm_number += 1
                assembly_fields.append(
                    _as_yes_no_or_text("asm", str(asm_number), section_title, label, used)
                )
            continue

    # Belt-drive Word cards show a pressure CCN matrix; inject only when that chart exists.
    if found_pressure_or_belt and not _has_section(assembly_fields, "Fill as per pressure rating"):
        insert_at = 0
        seen_parts = False
        for index, field in enumerate(assembly_fields):
            if field[1] in {"Assembly parts", "Major parts details"}:
                seen_parts = True
                insert_at = index + 1
            elif seen_parts:
                break
        injected = []
        bars = list(pressure_bars or [])
        for bar in ("7 Bar", "10 Bar", "13 Bar"):
            if bar not in bars:
                bars.append(bar)
        _add_pressure_rating_fields(injected, used, bars)
        assembly_fields[insert_at:insert_at] = injected

    # Standard sign-off / result fields (same pattern as Excel imports).
    assembly_fields.append(_short("sign", "Assembled by", "Assembly sign off", used))
    testing_fields.append(_short("test", "Tested by", "Testing sign off", used))
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
    testing_fields.append(
        (_field_key("test", "report_problem", used), "If not OK", "If not OK — report problem", "short_text", False, "", "")
    )

    return {
        "checklist_key": key,
        "source": str(docx_path),
        PhaseCode.ASSEMBLY: assembly_fields,
        PhaseCode.TESTING: testing_fields,
    }


def import_word_job_cards(folder: Path | None = None, keys: list[str] | None = None):
    """Import Assembly/Testing templates for Word-backed catalog keys.

    Matches each Job Card Detail name to a file in ``jobcard_word_file``
    (filename stem, ignoring trailing ``(1)`` and extension).
    """
    folder = Path(folder) if folder else default_word_folder()
    if not folder.is_dir():
        raise FileNotFoundError(f"Word job card folder not found: {folder}")

    if keys is None:
        from machines.models import PlanningCatalogItem

        keys = list(
            PlanningCatalogItem.objects.filter(job_card_format="word")
            .exclude(job_card_key="")
            .order_by("job_card_key")
            .values_list("job_card_key", flat=True)
            .distinct()
        )
        if not keys:
            # Fallback: import every file that looks like a job card name.
            keys = [
                re.sub(r"\s*\(\d+\)\s*$", "", normalize_job_card_key(path.stem)).strip()
                for path in folder.iterdir()
                if path.is_file() and path.suffix.lower() in {".doc", ".docx"} and not path.name.startswith("~")
            ]

    created = 0
    updated = 0
    empty = 0
    missing = []
    details = []

    with transaction.atomic():
        for raw_key in keys:
            key = normalize_job_card_key(raw_key)
            if not key:
                continue
            source = find_word_file(folder, key)
            if source is None:
                missing.append(key)
                details.append({"key": key, "status": "missing_file"})
                continue
            try:
                docx_path = ensure_docx(source, folder / "_converted")
                parsed = parse_word_document(docx_path, key)
            except Exception as exc:
                details.append({"key": key, "status": "error", "error": str(exc), "file": source.name})
                continue

            for phase_code, title in (
                (PhaseCode.ASSEMBLY, f"Assembly · {key}"),
                (PhaseCode.TESTING, f"Testing · {key}"),
            ):
                fields = parsed[phase_code]
                if not fields:
                    empty += 1
                    details.append({"key": key, "phase": phase_code, "status": "empty", "file": source.name})
                    continue
                before = JobCardTemplate.objects.filter(
                    phase_code=phase_code, checklist_key=key, is_active=True
                ).exists()
                template = upsert_phase_template(
                    phase_code,
                    key,
                    title,
                    fields,
                    description=f"Imported from Word job card {source.name}",
                )
                if template is None:
                    empty += 1
                    details.append({"key": key, "phase": phase_code, "status": "empty", "file": source.name})
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
                    details.append(
                        {
                            "key": key,
                            "phase": phase_code,
                            "status": "updated",
                            "fields": len(fields),
                            "file": source.name,
                        }
                    )
                else:
                    created += 1
                    details.append(
                        {
                            "key": key,
                            "phase": phase_code,
                            "status": "created",
                            "fields": len(fields),
                            "file": source.name,
                        }
                    )

    return {
        "created": created,
        "updated": updated,
        "empty": empty,
        "missing": missing,
        "keys": len(keys),
        "details": details,
    }
