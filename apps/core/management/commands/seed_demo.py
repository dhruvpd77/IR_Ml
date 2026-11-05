from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from openpyxl import Workbook

from accounts.models import Department, User, set_setting
from core.bootstrap import ensure_reference_data
from core.constants import ROLE_DEPARTMENT, Roles
from jobcards.services import active_template
from machines.models import Machine, ProductionStation
from machines.services import register_machine
from workflow.engine import (
    approve_qc,
    planner_release,
    production_release,
    reject_machine,
    submit_job_card,
    submit_planning,
)

PASSWORD = "IrDemo@2026"
PEOPLE = [
    ("superadmin", Roles.SUPER_ADMIN, "Asha", "Menon"),
    ("admin", Roles.ADMIN, "Rohit", "Iyer"),
    ("planning1", Roles.PLANNING_DATA_ENTRY, "Neha", "Kapoor"),
    ("planning2", Roles.PLANNING_DATA_ENTRY, "Vikram", "Shah"),
    ("planner1", Roles.PRODUCTION_LEADER, "Anita", "Desai"),
    ("planner2", Roles.PRODUCTION_LEADER, "Karan", "Mehta"),
    ("leader1", Roles.PRODUCTION_LEADER, "Sanjay", "Rao"),
    ("leader2", Roles.PRODUCTION_LEADER, "Pooja", "Nair"),
    ("assembly1", Roles.ASSEMBLY, "Imran", "Qureshi"),
    ("assembly2", Roles.ASSEMBLY, "Lakshmi", "Reddy"),
    ("electrical1", Roles.ELECTRICAL, "Arun", "Pillai"),
    ("electrical2", Roles.ELECTRICAL, "Divya", "Joshi"),
    ("testing1", Roles.TESTING, "Farhan", "Ali"),
    ("testing2", Roles.TESTING, "Meera", "Kulkarni"),
    ("eol1", Roles.EOL, "Suresh", "Patil"),
    ("eol2", Roles.EOL, "Kavita", "Bose"),
    ("qc1", Roles.QC, "Nandita", "Sen"),
    ("qc2", Roles.QC, "Rahul", "Verma"),
]
MODELS = [
    ("R90n Contact-Cooled Rotary 90 kW", "Rotary Screw"),
    ("Nirvana 75 Variable Speed 75 kW", "Rotary Screw"),
    ("Sierra SL 37 Oil-Free 37 kW", "Oil-Free Rotary"),
    ("UP6 15 Rotary 15 kW", "Rotary Screw"),
    ("MSG Centac C800", "Centrifugal"),
    ("IRN50H-OF Oil-Free 50 HP", "Oil-Free Rotary"),
]
PRIORITIES = ["1ST", "2ND", "STANDARD"]


def sample_answers(user, phase_code):
    answers = {}
    for field in active_template(phase_code).active_fields():
        kind = field.field_type
        if kind == "pass_fail":
            answers[field.field_key] = "Pass"
        elif kind == "yes_no":
            answers[field.field_key] = "Yes"
        elif kind in {"measurement", "decimal"}:
            answers[field.field_key] = "12.5"
        elif kind == "integer":
            answers[field.field_key] = "4"
        elif kind == "signature":
            answers[field.field_key] = {"name": user.display_name, "confirmed": True}
        elif kind in {"dropdown", "radio"}:
            answers[field.field_key] = (field.options or ["OK"])[0]
        elif kind in {"date"}:
            answers[field.field_key] = timezone.localdate().isoformat()
        elif kind == "time":
            answers[field.field_key] = "10:30"
        elif kind in {"image", "video", "file"}:
            continue
        else:
            answers[field.field_key] = "Checked and within specification."
    return answers


class Command(BaseCommand):
    help = "Create departments, phase users, and sample machines across the production flow."

    def handle(self, *args, **options):
        ensure_reference_data()
        users = {}
        for username, role, first, last in PEOPLE:
            department = Department.objects.get(code=ROLE_DEPARTMENT[role])
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "role": role,
                    "first_name": first,
                    "last_name": last,
                    "email": f"{username}@ingersollrand.example",
                    "employee_id": username.upper(),
                    "department": department,
                    "is_staff": role in Roles.MANAGEMENT,
                    "is_superuser": role == Roles.SUPER_ADMIN,
                },
            )
            if created:
                user.set_password(PASSWORD)
                user.save()
            users[username] = user
        if Machine.objects.exists():
            self.stdout.write("Machines are already in this database, so no extra fake records were added.")
        else:
            self._machines(users)
            set_setting("sample_data_loaded", "yes")
            self._workbook()
            self.stdout.write(self.style.SUCCESS(f"Added {Machine.objects.count()} fake machines."))
        self.stdout.write(self.style.SUCCESS("MQMS demo data is ready."))
        self.stdout.write(f"Password for every demo account: {PASSWORD}")
        self.stdout.write("Super admin: superadmin    Admin: admin")
        self.stdout.write("Two users exist for every phase, for example assembly1 and assembly2.")

    def _machines(self, users):
        stations = list(ProductionStation.objects.filter(is_active=True).order_by("code"))
        if not stations:
            raise RuntimeError("No active stations. Run migrate first so the shop floor is created.")
        companies = ["Ingersoll Rand", "Champion", "Compair"]
        plan = (
            [("draft", None)] * 2
            + [("planner", None)] * 2
            + [("production", None)] * 2
            + [("build", None)] * 2
            + [("assembly_only", None)] * 3
            + [("testing", None)] * 5
            + [("eol", None)] * 5
            + [("qc", None)] * 2
            + [("done", age) for age in (18, 14, 9, 4, 2)]
            + [("rework_open", None), ("rework_qc", None)]
        )
        for index, (level, age) in enumerate(plan, start=1):
            model, kind = MODELS[index % len(MODELS)]
            machine = register_machine(
                {
                    "company": companies[index % len(companies)],
                    "work_order": f"WO-26{100 + index}",
                    "ccn": f"CCN-{7000 + index}",
                    "model_description": model,
                    "machine_type": kind,
                    "calibration": "Standard",
                    "test_report_bar": "7 Bar" if index % 2 == 0 else "8.5 Bar",
                    "export_packing_required": "Yes" if index % 3 == 0 else "No",
                    "customer_inspection": "Yes" if index % 4 == 0 else "No",
                    "priority": PRIORITIES[index % len(PRIORITIES)],
                },
                users["planning1"],
            )
            self._advance(machine, level, users, stations[index % len(stations)], index)
            machine.refresh_from_db()
            if age and machine.status == "COMPLETED":
                created = timezone.now() - timedelta(days=age)
                Machine.objects.filter(pk=machine.pk).update(
                    created_at=created,
                    qc_approved_at=created + timedelta(days=3),
                    updated_at=created + timedelta(days=3),
                )

    def _advance(self, machine, level, users, station, index):
        if level == "draft":
            return
        submit_planning(machine, users["planning1"])
        if level == "planner":
            return
        planner_release(machine, users["planner1"], f"SN-26{index:04d}")
        if level == "production":
            return
        production_release(machine, users["leader1"], station, production_serial=f"PR-26{index:04d}", remarks="Released to the build bays.")
        if level == "build":
            return
        submit_job_card(machine, users["assembly1"], "ASSEMBLY", sample_answers(users["assembly1"], "ASSEMBLY"), remarks="Assembly complete.")
        if level == "assembly_only":
            return
        submit_job_card(machine, users["electrical1"], "ELECTRICAL", sample_answers(users["electrical1"], "ELECTRICAL"), remarks="Electrical complete.")
        if level == "testing":
            return
        submit_job_card(machine, users["testing1"], "TESTING", sample_answers(users["testing1"], "TESTING"), remarks="Test passed.")
        if level == "eol":
            return
        submit_job_card(machine, users["eol1"], "EOL", sample_answers(users["eol1"], "EOL"), remarks="EOL accepted.")
        if level == "qc":
            return
        if level == "done":
            approve_qc(machine, users["qc1"], sample_answers(users["qc1"], "QC"), remarks="Released to finished goods.")
            return
        if level == "rework_open":
            reject_machine(machine, users["qc1"], "ELECTRICAL", "Insulation reading was below the limit at the motor terminal.")
            return
        reject_machine(machine, users["qc1"], "ELECTRICAL", "Control interlock did not drop out on the emergency stop.")
        machine.refresh_from_db()
        submit_job_card(
            machine,
            users["electrical1"],
            "ELECTRICAL",
            sample_answers(users["electrical1"], "ELECTRICAL"),
            remarks="Interlock circuit corrected.",
            corrective_action="Replaced the emergency-stop contact block and verified the safety circuit.",
        )
        submit_job_card(machine, users["testing1"], "TESTING", sample_answers(users["testing1"], "TESTING"), remarks="Retest passed.")
        submit_job_card(machine, users["eol1"], "EOL", sample_answers(users["eol1"], "EOL"), remarks="EOL repeated after rework.")

    def _workbook(self):
        from pathlib import Path

        folder = Path(__file__).resolve().parents[4] / "sample_data"
        folder.mkdir(exist_ok=True)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Planning Data"
        sheet.append(["Company", "Work Order", "CCN", "Model Description", "Type", "Calibration", "Test Report Required at Bar", "Export Packing Required", "Customer Inspection", "Priority"])
        sheet.append(["Ingersoll Rand", "WO-26901", "CCN-9901", "R90n Contact-Cooled Rotary 90 kW", "Rotary Screw", "Standard", "7 Bar", "No", "No", "High"])
        sheet.append(["Ingersoll Rand", "WO-26902", "CCN-9902", "Sierra SL 37 Oil-Free 37 kW", "Oil-Free Rotary", "Special", "8.5 Bar", "Yes", "Yes", "Critical"])
        workbook.save(folder / "Planning_Data_Sample.xlsx")
