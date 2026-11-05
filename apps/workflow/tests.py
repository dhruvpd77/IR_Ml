import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from accounts.models import Department
from core.bootstrap import ensure_reference_data
from core.constants import ROLE_DEPARTMENT, MachineStatus, PhaseCode, Roles
from jobcards.models import JobCardSubmission
from machines.catalog import replace_catalog
from machines.forms import PlanningForm
from machines.importer import build_import_preview, confirm_import
from machines.models import PlanningCatalogItem, ProductionStation
from machines.services import register_machine
from workflow.engine import (
    WorkflowError,
    approve_qc,
    planner_release,
    production_release,
    reject_machine,
    submit_job_card,
    submit_planning,
)
from workflow.tests_support import sample_answers

User = get_user_model()


def make_user(username, role):
    return User.objects.create_user(
        username=username,
        password="IrDemo@2026",
        role=role,
        first_name=username,
        department=Department.objects.get(code=ROLE_DEPARTMENT[role]),
    )


def planning_data(suffix="1"):
    return {
        "company": "Ingersoll Rand",
        "work_order": f"WO-T{suffix}",
        "ccn": f"CCN-T{suffix}",
        "model_description": "R90n Contact-Cooled Rotary 90 kW",
        "machine_type": "Rotary Screw",
        "calibration": "Standard",
        "test_report_bar": "7 Bar",
        "export_packing_required": "No",
        "customer_inspection": "No",
        "priority": "HIGH",
    }


class WorkflowRuleTests(TestCase):
    def setUp(self):
        ensure_reference_data()
        self.planning = make_user("planning", Roles.PLANNING_DATA_ENTRY)
        self.leader = make_user("leader", Roles.PRODUCTION_LEADER)
        self.assembly = make_user("assembly", Roles.ASSEMBLY)
        self.electrical = make_user("electrical", Roles.ELECTRICAL)
        self.testing = make_user("testing", Roles.TESTING)
        self.eol = make_user("eol", Roles.EOL)
        self.qc = make_user("qc", Roles.QC)
        self.station = ProductionStation.objects.get(code="LM1-S4")

    def _to_production(self, suffix="1"):
        machine = register_machine(planning_data(suffix), self.planning)
        submit_planning(machine, self.planning)
        planner_release(machine, self.leader, f"SN-{suffix}")
        production_release(machine, self.leader, self.station, remarks="Bay release")
        machine.refresh_from_db()
        return machine

    def _to_qc(self, suffix):
        machine = self._to_production(suffix)
        for phase, user in (("ASSEMBLY", self.assembly), ("ELECTRICAL", self.electrical), ("TESTING", self.testing), ("EOL", self.eol)):
            submit_job_card(machine, user, phase, sample_answers(user, phase))
            machine.refresh_from_db()
        return machine

    def test_phases_cannot_be_skipped_and_parallel_departments_are_independent(self):
        machine = register_machine(planning_data("10"), self.planning)
        with self.assertRaises(WorkflowError):
            planner_release(machine, self.leader, "SN-EARLY")
        submit_planning(machine, self.planning)
        with self.assertRaises(WorkflowError):
            production_release(machine, self.leader, self.station)
        planner_release(machine, self.leader, "SN-10")
        production_release(machine, self.leader, self.station)
        machine.refresh_from_db()
        self.assertEqual(machine.status, MachineStatus.IN_PRODUCTION)
        with self.assertRaises(WorkflowError):
            submit_job_card(machine, self.testing, "TESTING", sample_answers(self.testing, "TESTING"))
        submit_job_card(machine, self.assembly, "ASSEMBLY", sample_answers(self.assembly, "ASSEMBLY"))
        machine.refresh_from_db()
        self.assertEqual(machine.status, MachineStatus.IN_PRODUCTION)
        self.assertEqual(machine.current_phase, PhaseCode.BUILD)
        with self.assertRaises(WorkflowError):
            submit_job_card(machine, self.testing, "TESTING", sample_answers(self.testing, "TESTING"))
        submit_job_card(machine, self.electrical, "ELECTRICAL", sample_answers(self.electrical, "ELECTRICAL"))
        machine.refresh_from_db()
        self.assertEqual(machine.status, MachineStatus.IN_TESTING)
        with self.assertRaises(WorkflowError):
            approve_qc(machine, self.qc, sample_answers(self.qc, "QC"))
        submit_job_card(machine, self.testing, "TESTING", sample_answers(self.testing, "TESTING"))
        submit_job_card(machine, self.eol, "EOL", sample_answers(self.eol, "EOL"))
        approve_qc(machine, self.qc, sample_answers(self.qc, "QC"))
        machine.refresh_from_db()
        self.assertEqual(machine.status, MachineStatus.COMPLETED)
        self.assertIsNotNone(machine.qc_approved_at)
        self.assertEqual(machine.qc_approved_by, self.qc)

    def test_rework_keeps_history_and_replays_later_phases(self):
        machine = self._to_qc("20")
        original = JobCardSubmission.objects.get(machine=machine, phase_code="ELECTRICAL", status="SUBMITTED")
        reject_machine(machine, self.qc, "ELECTRICAL", "Terminal insulation was below the limit.")
        original.refresh_from_db()
        self.assertEqual(original.status, "SUBMITTED")
        machine.refresh_from_db()
        self.assertEqual(machine.status, MachineStatus.UNDER_REWORK)
        self.assertTrue(machine.is_under_rework)
        with self.assertRaises(WorkflowError):
            submit_job_card(machine, self.testing, "TESTING", sample_answers(self.testing, "TESTING"))
        submit_job_card(
            machine,
            self.electrical,
            "ELECTRICAL",
            sample_answers(self.electrical, "ELECTRICAL"),
            corrective_action="Re-terminated the motor lead and repeated the insulation test.",
        )
        machine.refresh_from_db()
        self.assertEqual(machine.status, MachineStatus.IN_TESTING)
        self.assertEqual(JobCardSubmission.objects.filter(machine=machine, phase_code="ELECTRICAL").count(), 2)
        submit_job_card(machine, self.testing, "TESTING", sample_answers(self.testing, "TESTING"))
        submit_job_card(machine, self.eol, "EOL", sample_answers(self.eol, "EOL"))
        machine.refresh_from_db()
        self.assertNotEqual(machine.status, MachineStatus.COMPLETED)
        approve_qc(machine, self.qc, sample_answers(self.qc, "QC"))
        machine.refresh_from_db()
        self.assertEqual(machine.status, MachineStatus.COMPLETED)
        self.assertFalse(machine.is_under_rework)

    def test_duplicate_serial_and_repeat_submission_are_rejected(self):
        first = self._to_production("30")
        second = register_machine(planning_data("31"), self.planning)
        submit_planning(second, self.planning)
        with self.assertRaises(WorkflowError):
            planner_release(second, self.leader, "SN-30")
        with self.assertRaises(WorkflowError):
            submit_job_card(first, self.assembly, "ASSEMBLY", sample_answers(self.assembly, "ASSEMBLY"))
            submit_job_card(first, self.assembly, "ASSEMBLY", sample_answers(self.assembly, "ASSEMBLY"))

    def test_other_roles_cannot_approve_or_open_another_queue(self):
        machine = self._to_qc("40")
        with self.assertRaises(WorkflowError):
            approve_qc(machine, self.planning, sample_answers(self.planning, "QC"))
        self.client.login(username="assembly", password="IrDemo@2026")
        response = self.client.get(reverse("workflow:planner"))
        self.assertEqual(response.status_code, 403)
        allowed = self.client.get(reverse("workflow:phase", args=["ASSEMBLY"]))
        self.assertEqual(allowed.status_code, 200)
        self.assertNotContains(allowed, machine.machine_id)
        submitted = self.client.get(reverse("workflow:phase", args=["ASSEMBLY"]) + "?tab=done")
        self.assertContains(submitted, machine.machine_id)

    def test_dashboards_render_for_department_and_super_admin(self):
        self.client.login(username="planning", password="IrDemo@2026")
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 200)
        make_user("boss", Roles.SUPER_ADMIN)
        self.client.login(username="boss", password="IrDemo@2026")
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("machines:list")).status_code, 200)

    def test_queues_link_to_previously_filled_details(self):
        machine = register_machine(planning_data("view"), self.planning)
        submit_planning(machine, self.planning)
        self.client.login(username="leader", password="IrDemo@2026")
        queue = self.client.get(reverse("workflow:planner"))
        self.assertContains(queue, "View")
        detail = self.client.get(reverse("machines:detail", args=[machine.machine_id]))
        self.assertContains(detail, "Planning date")
        self.assertContains(detail, "WO-Tview")
        self.assertContains(detail, "R90n Contact-Cooled Rotary 90 kW")
        self.assertContains(detail, "Assembly checklist")
        planner_release(machine, self.leader, "SN-view")
        production_release(machine, self.leader, self.station, production_serial="PR-view", remarks="Bay release")
        self.client.login(username="assembly", password="IrDemo@2026")
        assembly = self.client.get(reverse("workflow:phase", args=["ASSEMBLY"]))
        self.assertContains(assembly, "View")
        record = self.client.get(reverse("machines:detail", args=[machine.machine_id]))
        self.assertContains(record, "Machine serial number")
        self.assertContains(record, "SN-VIEW")
        self.assertContains(record, "Production Leader")
        self.assertContains(record, "Bay release")
        self.assertContains(record, "PR-VIEW")
        self.assertContains(record, "Large / Medium – Line 1 · Station 4")

    def test_machine_ids_are_unique(self):
        ids = {register_machine(planning_data(str(50 + i)), self.planning).machine_id for i in range(3)}
        self.assertEqual(len(ids), 3)


class ImportTests(TestCase):
    def setUp(self):
        ensure_reference_data()
        self.user = make_user("planning-import", Roles.PLANNING_DATA_ENTRY)
        register_machine(planning_data("90"), self.user)

    def test_preview_separates_valid_invalid_and_duplicate_rows(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Company", "Work Order", "CCN", "Model Description", "Type", "Calibration", "Test Report Required at Bar", "Export Packing Required", "Customer Inspection", "Priority"])
        sheet.append(["Ingersoll Rand", "WO-NEW", "CCN-NEW", "Nirvana 75", "Rotary Screw", "Standard", "7 Bar", "No", "No", "High"])
        sheet.append(["Ingersoll Rand", "", "CCN-X", "", "Rotary Screw", "", "", "", "", "High"])
        sheet.append(["Ingersoll Rand", "WO-T90", "CCN-T90", "R90n Contact-Cooled Rotary 90 kW", "Rotary Screw", "Standard", "7 Bar", "No", "No", "Low"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        upload = SimpleUploadedFile("planning.xlsx", buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        batch, _unknown = build_import_preview(upload, self.user)
        self.assertEqual(batch.valid_count, 1)
        self.assertEqual(batch.duplicate_count, 1)
        created = confirm_import(batch, self.user)
        self.assertEqual(len(created), 1)
        self.assertTrue(created[0].machine_id.startswith("IR-MCH-"))


class CatalogTests(TestCase):
    def setUp(self):
        ensure_reference_data()
        self.planning = make_user("planning-catalog", Roles.PLANNING_DATA_ENTRY)
        self.leader = make_user("leader-catalog", Roles.PRODUCTION_LEADER)

    def _workbook(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Company", "CCN", "TYPE", "Model Description", "Work order"])
        sheet.append(["Ingersoll Rand", 24153579, "OF", "COMPRESSOR SIERRA SM45", "WR001"])
        sheet.append(["Ingersoll Rand", 24153579, "OF", "COMPRESSOR SIERRA SM45", ""])
        sheet.append(["Champion", "47804542001", "OF", "COMPRESSOR PACKAGE D3/H", ""])
        buffer = io.BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        return SimpleUploadedFile("planning.xlsx", buffer.getvalue())

    def test_upload_keeps_unique_models_and_registration_copies_ccn(self):
        result = replace_catalog(self._workbook(), self.leader)
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(PlanningCatalogItem.objects.count(), 2)
        form = PlanningForm()
        self.assertEqual(form.initial["calibration"], "No")
        self.assertEqual(form.initial["test_report_bar"], "Standard")
        self.assertEqual(form.initial["export_packing_required"], "No")
        self.assertEqual(form.initial["customer_inspection"], "No")
        self.assertEqual(form.initial["priority"], "STANDARD")
        posted = PlanningForm(
            data={
                "company": "Ingersoll Rand",
                "machine_type": "OF",
                "model_description": "COMPRESSOR SIERRA SM45",
                "ccn": "WRONG",
                "work_order": "WO-1",
                "calibration": "No",
                "test_report_bar": "Standard",
                "export_packing_required": "No",
                "customer_inspection": "No",
                "priority": "STANDARD",
            }
        )
        self.assertTrue(posted.is_valid(), posted.errors)
        self.assertEqual(posted.cleaned_data["ccn"], "24153579")

    def test_catalog_upload_is_limited_to_production_leader_and_management(self):
        self.client.login(username="planning-catalog", password="IrDemo@2026")
        self.assertEqual(self.client.get(reverse("machines:catalog")).status_code, 403)
        self.client.login(username="leader-catalog", password="IrDemo@2026")
        self.assertEqual(self.client.get(reverse("machines:catalog")).status_code, 200)
        self.client.login(username="planning-catalog", password="IrDemo@2026")
        page = self.client.get(reverse("machines:create"))
        self.assertContains(page, "Model description")
        self.assertNotContains(page, "Model catalog")
