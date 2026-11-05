"""Shop-floor lines and the station board used by location pickers and analytics."""

from core.constants import PhaseCode, PhaseStatus, ShopLine
from machines.models import Machine, ProductionStation

LEGEND = (
    {"code": "ASSEMBLY", "label": "Assembly", "shape": "circle", "color": "#3b82f6"},
    {"code": "ELECTRICAL", "label": "Electrical", "shape": "triangle", "color": "#f59e0b"},
    {"code": "TESTING", "label": "Testing", "shape": "square", "color": "#22c55e"},
    {"code": "EOL", "label": "End of line", "shape": "diamond", "color": "#a78bfa"},
    {"code": "QC", "label": "Quality", "shape": "hex", "color": "#fb7185"},
    {"code": "COMPLETED", "label": "Completed", "shape": "target", "color": "#34d399"},
    {"code": "REWORK", "label": "Rework", "shape": "star", "color": "#f97316"},
    {"code": "WAIT", "label": "Allocated", "shape": "dot", "color": "#94a3b8"},
)
_MARK = {item["code"]: item for item in LEGEND}
_WORK = (PhaseCode.ASSEMBLY, PhaseCode.ELECTRICAL, PhaseCode.TESTING, PhaseCode.EOL, PhaseCode.QC)


def stations_by_line(active_only=True):
    stations = ProductionStation.objects.all()
    if active_only:
        stations = stations.filter(is_active=True)
    buckets = {code: [] for code, _label in ShopLine.CHOICES}
    for station in stations.order_by("line", "sort_order", "name"):
        if station.line in buckets:
            buckets[station.line].append(station)
    return [
        {"code": code, "label": label, "stations": buckets[code]}
        for code, label in ShopLine.CHOICES
        if buckets[code]
    ]


def _mark(code, live=False):
    item = dict(_MARK[code])
    item["live"] = live
    return item


def machine_marks(machine):
    if machine.status == "COMPLETED":
        return [_mark("COMPLETED", live=False)]
    states = {state.phase.code: state for state in machine.phase_states.all()}
    marks = []
    if machine.is_under_rework:
        marks.append(_mark("REWORK", live=True))
    for code in _WORK:
        state = states.get(code)
        if state and state.status == PhaseStatus.IN_PROGRESS:
            marks.append(_mark(code, live=True))
    if not marks:
        marks.append(_mark("WAIT", live=False))
    return marks


def floor_board():
    placed = (
        Machine.objects.exclude(station_id=None)
        .select_related("planning", "station")
        .prefetch_related("phase_states__phase")
        .order_by("machine_id")
    )
    by_station = {}
    for machine in placed:
        marks = machine_marks(machine)
        by_station.setdefault(machine.station_id, []).append(
            {
                "id": machine.machine_id,
                "model": machine.planning.model_description if hasattr(machine, "planning") else "",
                "work_order": machine.planning.work_order if hasattr(machine, "planning") else "",
                "marks": marks,
                "live": any(mark["live"] for mark in marks),
                "phase_label": " · ".join(mark["label"] for mark in marks),
                "caption": machine.machine_id + " · " + " · ".join(mark["label"] for mark in marks),
            }
        )
    lines = []
    on_floor = 0
    for group in stations_by_line():
        boxes = []
        count = 0
        for station in group["stations"]:
            chips = by_station.get(station.pk, [])
            count += len(chips)
            tally = []
            for item in LEGEND:
                total = sum(1 for chip in chips for mark in chip["marks"] if mark["code"] == item["code"])
                if total:
                    tally.append({**item, "count": total, "live": item["code"] not in {"COMPLETED", "WAIT"}})
            boxes.append({"station": station, "machines": chips, "count": len(chips), "tally": tally})
        on_floor += count
        lines.append(
            {
                "code": group["code"],
                "label": group["label"],
                "tone": "small" if group["code"] == ShopLine.SMALL else "large",
                "subtitle": "Full assembly" if group["code"] else "Not on a line",
                "boxes": boxes,
                "count": count,
            }
        )
    waiting = Machine.objects.filter(station_id=None).exclude(status="COMPLETED").count()
    return {"lines": lines, "on_floor": on_floor, "waiting": waiting, "legend": LEGEND}
