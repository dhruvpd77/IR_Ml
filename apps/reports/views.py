from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from accounts.permissions import can_view_machine, can_view_reports
from core.constants import MachineStatus, Priority
from core.http import paginate, querystring
from machines.models import Machine, ProductionStation
from reports.builders import REPORTS, build_report
from reports.excel import machine_workbook, workbook_bytes
from reports.pdf import machine_history_pdf, table_pdf
from workflow.models import ProductionPhase
from workflow.presenters import tracking_steps


def _guard(user):
    if not can_view_reports(user):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied


def _dossier(machine):
    submissions = list(
        machine.job_card_submissions.exclude(status="DRAFT")
        .select_related("operator", "template")
        .prefetch_related("responses__field")
        .order_by("phase_code", "cycle", "revision")
    )
    events = list(machine.events.select_related("actor", "phase"))
    reworks = list(machine.reworks.select_related("assigned_phase", "rejected_phase").prefetch_related("actions"))
    return submissions, events, reworks


@login_required
def index(request):
    _guard(request.user)
    key = request.GET.get("report") or "production"
    if key not in dict(REPORTS):
        key = "production"
    title, headers, rows = build_report(key, request.GET)
    return render(
        request,
        "reports/index.html",
        {
            "reports": REPORTS,
            "selected": key,
            "title": title,
            "headers": headers,
            "page": paginate(request, rows, size=25),
            "filters": request.GET,
            "phases": ProductionPhase.objects.filter(is_active=True),
            "stations": ProductionStation.objects.filter(is_active=True),
            "statuses": MachineStatus.CHOICES,
            "priorities": Priority.CHOICES,
            "querystring": querystring(request),
        },
    )


@login_required
def export_excel(request):
    _guard(request.user)
    key = request.GET.get("report") or "production"
    title, headers, rows = build_report(key, request.GET)
    return FileResponse(workbook_bytes(title, headers, rows), as_attachment=True, filename=f"{key}-report.xlsx")


@login_required
def export_pdf(request):
    _guard(request.user)
    key = request.GET.get("report") or "production"
    title, headers, rows = build_report(key, request.GET)
    subtitle = "Generated " + timezone.localtime().strftime("%d %b %Y %H:%M")
    return FileResponse(
        table_pdf(title, subtitle, headers, rows),
        as_attachment=True,
        filename=f"{key}-report.pdf",
        content_type="application/pdf",
    )


@login_required
def machine_excel(request, machine_id):
    machine = get_object_or_404(Machine.objects.select_related("planning", "station"), machine_id=machine_id)
    if not can_view_machine(request.user, machine):
        raise Http404
    submissions, events, reworks = _dossier(machine)
    return FileResponse(machine_workbook(machine, submissions, events, reworks), as_attachment=True, filename=f"{machine.machine_id}.xlsx")


@login_required
def machine_pdf(request, machine_id):
    machine = get_object_or_404(Machine.objects.select_related("planning", "station"), machine_id=machine_id)
    if not can_view_machine(request.user, machine):
        raise Http404
    submissions, events, reworks = _dossier(machine)
    buffer = machine_history_pdf(machine, tracking_steps(machine), submissions, events, reworks)
    return FileResponse(buffer, as_attachment=True, filename=f"{machine.machine_id}.pdf", content_type="application/pdf")
