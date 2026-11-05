import pandas as pd

from core.constants import FieldType

STRUCTURED = {"field label", "field type"}
YES = {"yes", "true", "1", "y", "required"}


def parse_template_workbook(uploaded):
    frame = pd.read_excel(uploaded, dtype=str).dropna(how="all")
    frame.columns = [str(column).strip() for column in frame.columns]
    lookup = {column.strip().lower(): column for column in frame.columns}
    if STRUCTURED.issubset(lookup):
        return _structured(frame, lookup)
    labels = [str(column).strip() for column in frame.columns if str(column).strip() and str(column).strip().lower() != "nan"]
    specs = []
    for label in labels:
        specs.append(
            {
                "label": label[:200],
                "field_type": FieldType.SHORT_TEXT,
                "section": "Imported",
                "required": False,
                "unit": "",
                "help_text": "",
                "options": [],
            }
        )
    return specs, []


def _structured(frame, lookup):
    specs = []
    errors = []
    allowed = {value for value, _label in FieldType.CHOICES}
    for index, record in enumerate(frame.to_dict(orient="records"), start=2):
        label = _cell(record, lookup, "field label")
        field_type = _cell(record, lookup, "field type").lower().replace(" ", "_").replace("/", "_")
        aliases = {
            "text": FieldType.SHORT_TEXT,
            "textarea": FieldType.LONG_TEXT,
            "number": FieldType.DECIMAL,
            "passfail": FieldType.PASS_FAIL,
            "yesno": FieldType.YES_NO,
            "photo": FieldType.IMAGE,
            "picture": FieldType.IMAGE,
        }
        field_type = aliases.get(field_type, field_type)
        if not label:
            continue
        if field_type not in allowed:
            errors.append(f"Row {index}: unknown field type '{field_type}'.")
            continue
        options = [part.strip() for part in _cell(record, lookup, "options").replace("|", ",").split(",") if part.strip()]
        specs.append(
            {
                "label": label[:200],
                "field_type": field_type,
                "section": _cell(record, lookup, "section")[:120],
                "required": _cell(record, lookup, "required").lower() in YES,
                "unit": _cell(record, lookup, "unit")[:32],
                "help_text": _cell(record, lookup, "help text")[:240],
                "options": options,
            }
        )
    return specs, errors


def _cell(record, lookup, name):
    column = lookup.get(name)
    if not column:
        return ""
    value = record.get(column)
    if value is None or str(value).strip().lower() == "nan":
        return ""
    return str(value).strip()
