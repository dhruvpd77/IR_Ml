"""Shop-floor lines and the station board used by location pickers and analytics."""

from django.db.models import Q
from django.urls import reverse

from core.constants import TEST_AREAS, MachineStatus, PhaseCode, PhaseStatus, ShopLine
from machines.models import Machine, ProductionStation


LEGEND = (
    {"label": "Assembly", "color": "#2563eb"},
    {"label": "Electrical", "color": "#d97706"},
    {"label": "Waiting", "color": "#b45309"},
    {"label": "Testing", "color": "#059669"},
    {"label": "End of line", "color": "#7c3aed"},
    {"label": "Rework", "color": "#ea580c"},
)
_LINE_TONE = {ShopLine.LM1: "line-1", ShopLine.LM2: "line-2", ShopLine.SMALL: "line-3"}
_TEST_TONE = {"Test area 1": "area-1", "Test area 2": "area-2", "Test area 3": "area-3"}
_LINE_TEST = {ShopLine.LM1: TEST_AREAS[0], ShopLine.LM2: TEST_AREAS[1], ShopLine.SMALL: TEST_AREAS[2]}


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


def _open_codes(machine):
    return {
        state.phase.code
        for state in machine.phase_states.all()
        if state.status == PhaseStatus.IN_PROGRESS
    }


def _zone(machine):
    phase = machine.current_phase
    if phase == PhaseCode.WAITING or machine.status == MachineStatus.IN_WAITING:
        return "waiting"
    if phase == PhaseCode.TESTING or machine.status == MachineStatus.IN_TESTING:
        return "testing"
    if phase == PhaseCode.EOL or machine.status == MachineStatus.IN_EOL:
        return "eol"
    if machine.station_id and (
        machine.status == MachineStatus.IN_PRODUCTION
        or phase in {PhaseCode.BUILD, PhaseCode.ASSEMBLY, PhaseCode.ELECTRICAL}
    ):
        return "assembly"
    return ""


def _dots(machine, zone):
    open_codes = _open_codes(machine)
    dots = []
    if zone == "assembly":
        if PhaseCode.ASSEMBLY in open_codes:
            dots.append({"label": "Assembly", "color": "#2563eb"})
        if PhaseCode.ELECTRICAL in open_codes:
            dots.append({"label": "Electrical", "color": "#d97706"})
    elif zone == "waiting":
        dots.append({"label": "Waiting", "color": "#b45309"})
    elif zone == "testing":
        dots.append({"label": "Testing", "color": "#059669"})
    elif zone == "eol":
        dots.append({"label": "End of line", "color": "#7c3aed"})
    if machine.is_under_rework:
        dots.append({"label": "Rework", "color": "#e10600"})
    if not dots:
        dots.append({"label": "At this station", "color": "#64748b"})
    return dots


def _testing_area(machine):
    if machine.test_area in _TEST_TONE:
        return machine.test_area
    line = machine.station.line if machine.station_id else ""
    return _LINE_TEST.get(line, "")


def _heat(count):
    if count <= 0:
        return 0
    if count == 1:
        return 1
    if count == 2:
        return 2
    if count <= 4:
        return 3
    return 4


def _chip(machine, zone):
    planning = machine.planning if hasattr(machine, "planning") else None
    serial = machine.planner_serial or machine.production_serial or ""
    model = planning.model_description if planning else ""
    work_order = planning.work_order if planning else ""
    dots = _dots(machine, zone)
    detail = " · ".join(dot["label"] for dot in dots)
    labels = {dot["label"] for dot in dots}
    if machine.is_under_rework:
        tone = "rework"
    elif zone == "waiting":
        tone = "waiting"
    elif zone == "testing":
        tone = "testing"
    elif zone == "eol":
        tone = "eol"
    elif "Assembly" in labels and "Electrical" in labels:
        tone = "both"
    elif "Electrical" in labels:
        tone = "electrical"
    else:
        tone = "assembly"
    return {
        "id": machine.machine_id,
        "serial": serial or "No serial",
        "model": model,
        "work_order": work_order,
        "shift": planning.shift if planning else "",
        "priority": machine.priority_label,
        "rework": machine.is_under_rework,
        "dots": dots,
        "tone": tone,
        "where": detail,
        "caption": " · ".join(part for part in (machine.machine_id, serial, model, work_order, detail) if part),
    }


def floor_board(start=None, end=None, on_date=None, shift=""):
    machines = (
        Machine.objects.filter(
            Q(
                status__in=[
                    MachineStatus.IN_PRODUCTION,
                    MachineStatus.IN_WAITING,
                    MachineStatus.IN_TESTING,
                    MachineStatus.IN_EOL,
                    MachineStatus.UNDER_REWORK,
                ]
            )
            | Q(
                current_phase__in=[
                    PhaseCode.BUILD,
                    PhaseCode.ASSEMBLY,
                    PhaseCode.ELECTRICAL,
                    PhaseCode.WAITING,
                    PhaseCode.TESTING,
                    PhaseCode.EOL,
                ]
            )
        )
        .select_related("planning", "station")
        .prefetch_related("phase_states__phase")
        .order_by("machine_id")
    )
    if on_date:
        machines = machines.filter(created_at__date=on_date)
    elif start and end:
        machines = machines.filter(created_at__gte=start, created_at__lt=end)
    if shift:
        machines = machines.filter(planning__shift=shift)
    by_station = {}
    by_area = {name: [] for name in TEST_AREAS}
    waiting = []
    eol = []
    for machine in machines:
        zone = _zone(machine)
        if zone == "assembly":
            by_station.setdefault(machine.station_id, []).append(_chip(machine, zone))
        elif zone == "waiting":
            waiting.append(_chip(machine, zone))
        elif zone == "testing":
            area = _testing_area(machine)
            by_area[area or TEST_AREAS[0]].append(_chip(machine, zone))
        elif zone == "eol":
            eol.append(_chip(machine, zone))
    lines = []
    assembly_count = 0
    for group in stations_by_line():
        boxes = []
        count = 0
        for station in group["stations"]:
            chips = by_station.get(station.pk, [])
            count += len(chips)
            boxes.append({"station": station, "machines": chips, "count": len(chips), "heat": _heat(len(chips))})
        assembly_count += count
        lines.append(
            {
                "code": group["code"],
                "label": group["label"],
                "tone": _LINE_TONE.get(group["code"], "line-1"),
                "boxes": boxes,
                "count": count,
            }
        )
    test_areas = [
        {
            "name": name,
            "tone": _TEST_TONE[name],
            "machines": by_area[name],
            "count": len(by_area[name]),
            "heat": _heat(len(by_area[name])),
        }
        for name in TEST_AREAS
    ]
    testing_count = sum(area["count"] for area in test_areas)
    waiting_count = len(waiting)
    return {
        "lines": lines,
        "waiting_machines": waiting,
        "waiting_count": waiting_count,
        "waiting_heat": _heat(waiting_count),
        "test_areas": test_areas,
        "eol_machines": eol,
        "assembly_count": assembly_count,
        "testing_count": testing_count,
        "eol_count": len(eol),
        "eol_heat": _heat(len(eol)),
        "on_floor": assembly_count + waiting_count + testing_count + len(eol),
        "legend": LEGEND,
    }


def _chip_payload(chip):
    return {
        "id": chip["id"],
        "url": reverse("machines:detail", args=[chip["id"]]),
        "tone": chip["tone"],
        "rework": chip["rework"],
        "caption": chip["caption"],
        "serial": chip["serial"],
        "where": chip["where"],
        "dots": chip["dots"],
    }


def floor_board_payload(start=None, end=None, on_date=None, shift=""):
    """JSON-ready shop floor snapshot for live analytics refresh."""
    board = floor_board(start=start, end=end, on_date=on_date, shift=shift)
    return {
        "assembly_count": board["assembly_count"],
        "waiting_count": board["waiting_count"],
        "waiting_heat": board["waiting_heat"],
        "testing_count": board["testing_count"],
        "eol_count": board["eol_count"],
        "eol_heat": board["eol_heat"],
        "on_floor": board["on_floor"],
        "lines": [
            {
                "code": line["code"],
                "label": line["label"],
                "tone": line["tone"],
                "count": line["count"],
                "boxes": [
                    {
                        "station_id": box["station"].pk,
                        "station_name": box["station"].name,
                        "count": box["count"],
                        "heat": box["heat"],
                        "machines": [_chip_payload(chip) for chip in box["machines"]],
                    }
                    for box in line["boxes"]
                ],
            }
            for line in board["lines"]
        ],
        "waiting_machines": [_chip_payload(chip) for chip in board["waiting_machines"]],
        "test_areas": [
            {
                "name": area["name"],
                "tone": area["tone"],
                "count": area["count"],
                "heat": area["heat"],
                "machines": [_chip_payload(chip) for chip in area["machines"]],
            }
            for area in board["test_areas"]
        ],
        "eol_machines": [_chip_payload(chip) for chip in board["eol_machines"]],
    }
