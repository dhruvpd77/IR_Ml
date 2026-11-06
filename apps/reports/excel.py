import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def workbook_bytes(title, headers, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title[:31] or "Report"
    sheet.append(headers)
    for row in rows:
        sheet.append(["" if value is None else value for value in row])
    header_fill = PatternFill("solid", fgColor="0B1D36")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center")
    for index, header in enumerate(headers, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = min(max(len(str(header)) + 4, 14), 36)
    sheet.auto_filter.ref = sheet.dimensions
    sheet.freeze_panes = "A2"
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def machine_workbook(machine, submissions, events, reworks):
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Summary"
    planning = machine.planning
    pairs = [
        ("Machine ID", machine.machine_id),
        ("Status", machine.status_label),
        ("Phase", machine.current_phase),
        ("Priority", machine.priority_label),
        ("Brand", planning.company),
        ("Work Order", planning.work_order),
        ("CCN", planning.ccn),
        ("Model", planning.model_description),
        ("Type", planning.machine_type),
        ("Calibration", planning.calibration),
        ("Shift of machine", planning.shift),
        ("Test report bar", planning.test_report_bar),
        ("Export packing", planning.export_packing_required),
        ("Customer inspection", planning.customer_inspection),
        ("Customer inspection date", planning.customer_inspection_date.isoformat() if planning.customer_inspection_date else ""),
        ("Serial", machine.planner_serial or ""),
        ("Production serial", machine.production_serial or ""),
        ("Station", machine.station.name if machine.station_id else ""),
        ("QC approved at", machine.qc_approved_at.strftime("%d %b %Y %H:%M") if machine.qc_approved_at else ""),
    ]
    for pair in pairs:
        summary.append(list(pair))
    cards = workbook.create_sheet("Job cards")
    cards.append(["Phase", "Cycle", "Revision", "Status", "Field", "Value", "Operator", "Submitted"])
    for submission in submissions:
        for response in submission.responses.all():
            cards.append(
                [
                    submission.phase_code,
                    submission.cycle,
                    submission.revision,
                    submission.get_status_display(),
                    response.field.label,
                    response.display_value(),
                    submission.operator.display_name if submission.operator_id else "",
                    submission.submitted_at.strftime("%d %b %Y %H:%M") if submission.submitted_at else "",
                ]
            )
    history = workbook.create_sheet("Timeline")
    history.append(["When", "Event", "Phase", "Actor", "Remarks"])
    for event in events:
        history.append(
            [
                event.created_at.strftime("%d %b %Y %H:%M"),
                event.event_type,
                event.phase.name if event.phase_id else "",
                event.actor.display_name if event.actor_id else "",
                event.remarks,
            ]
        )
    rework_sheet = workbook.create_sheet("Rework")
    rework_sheet.append(["Code", "From", "To", "Reason", "Status", "Corrective action"])
    for item in reworks:
        action = item.actions.first()
        rework_sheet.append(
            [
                item.rework_code,
                item.rejected_phase.name,
                item.assigned_phase.name,
                item.reason,
                item.get_status_display(),
                action.corrective_action if action else "",
            ]
        )
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
