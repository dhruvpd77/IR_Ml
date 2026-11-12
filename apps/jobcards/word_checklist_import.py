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

PARTS_HEADER = re.compile(r"list\s+of\s+major\s+parts|મુખ્ય\s+ભાગ", re.I)
AUDIT_HEADER = re.compile(r"final\s+self|sequential\s+audit", re.I)
BEFORE_HEADER = re.compile(r"ટેસ્ટિંગ\s+પહેલાં|before\s+testing", re.I)
DURING_HEADER = re.compile(r"ટેસ્ટિંગ\s+દરમિયાન|during\s+testing", re.I)
AFTER_HEADER = re.compile(r"ટેસ્ટિંગ\s+પછી|after\s+testing", re.I)
SIGN_DATE = re.compile(r"sign\s*/?\s*date|name\s*/?\s*sign", re.I)
SKIP_TABLE = re.compile(
    r"revision\s+history|problem\s+description|random\s*/?\s*spot|belt\s+tension\s+data|"
    r"model\s*#|model\s*№|pack(?:age|ge)?\s*ccn|work\s+order",
    re.I,
)
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


def find_word_file(folder: Path, job_card_key: str) -> Path | None:
    wanted = _stem_key(job_card_key)
    if not wanted or not folder.is_dir():
        return None
    candidates = []
    for path in folder.iterdir():
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
    # Prefer .docx over .doc when both exist.
    candidates.sort(key=lambda p: (0 if p.suffix.lower() == ".docx" else 1, len(p.name), p.name.lower()))
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


def ensure_docx(path: Path, cache_dir: Path | None = None) -> Path:
    path = Path(path)
    if path.suffix.lower() == ".docx":
        return path
    if path.suffix.lower() != ".doc":
        raise RuntimeError(f"Unsupported Word file type: {path.suffix}")
    # Prefer already-converted .docx (needed on Linux / PythonAnywhere — no Word COM).
    for folder in (
        cache_dir,
        path.parent / "_converted",
        path.parent / ".converted",
    ):
        if not folder:
            continue
        cached = Path(folder) / f"{path.stem}.docx"
        if cached.exists() and cached.stat().st_size > 0:
            return cached
    cache = Path(cache_dir) if cache_dir else (path.parent / "_converted")
    return _convert_doc_to_docx(path, cache / f"{path.stem}.docx")


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
    if PARTS_HEADER.search(heading):
        return True
    # Some English cards use a plain "Description / Part No / Sr. No" header row.
    probe = " | ".join(_unique_cells(table.rows[0]) + _unique_cells(table.rows[1])).lower()
    has_description = "description" in probe
    has_part = "part" in probe or "ccn" in probe
    has_sr = "sr" in probe or "#" in probe
    return has_description and (has_part or has_sr)


def _is_skip_table(heading: str) -> bool:
    if BEFORE_HEADER.search(heading) or DURING_HEADER.search(heading) or AFTER_HEADER.search(heading):
        return False
    if AUDIT_HEADER.search(heading):
        return False
    if SIGN_DATE.search(heading):
        return False
    if PARTS_HEADER.search(heading):
        return False
    return bool(SKIP_TABLE.search(heading))


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

    for table in document.tables:
        heading = _table_heading(table)
        if not heading:
            continue
        if _is_parts_table(table):
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
            for row in table.rows[1:]:
                label = _checklist_label(_unique_cells(row))
                if not label:
                    continue
                test_number += 1
                testing_fields.append(
                    _as_yes_no_or_text(prefix, str(test_number), test_section, label, used)
                )
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
            section_title = heading.split("|")[0].strip()
            if len(section_title) > 80:
                section_title = "Assembly checklist"
            else:
                section_title = section_title or "Assembly checklist"
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
                docx_path = ensure_docx(source, folder / ".converted")
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
