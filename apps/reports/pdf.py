import io
import os
import re
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
_LATIN_REGULAR = os.path.join(_FONT_DIR, "NotoSans-Regular.ttf")
_LATIN_BOLD = os.path.join(_FONT_DIR, "NotoSans-Bold.ttf")
_GUJ_REGULAR = os.path.join(_FONT_DIR, "NotoSansGujarati-Regular.ttf")
_GUJ_BOLD = os.path.join(_FONT_DIR, "NotoSansGujarati-Bold.ttf")

# Noto Sans Gujarati has no Latin letters, so English used to disappear in the PDF.
# Use Noto Sans for Latin and Noto Sans Gujarati only for Gujarati script.
_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_FONT_GUJ = _FONT
_FONT_GUJ_BOLD = _FONT_BOLD
if os.path.exists(_LATIN_REGULAR):
    pdfmetrics.registerFont(TTFont("JobCard", _LATIN_REGULAR))
    pdfmetrics.registerFont(TTFont("JobCard-Bold", _LATIN_BOLD if os.path.exists(_LATIN_BOLD) else _LATIN_REGULAR))
    _FONT = "JobCard"
    _FONT_BOLD = "JobCard-Bold"
if os.path.exists(_GUJ_REGULAR):
    pdfmetrics.registerFont(TTFont("JobCardGuj", _GUJ_REGULAR))
    pdfmetrics.registerFont(TTFont("JobCardGuj-Bold", _GUJ_BOLD if os.path.exists(_GUJ_BOLD) else _GUJ_REGULAR))
    _FONT_GUJ = "JobCardGuj"
    _FONT_GUJ_BOLD = "JobCardGuj-Bold"

_GUJARATI_RE = re.compile(r"[\u0A80-\u0AFF]+")


NAVY = colors.HexColor("#0B1D36")
RED = colors.HexColor("#E10600")
LINE = colors.HexColor("#CBD5E1")
ZEBRA = colors.HexColor("#F8FAFC")
CREAM = colors.HexColor("#FFF4CC")
GOLD = colors.HexColor("#FFE14A")
GREEN = colors.HexColor("#047857")
GREEN_BG = colors.HexColor("#D1FAE5")
RED_TEXT = colors.HexColor("#B91C1C")
RED_BG = colors.HexColor("#FEE2E2")
INK = colors.HexColor("#142033")
CONTENT_WIDTH = A4[0] - 56

PHASE_LAYOUT = (
    ("ASSEMBLY", "Assembly", colors.HexColor("#1D4ED8"), colors.HexColor("#DBEAFE")),
    ("ELECTRICAL", "Electrical", colors.HexColor("#B45309"), colors.HexColor("#FEF3C7")),
    ("TESTING", "Testing", colors.HexColor("#047857"), colors.HexColor("#D1FAE5")),
    ("EOL", "End of line", colors.HexColor("#6D28D9"), colors.HexColor("#EDE9FE")),
    ("QC", "Quality control", colors.HexColor("#E10600"), colors.HexColor("#FEE2E2")),
)
GRID_SECTIONS = {
    "assembly parts",
    "assembly sign off",
    "testing sign off",
    "end of line",
    "general check",
}


def _rich(value, bold=False):
    """Escape text and wrap Gujarati runs in the Gujarati font so English stays visible."""
    shown = "—" if value in (None, "") else str(value)
    latin = _FONT_BOLD if bold else _FONT
    guj = _FONT_GUJ_BOLD if bold else _FONT_GUJ
    parts = []
    cursor = 0
    for match in _GUJARATI_RE.finditer(shown):
        if match.start() > cursor:
            parts.append(f'<font name="{latin}">{escape(shown[cursor:match.start()])}</font>')
        parts.append(f'<font name="{guj}">{escape(match.group(0))}</font>')
        cursor = match.end()
    if cursor < len(shown):
        parts.append(f'<font name="{latin}">{escape(shown[cursor:])}</font>')
    return "".join(parts) or f'<font name="{latin}">—</font>'


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="IRTitle", fontName=_FONT_BOLD, fontSize=16, textColor=NAVY, spaceAfter=4))
    styles.add(ParagraphStyle(name="IRSub", fontName=_FONT, fontSize=9, textColor=colors.HexColor("#475569"), spaceAfter=10))
    styles.add(ParagraphStyle(name="IRHead", fontName=_FONT_BOLD, fontSize=11, textColor=NAVY, spaceBefore=10, spaceAfter=4))
    styles.add(ParagraphStyle(name="IRCell", fontName=_FONT, fontSize=8, leading=11, textColor=colors.HexColor("#0F172A")))
    return styles


def _paragraphs(headers, rows, style):
    header = [Paragraph(_rich(item, bold=True), style) for item in headers]
    body = [[Paragraph(_rich(str(item if item not in (None, "") else "—")[:500]), style) for item in row] for row in rows]
    return [header] + body


def table_pdf(title, subtitle, headers, rows):
    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=landscape(A4), title=title, leftMargin=24, rightMargin=24, topMargin=28, bottomMargin=28)
    styles = _styles()
    data = _paragraphs(headers, rows or [["No records"]], styles["IRCell"])
    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
                ("GRID", (0, 0), (-1, -1), 0.3, LINE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    document.build(
        [
            Paragraph(_rich("Ingersoll Rand · ROTARY"), styles["IRSub"]),
            Paragraph(_rich(title, bold=True), styles["IRTitle"]),
            Paragraph(_rich(subtitle), styles["IRSub"]),
            table,
        ]
    )
    buffer.seek(0)
    return buffer


def _card_styles():
    styles = _styles()
    styles.add(ParagraphStyle(name="CardWhite", fontName=_FONT_BOLD, fontSize=11, leading=14, textColor=colors.white))
    styles.add(ParagraphStyle(name="CardWhiteSmall", fontName=_FONT, fontSize=8, leading=10, textColor=colors.white, alignment=2))
    styles.add(ParagraphStyle(name="CardAddress", fontName=_FONT, fontSize=8, leading=11, textColor=NAVY))
    styles.add(ParagraphStyle(name="CardLabel", fontName=_FONT_BOLD, fontSize=8, leading=10, textColor=NAVY))
    styles.add(ParagraphStyle(name="CardValue", fontName=_FONT, fontSize=9, leading=12, textColor=INK))
    styles.add(ParagraphStyle(name="CardQuestion", fontName=_FONT, fontSize=10, leading=14, textColor=INK))
    styles.add(ParagraphStyle(name="CardValueStrong", fontName=_FONT_BOLD, fontSize=9, leading=12, textColor=INK))
    styles.add(ParagraphStyle(name="CardYes", fontName=_FONT_BOLD, fontSize=9, leading=12, textColor=GREEN, alignment=1))
    styles.add(ParagraphStyle(name="CardNo", fontName=_FONT_BOLD, fontSize=9, leading=12, textColor=RED_TEXT, alignment=1))
    styles.add(ParagraphStyle(name="CardMuted", fontName=_FONT, fontSize=8, leading=11, textColor=colors.HexColor("#64748B")))
    styles.add(ParagraphStyle(name="CardTitleRight", fontName=_FONT_BOLD, fontSize=13, leading=16, textColor=NAVY, alignment=2))
    styles.add(ParagraphStyle(name="CardRight", fontName=_FONT_BOLD, fontSize=8, leading=10, textColor=NAVY, alignment=2))
    styles.add(ParagraphStyle(name="CardBadge", fontName=_FONT_BOLD, fontSize=8, leading=10, textColor=NAVY, alignment=1))
    styles.add(ParagraphStyle(name="CardChip", fontName=_FONT_BOLD, fontSize=7, leading=9, textColor=colors.white, alignment=1))
    return styles


def _text(value, style):
    bold = "Bold" in (getattr(style, "fontName", "") or "")
    return Paragraph(_rich(value, bold=bold), style)


def _widths(*ratios):
    raw = [CONTENT_WIDTH * ratio / sum(ratios) for ratio in ratios]
    raw[-1] = CONTENT_WIDTH - sum(raw[:-1])
    return raw


def _paint(table, commands):
    table.setStyle(TableStyle(commands))
    return table


def _logo_file(company=""):
    from machines.brand import brand_file

    path = brand_file(company)
    if path:
        return path
    try:
        from accounts.models import current_logo

        logo = current_logo()
        stored = logo.image.path if logo and logo.image else ""
        if stored and os.path.exists(stored):
            return stored
    except Exception:
        return ""
    return ""


def _logo_mark(styles, company=""):
    path = _logo_file(company)
    if path:
        return Image(path, width=156, height=36, kind="proportional", mask="auto", hAlign="LEFT")
    mark = Table([[Paragraph(_rich("IR", bold=True), styles["CardWhite"])]], colWidths=[46], rowHeights=[46])
    return _paint(
        mark,
        [
            ("BACKGROUND", (0, 0), (-1, -1), RED),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ],
    )


def _banner(left, right, fill, styles, size=11):
    left_style = ParagraphStyle("banner-left", parent=styles["CardWhite"], fontSize=size, leading=size + 3)
    data = [[Paragraph(_rich(left, bold=True), left_style), Paragraph(_rich(right), styles["CardWhiteSmall"])]]
    table = Table(data, colWidths=_widths(62, 38))
    return _paint(
        table,
        [
            ("BACKGROUND", (0, 0), (-1, -1), fill),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ],
    )


def _tone(value):
    if value in {"Yes", "હા", "OK", "Pass"}:
        return GREEN_BG, "CardYes"
    if value in {"No", "ના", "NOT OK", "Fail"}:
        return RED_BG, "CardNo"
    return colors.white, "CardValueStrong"


def _card_items(template, submission=None):
    from workflow.presenters import card_items

    return card_items(template, submission)


def _line(item, styles):
    fill, style_name = _tone(item["value"])
    if item["kind"] in {"long_text", "remarks"}:
        data = [[_text(item["label"], styles["CardLabel"])], [_text(item["value"], styles["CardValue"])]]
        table = Table(data, colWidths=[CONTENT_WIDTH])
        return _paint(
            table,
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF6")),
                ("BACKGROUND", (0, 1), (-1, 1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ],
        )
    gujarati = any("\u0a80" <= char <= "\u0aff" for char in item["label"])
    label_style = styles["CardQuestion"] if gujarati else styles["CardValue"]
    data = [[_text(item["label"], label_style), _text(item["value"], styles[style_name])]]
    table = Table(data, colWidths=_widths(78, 22))
    return _paint(
        table,
        [
            ("BACKGROUND", (0, 0), (0, 0), colors.white),
            ("BACKGROUND", (1, 0), (1, 0), fill),
            ("GRID", (0, 0), (-1, -1), 0.3, LINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ],
    )


def _pairs(items, styles):
    rows = []
    spans = []
    pending = None
    for item in items:
        if item["kind"] in {"long_text", "remarks"}:
            if pending:
                rows.append([_text(pending["label"], styles["CardLabel"]), _text(pending["value"], styles["CardValueStrong"]), "", ""])
                spans.append(len(rows) - 1)
                pending = None
            rows.append([_text(item["label"], styles["CardLabel"]), _text(item["value"], styles["CardValue"]), "", ""])
            spans.append(len(rows) - 1)
            continue
        if pending is None:
            pending = item
            continue
        rows.append(
            [
                _text(pending["label"], styles["CardLabel"]),
                _text(pending["value"], styles["CardValueStrong"]),
                _text(item["label"], styles["CardLabel"]),
                _text(item["value"], styles["CardValueStrong"]),
            ]
        )
        pending = None
    if pending:
        rows.append([_text(pending["label"], styles["CardLabel"]), _text(pending["value"], styles["CardValueStrong"]), "", ""])
        spans.append(len(rows) - 1)
    if not rows:
        return None
    table = Table(rows, colWidths=_widths(24, 26, 24, 26))
    commands = [
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E8EEF6")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#E8EEF6")),
        ("GRID", (0, 0), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for index in spans:
        commands.append(("SPAN", (1, index), (3, index)))
        commands.append(("BACKGROUND", (2, index), (3, index), colors.white))
    return _paint(table, commands)


def _electrical_table(rows, styles):
    header = [
        _text("ચેક વિગત", styles["CardWhite"]),
        _text("મૂલ્ય / નોંધ", styles["CardWhite"]),
        _text("Result", styles["CardWhite"]),
        _text("Remark", styles["CardWhite"]),
    ]
    data = [header]
    tones = []
    for row in rows:
        result = row["result"]
        _fill, style_name = _tone(result["value"])
        data.append(
            [
                _text(result["label"], styles["CardQuestion"]),
                _text(row["value"]["value"], styles["CardValueStrong"]),
                _text(result["value"], styles[style_name]),
                _text(row["remark"]["value"], styles["CardValue"]),
            ]
        )
        tones.append(_fill)
    table = Table(data, colWidths=_widths(46, 18, 14, 22))
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, 1), (0, -1), colors.white),
        ("BACKGROUND", (1, 1), (1, -1), colors.white),
        ("BACKGROUND", (3, 1), (3, -1), colors.white),
    ]
    for index, fill in enumerate(tones, start=1):
        commands.append(("BACKGROUND", (2, index), (2, index), fill))
    return _paint(table, commands)


def _section_flow(items, color, styles):
    flow = []
    grouped = []
    current = None
    bucket = []
    for item in items:
        if item["section"] != current:
            if bucket:
                grouped.append((current, bucket))
            current = item["section"]
            bucket = [item]
        else:
            bucket.append(item)
    if bucket:
        grouped.append((current, bucket))
    from workflow.presenters import electrical_rows

    for name, bucket in grouped:
        flow.append(Spacer(1, 4))
        flow.append(_banner(name, "", color, styles, size=10))
        bundled = electrical_rows(bucket)
        if bundled:
            flow.append(_electrical_table(bundled, styles))
            continue
        grid = name.strip().lower() in GRID_SECTIONS
        if grid:
            table = _pairs(bucket, styles)
            if table:
                flow.append(table)
        else:
            for item in bucket:
                flow.append(_line(item, styles))
    return flow


def _stamp(submission):
    when = timezone.localtime(submission.submitted_at).strftime("%d %b %Y %H:%M") if submission.submitted_at else "Saved"
    who = submission.operator.display_name if submission.operator_id else "—"
    return f"{who}  ·  {when}  ·  cycle {submission.cycle}"


def _header_block(machine, styles):
    planning = machine.planning
    badge = Table([[Paragraph(_rich("ULTRA COOLANT OIL", bold=True), styles["CardBadge"])]], colWidths=[148])
    badge.hAlign = "RIGHT"
    _paint(
        badge,
        [
            ("BACKGROUND", (0, 0), (-1, -1), GOLD),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#E2B400")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ],
    )
    title = [
        Paragraph(_rich("OIL FREE IRN-SEEIRA-DX", bold=True), styles["CardTitleRight"]),
        Spacer(1, 4),
        badge,
        Spacer(1, 4),
        Paragraph(_rich(machine.machine_id, bold=True), styles["CardRight"]),
    ]
    address = Paragraph(
        _rich("Ingersoll Rand (I) Ltd.") + "<br/>"
        + _rich("21-30 GIDC Industrial Estate,") + "<br/>"
        + _rich("Naroda, Ahmedabad- 382330") + "<br/>"
        + _rich("Gujarat, India"),
        styles["CardAddress"],
    )
    header = Table([[_logo_mark(styles, planning.company), address, title]], colWidths=_widths(32, 34, 34))
    _paint(
        header,
        [
            ("BACKGROUND", (0, 0), (-1, -1), CREAM),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LINEBEFORE", (0, 0), (0, 0), 4, RED),
            ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ],
    )
    planning_date = planning.submitted_at or machine.created_at
    date_text = timezone.localtime(planning_date).strftime("%d-%b-%Y") if planning_date else "—"
    inspection = planning.customer_inspection or "—"
    if planning.customer_inspection_date:
        inspection = f"{inspection} · {planning.customer_inspection_date.strftime('%d %b %Y')}"
    identity = [
        [_text("Planning date", styles["CardLabel"]), _text(date_text, styles["CardValueStrong"]), _text("Model", styles["CardLabel"]), _text(planning.model_description, styles["CardValueStrong"])],
        [_text("Machine serial number", styles["CardLabel"]), _text(machine.planner_serial or "—", styles["CardValueStrong"]), _text("Work order number", styles["CardLabel"]), _text(planning.work_order, styles["CardValueStrong"])],
        [_text("CCN", styles["CardLabel"]), _text(planning.ccn or "—", styles["CardValueStrong"]), _text("Brand", styles["CardLabel"]), _text(planning.company, styles["CardValueStrong"])],
        [_text("Type", styles["CardLabel"]), _text(planning.machine_type or "—", styles["CardValueStrong"]), _text("Priority", styles["CardLabel"]), _text(machine.priority_label, styles["CardValueStrong"])],
        [_text("Calibration", styles["CardLabel"]), _text(planning.calibration or "—", styles["CardValueStrong"]), _text("Shift of machine", styles["CardLabel"]), _text(planning.shift or "—", styles["CardValueStrong"])],
        [_text("Test report bar", styles["CardLabel"]), _text(planning.test_report_bar or "—", styles["CardValueStrong"]), _text("Export packing", styles["CardLabel"]), _text(planning.export_packing_required or "—", styles["CardValueStrong"])],
        [_text("Customer inspection", styles["CardLabel"]), _text(inspection, styles["CardValueStrong"]), _text("", styles["CardLabel"]), _text("", styles["CardValueStrong"])],
    ]
    identity_table = Table(identity, colWidths=_widths(22, 28, 22, 28))
    _paint(
        identity_table,
        [
            ("BACKGROUND", (0, 0), (0, -1), GOLD),
            ("BACKGROUND", (2, 0), (2, -1), GOLD),
            ("BACKGROUND", (1, 0), (1, -1), colors.white),
            ("BACKGROUND", (3, 0), (3, -1), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2B400")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ],
    )
    return [header, Spacer(1, 8), identity_table]


def _progress_strip(steps, styles):
    labels = []
    fills = []
    for group in steps or []:
        for phase in group.get("phases", []):
            status = phase.get("status_label") or ""
            if status == "Completed":
                fill = GREEN
            elif status == "In Progress":
                fill = colors.HexColor("#B45309")
            else:
                fill = colors.HexColor("#64748B")
            labels.append(Paragraph(f"{phase['name']}<br/>{escape(status)}", styles["CardChip"]))
            fills.append(fill)
    if not labels:
        return []
    table = Table([labels], colWidths=_widths(*([1] * len(labels))))
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("LINEAFTER", (0, 0), (-2, -1), 2, colors.white),
    ]
    for index, fill in enumerate(fills):
        commands.append(("BACKGROUND", (index, 0), (index, 0), fill))
    return [Spacer(1, 8), _paint(table, commands)]


def _phase_story(phase_code, title, color, tint, submission, earlier, styles):
    from jobcards.services import active_template

    flow = [Spacer(1, 10)]
    template = active_template(phase_code)
    flow.append(_banner(title, _stamp(submission) if submission else "Not submitted", color, styles))
    flow.extend(_section_flow(_card_items(template, submission), color, styles))
    for old in earlier:
        flow.append(Spacer(1, 6))
        flow.append(_banner(f"{title} · earlier record", _stamp(old), colors.HexColor("#334155"), styles, size=9))
        flow.extend(_section_flow(_card_items(old.template, old), colors.HexColor("#334155"), styles))
    return flow


def machine_history_pdf(machine, steps, submissions, events, reworks):
    buffer = io.BytesIO()
    styles = _card_styles()

    def _decorate(canvas, document):
        canvas.saveState()
        canvas.setFillColor(RED)
        canvas.rect(0, A4[1] - 8, A4[0], 8, fill=1, stroke=0)
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, A4[0], 26, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont(_FONT, 8)
        canvas.drawString(28, 10, machine.machine_id)
        canvas.drawRightString(A4[0] - 28, 10, f"Page {document.page}")
        canvas.restoreState()

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title=f"{machine.machine_id} job card",
        leftMargin=28,
        rightMargin=28,
        topMargin=22,
        bottomMargin=38,
    )
    story = _header_block(machine, styles)
    story.extend(_progress_strip(steps, styles))
    from workflow.presenters import station_label

    planning = machine.planning
    entered = planning.submitted_by.display_name if planning.submitted_by_id else "—"
    station = station_label(machine)
    story.append(Spacer(1, 8))
    story.append(_banner("Planning and production", f"Entered by {entered}", NAVY, styles))
    story.append(
        _pairs(
            [
                {"label": "Production serial", "kind": "short_text", "value": machine.production_serial or "—"},
                {"label": "Station", "kind": "short_text", "value": station},
                {"label": "Production remarks", "kind": "long_text", "value": machine.production_remarks or "—"},
                {"label": "Status", "kind": "short_text", "value": machine.status_label},
            ],
            styles,
        )
    )
    grouped = {}
    for submission in submissions:
        grouped.setdefault(submission.phase_code, []).append(submission)
    for code, title, color, tint in PHASE_LAYOUT:
        records = sorted(grouped.get(code, []), key=lambda item: (item.cycle, item.revision, item.pk))
        current = records[-1] if records else None
        earlier = records[:-1]
        story.extend(_phase_story(code, title, color, tint, current, earlier, styles))
    if reworks:
        from workflow.rework_flow import rework_notes_for_report

        story.append(Spacer(1, 10))
        story.append(_banner("Rework", f"{len(reworks)} record(s)", colors.HexColor("#B45309"), styles))
        for block in rework_notes_for_report(machine):
            item = block["rework"]
            story.append(
                _line(
                    {
                        "label": f"{item.rework_code} · from {item.rejected_phase.name} · {item.get_status_display()}",
                        "kind": "long_text",
                        "value": f"Problem: {item.reason}",
                    },
                    styles,
                )
            )
            for note in block["notes"]:
                if note.note_type == "PROBLEM":
                    continue
                who = note.author.display_name if note.author_id else "Operator"
                story.append(
                    _line(
                        {
                            "label": f"Solved · {note.phase_code} · {who}",
                            "kind": "long_text",
                            "value": note.text,
                        },
                        styles,
                    )
                )
    if events:
        story.append(Spacer(1, 8))
        story.append(_text(f"{len(events)} shop-floor events are kept on this machine.", styles["CardMuted"]))
    document.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    buffer.seek(0)
    return buffer


def _plain_table(rows, header=False):
    styles = _styles()
    data = [[Paragraph(_rich(value), styles["IRCell"]) for value in row] for row in rows]
    table = Table(data, hAlign="LEFT")
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, 0), (0, -1), ZEBRA),
    ]
    if header:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
        commands.append(("TEXTCOLOR", (0, 0), (-1, 0), colors.white))
    table.setStyle(TableStyle(commands))
    return table
