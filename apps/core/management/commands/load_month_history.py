"""Add 500 fake machines across September, October, and November 2026.

Does not delete or change machines already in the database. November dates
stop at today. Run again and existing HX26 work orders are skipped.

    python manage.py load_month_history
"""

from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User
from core.bootstrap import ensure_reference_data
from core.constants import TEST_AREAS, Roles
from machines.models import Machine, MachinePlanningData, PlanningCatalogItem, ProductionStation
from machines.services import register_machine
from workflow.engine import (
    approve_qc,
    planner_release,
    production_release,
    reject_machine,
    submit_job_card,
    submit_planning,
)

YEAR = 2026
MONTHS = (9, 10, 11)
LINE_AREA = {"LM1": TEST_AREAS[0], "LM2": TEST_AREAS[1], "SMALL": TEST_AREAS[2]}
PRIORITIES = ["1ST", "2ND", "STANDARD"]
FALLBACK_MODELS = [
    ("Ingersoll Rand", "OF", "R90n Contact-Cooled Rotary 90 kW", "CCN-OF-90"),
    ("Ingersoll Rand", "OF", "Nirvana 75 Variable Speed 75 kW", "CCN-OF-75"),
    ("Ingersoll Rand", "Airend", "Airend 137 mm", "CCN-AE-137"),
    ("Ingersoll Rand", "LIS", "Large industrial rotary 110 kW", "CCN-LIS-110"),
    ("Ingersoll Rand", "MIS", "Medium industrial rotary 55 kW", "CCN-MIS-55"),
    ("Ingersoll Rand", "STN", "30 kW ML30IE", "CCN-STN-30"),
    ("Champion", "OF", "Champion rotary 45 kW", "CCN-CH-45"),
    ("Compair", "OF", "Compair rotary 75 kW", "CCN-CP-75"),
]
# Weights are out of 100. Older months are mostly finished. November is still on the floor.
LEVELS = {
    9: (
        ("done", 62),
        ("qc", 8),
        ("eol", 7),
        ("testing", 6),
        ("assembly_only", 4),
        ("electrical_only", 3),
        ("build", 3),
        ("production", 2),
        ("planner", 1),
        ("draft", 1),
        ("rework_open", 3),
    ),
    10: (
        ("done", 40),
        ("qc", 10),
        ("eol", 10),
        ("testing", 10),
        ("assembly_only", 8),
        ("electrical_only", 5),
        ("build", 5),
        ("production", 4),
        ("planner", 2),
        ("draft", 1),
        ("rework_open", 5),
    ),
    11: (
        ("done", 6),
        ("qc", 6),
        ("eol", 12),
        ("testing", 16),
        ("assembly_only", 14),
        ("electrical_only", 10),
        ("build", 12),
        ("production", 10),
        ("planner", 6),
        ("draft", 4),
        ("rework_open", 4),
    ),
}


def month_dates(year, month, today):
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    if today < start:
        return []
    if today < end:
        end = today
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def level_for(month, index):
    roll = index % 100
    total = 0
    for level, weight in LEVELS[month]:
        total += weight
        if roll < total:
            return level
    return LEVELS[month][-1][0]


def registered_at(day, shift, slot):
    if shift == "1st shift":
        hour = 7 + (slot % 8)
    else:
        hour = 15 + (slot % 7)
    moment = datetime.combine(day, time(hour, (slot * 11) % 60))
    return timezone.make_aware(moment, timezone.get_current_timezone())


class Command(BaseCommand):
    help = "Add 500 fake machines for September, October, and November 2026, up to today."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=500, help="How many machines to add. Default 500.")

    def handle(self, *args, **options):
        count = options["count"]
        if count < 1:
            raise CommandError("Count must be at least 1.")
        ensure_reference_data()
        today = timezone.localdate()
        months = [(month, month_dates(YEAR, month, today)) for month in MONTHS]
        months = [(month, days) for month, days in months if days]
        if not months:
            raise CommandError("None of September, October, or November 2026 is open yet.")
        stations = list(ProductionStation.objects.filter(is_active=True).order_by("line", "sort_order", "code"))
        if not stations:
            raise CommandError("No active stations. Migrate first so the shop floor exists.")
        actor = self._actor()
        planner = User.objects.filter(role=Roles.PLANNING_DATA_ENTRY, is_active=True).order_by("id").first() or actor
        catalog = list(
            PlanningCatalogItem.objects.order_by("company", "machine_type", "model_description").values_list(
                "company", "machine_type", "model_description", "ccn"
            )
        ) or FALLBACK_MODELS
        shares = self._shares(count, len(months))
        added = skipped = 0
        by_month = {month: 0 for month, _days in months}
        for (month, days), share in zip(months, shares):
            for index in range(1, share + 1):
                work_order = f"HX26-{month:02d}-{index:04d}"
                if MachinePlanningData.objects.filter(work_order=work_order).exists():
                    skipped += 1
                    continue
                day = days[(index - 1) % len(days)]
                shift = "1st shift" if ((index - 1) // len(days)) % 2 == 0 else "2nd shift"
                company, machine_type, model, ccn = catalog[(month * 1000 + index) % len(catalog)]
                level = level_for(month, index)
                station = stations[(month + index) % len(stations)]
                machine = register_machine(
                    {
                        "company": company,
                        "work_order": work_order,
                        "ccn": ccn or f"CCN-{month:02d}{index:04d}",
                        "model_description": model,
                        "machine_type": machine_type,
                        "calibration": "Standard" if index % 3 else "Special",
                        "shift": shift,
                        "test_report_bar": "Standard" if index % 2 else "Other",
                        "export_packing_required": "Yes" if index % 4 == 0 else "No",
                        "customer_inspection": "Yes" if index % 5 == 0 else "No",
                        "priority": PRIORITIES[index % len(PRIORITIES)],
                    },
                    planner,
                )
                self._advance(machine, level, actor, station, index, month)
                self._stamp(machine, registered_at(day, shift, index))
                added += 1
                by_month[month] += 1
                if added % 25 == 0:
                    self.stdout.write(f"Added {added}...")
        names = {9: "September", 10: "October", 11: "November"}
        parts = [f"{names[month]} {total}" for month, total in by_month.items()]
        self.stdout.write(self.style.SUCCESS(
            f"Added {added} machines ({', '.join(parts)}). Skipped {skipped} that were already loaded. "
            f"Shop total is now {Machine.objects.count()}."
        ))

    def _shares(self, count, months):
        base, extra = divmod(count, months)
        return [base + (1 if offset < extra else 0) for offset in range(months)]

    def _actor(self):
        actor = (
            User.objects.filter(is_superuser=True, is_active=True).order_by("id").first()
            or User.objects.filter(role=Roles.SUPER_ADMIN, is_active=True).order_by("id").first()
            or User.objects.filter(role=Roles.ADMIN, is_active=True).order_by("id").first()
        )
        if actor is None:
            raise CommandError("Create a Super Admin or Admin before loading this history.")
        return actor

    def _advance(self, machine, level, user, station, index, month):
        serial = f"HXSN-{month:02d}{index:04d}"
        production_serial = f"HXPR-{month:02d}{index:04d}"
        if level == "draft":
            return
        machine = submit_planning(machine, user)
        if level == "planner":
            return
        machine = planner_release(machine, user, serial)
        if level == "production":
            return
        machine = production_release(
            machine, user, station, production_serial=production_serial, remarks="Released to the station."
        )
        if level == "build":
            return
        if level == "electrical_only":
            submit_job_card(machine, user, "ELECTRICAL", {}, remarks="Electrical started.", skip_required=True)
            return
        machine = submit_job_card(machine, user, "ASSEMBLY", {}, remarks="Assembly complete.", skip_required=True)
        if level == "assembly_only":
            return
        machine = submit_job_card(machine, user, "ELECTRICAL", {}, remarks="Electrical complete.", skip_required=True)
        machine.test_area = LINE_AREA.get(station.line, TEST_AREAS[0])
        machine.save(update_fields=["test_area", "updated_at"])
        if level == "testing":
            return
        machine = submit_job_card(machine, user, "TESTING", {}, remarks="Test passed.", skip_required=True)
        if level == "eol":
            return
        machine = submit_job_card(machine, user, "EOL", {}, remarks="EOL accepted.", skip_required=True)
        if level == "qc":
            return
        if level == "done":
            approve_qc(machine, user, {}, remarks="Released.", skip_required=True)
            return
        reject_machine(machine, user, "ASSEMBLY", "Leak found at the discharge connection during the final check.")

    def _stamp(self, machine, when):
        approved = when
        machine.refresh_from_db(fields=["status", "qc_approved_at"])
        if machine.qc_approved_at:
            approved = min(when + timedelta(days=2), timezone.now())
            if approved < when:
                approved = when
        Machine.objects.filter(pk=machine.pk).update(created_at=when, updated_at=approved, qc_approved_at=approved if machine.qc_approved_at else None)
        MachinePlanningData.objects.filter(machine=machine, submitted_at__isnull=False).update(submitted_at=when)
