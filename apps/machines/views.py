from django.contrib import messages
from django.templatetags.static import static
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import management_required, roles_required
from accounts.permissions import can_delete_machine, can_edit_planning, can_operate_phase, can_reject, can_view_machine
from audit.utils import log_audit
from core.constants import TEST_AREAS, MachineStatus, PhaseCode, PhaseStatus, Priority, Roles
from core.http import paginate, querystring
from machines.catalog import CatalogError, models_for, replace_catalog
from machines.forms import ImportUploadForm, PlanningForm, PlanningFormSet, StationForm
from machines.importer import build_import_preview, confirm_import, error_workbook, planning_template_workbook
from machines.floor import stations_by_line
from machines.models import ImportBatch, Machine, MachineNote, PlanningCatalogItem, ProductionStation
from machines.services import apply_machine_filters, apply_sort, register_machine, update_planning, visible_machines
from jobcards.services import JobCardError
from machines.brand import brand_static
from workflow.engine import WorkflowError, pass_phase, reachable_rework_targets, submit_planning
from workflow.models import WorkflowEvent
from accounts.models import current_logo
from core.stats import CARD_META, STAGE_LABELS, limit_for_card
from workflow.presenters import event_label, job_card_view, pipeline_label, recent_events, tracking_steps


def _machine_or_404(user, machine_id):
    machine = get_object_or_404(
        visible_machines(user).prefetch_related("phase_states__phase", "phase_states__completed_by", "phase_states__started_by"),
        machine_id=machine_id,
    )
    if not can_view_machine(user, machine):
        raise PermissionDenied
    return machine


def _with_track(user, machine):
    steps = tracking_steps(machine)
    for group in steps:
        group["here"] = False
        group["done"] = bool(group["phases"])
        for phase in group["phases"]:
            if phase["status"] != PhaseStatus.COMPLETED:
                group["done"] = False
            if phase["status"] == PhaseStatus.IN_PROGRESS:
                group["here"] = True
            phase["can_pass"] = (
                phase["status"] == PhaseStatus.IN_PROGRESS
                and can_operate_phase(user, phase["code"])
                and _pass_ready(machine, phase["code"])
            )
    machine.track_steps = steps
    machine.pipeline = pipeline_label(machine)
    machine.track_actions = _actions(user, machine)
    return machine


def _actions(user, machine):
    actions = []
    states = machine.phase_states.filter(status=PhaseStatus.IN_PROGRESS).select_related("phase").order_by("phase__sequence", "phase__name")
    for state in states:
        if not can_operate_phase(user, state.phase.code):
            continue
        if state.phase.code == PhaseCode.PLANNER:
            actions.append({"label": "Assign serial", "href": f"/workflow/planner/?focus={machine.machine_id}"})
        elif state.phase.code == PhaseCode.PRODUCTION:
            actions.append({"label": "Allocate station", "href": f"/workflow/production/{machine.machine_id}/"})
        elif state.phase.code == PhaseCode.WAITING:
            actions.append({"label": "Assign test bay", "href": "/workflow/phase/WAITING/"})
        elif state.phase.code in PhaseCode.JOB_CARDS:
            actions.append({"label": f"Open {state.phase.name} job card", "href": f"/job-cards/{state.phase.code}/{machine.machine_id}/"})
        elif state.phase.code == PhaseCode.PLANNING:
            actions.append({"label": "Submit to production", "href": f"/machines/{machine.machine_id}/"})
    qc_done = (
        machine.status == MachineStatus.COMPLETED
        and can_operate_phase(user, PhaseCode.QC)
        and machine.phase_states.filter(phase__code=PhaseCode.QC, status=PhaseStatus.COMPLETED).exists()
    )
    if qc_done:
        actions.append({"label": "Edit QC record", "href": f"/job-cards/QC/{machine.machine_id}/"})
    return actions


@management_required
def machine_track(request):
    params = request.GET.copy()
    if not params.get("sort"):
        params["sort"] = "machine_id"
        params["dir"] = "asc"
    queryset = visible_machines(request.user).prefetch_related(
        "phase_states__phase", "phase_states__completed_by", "phase_states__started_by"
    )
    queryset = apply_sort(apply_machine_filters(queryset, params), params)
    page = paginate(request, queryset, size=50)
    for machine in page.object_list:
        _with_track(request.user, machine)
    return render(
        request,
        "machines/track.html",
        {
            "page": page,
            "querystring": querystring(request),
            "statuses": MachineStatus.CHOICES,
            "priorities": Priority.CHOICES,
            "station_groups": stations_by_line(),
            "phases": [
                ("PLANNING", "Planning"),
                ("PLANNER", "Serial"),
                ("PRODUCTION", "Production"),
                ("BUILD", "Assembly + Electrical"),
                ("TESTING", "Testing"),
                ("EOL", "EOL"),
                ("QC", "QC"),
            ],
            "filters": request.GET,
        },
    )


@login_required
def machine_list(request):
    queryset = visible_machines(request.user).prefetch_related("phase_states__phase")
    queryset = apply_sort(apply_machine_filters(queryset, request.GET), request.GET)
    page = paginate(request, queryset)
    for machine in page.object_list:
        machine.pipeline = pipeline_label(machine)
        machine.can_edit = can_edit_planning(request.user, machine)
        machine.can_delete = can_delete_machine(request.user, machine)
    return render(
        request,
        "machines/list.html",
        {
            "page": page,
            "querystring": querystring(request),
            "statuses": MachineStatus.CHOICES,
            "priorities": Priority.CHOICES,
            "station_groups": stations_by_line(),
            "phases": [
                ("PLANNING", "Planning"),
                ("PLANNER", "Serial"),
                ("PRODUCTION", "Production"),
                ("BUILD", "Assembly + Electrical"),
                ("TESTING", "Testing"),
                ("EOL", "EOL"),
                ("QC", "QC"),
            ],
            "filters": request.GET,
        },
    )


@roles_required(Roles.PLANNING_DATA_ENTRY)
def machine_create(request):
    form = PlanningForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        machine = register_machine(form.cleaned_data, request.user, submit=request.POST.get("action") == "submit")
        messages.success(request, f"{machine.machine_id} registered.")
        return redirect("machines:detail", machine.machine_id)
    return render(request, "machines/form.html", {"form": form, "mode": "create", "catalog_ready": PlanningCatalogItem.objects.exists()})


@roles_required(Roles.PLANNING_DATA_ENTRY)
def machine_bulk(request):
    formset = PlanningFormSet(request.POST or None, prefix="machines")
    if request.method == "POST" and formset.is_valid():
        created = []
        submit = request.POST.get("action") == "submit"
        for form in formset:
            if form.cleaned_data.get("blank"):
                continue
            created.append(register_machine(form.cleaned_data, request.user, submit=submit))
        if not created:
            messages.error(request, "Enter at least one machine.")
        else:
            messages.success(request, f"{len(created)} machine{'s' if len(created) != 1 else ''} registered.")
            return redirect("machines:list")
    return render(request, "machines/bulk.html", {"formset": formset, "catalog_ready": PlanningCatalogItem.objects.exists()})


@login_required
def machine_edit(request, machine_id):
    machine = _machine_or_404(request.user, machine_id)
    if not can_edit_planning(request.user, machine):
        raise PermissionDenied
    initial = {
        "company": machine.planning.company,
        "work_order": machine.planning.work_order,
        "ccn": machine.planning.ccn,
        "model_description": machine.planning.model_description,
        "machine_type": machine.planning.machine_type,
        "calibration": machine.planning.calibration,
        "shift": machine.planning.shift,
        "test_report_bar": machine.planning.test_report_bar,
        "export_packing_required": machine.planning.export_packing_required,
        "customer_inspection": machine.planning.customer_inspection,
        "customer_inspection_date": machine.planning.customer_inspection_date,
        "priority": machine.priority,
    }
    form = PlanningForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        update_planning(machine, form.cleaned_data, request.user)
        messages.success(request, "Planning data updated.")
        return redirect("machines:detail", machine.machine_id)
    return render(
        request,
        "machines/form.html",
        {"form": form, "mode": "edit", "machine": machine, "catalog_ready": PlanningCatalogItem.objects.exists()},
    )


@login_required
@require_POST
def machine_delete(request, machine_id):
    machine = _machine_or_404(request.user, machine_id)
    if not can_delete_machine(request.user, machine):
        raise PermissionDenied
    label = machine.machine_id
    log_audit(request.user, "machine.delete", instance=machine, changes={"machine_id": label}, request=request)
    with transaction.atomic():
        machine.job_card_submissions.update(supersedes=None)
        for attachment in list(machine.attachments.all()):
            if attachment.file:
                attachment.file.delete(save=False)
        machine.delete()
    messages.success(request, f"{label} was deleted.")
    return redirect("machines:list")


@login_required
def machine_detail(request, machine_id):
    machine = _machine_or_404(request.user, machine_id)
    try:
        return _machine_detail(request, machine)
    except Exception:
        import logging
        import traceback

        logging.getLogger("machines.detail").exception("machine_detail failed for %s", machine_id)
        # Temporary: show traceback so live PythonAnywhere 500s can be fixed quickly.
        if request.user.is_authenticated:
            from django.http import HttpResponse

            return HttpResponse(
                f"<pre>Machine detail error for {machine_id}\n\n{traceback.format_exc()}</pre>",
                status=500,
                content_type="text/html; charset=utf-8",
            )
        raise


@login_required
def machine_detail_probe(request, machine_id):
    """Step-by-step probe for live 500 diagnosis. Remove after the crash is fixed."""
    import traceback

    from django.http import JsonResponse

    machine = _machine_or_404(request.user, machine_id)
    steps = []

    def run(label, fn):
        try:
            value = fn()
            steps.append({"step": label, "ok": True, "detail": str(value)[:300]})
            return value
        except Exception as exc:
            steps.append({"step": label, "ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()})
            return None

    submissions = run("submissions", lambda: list(machine.job_card_submissions.select_related("operator", "template")))
    reworks = run("reworks", lambda: list(machine.reworks.select_related("assigned_phase", "rejected_phase", "rejected_by")))
    run("planning", lambda: machine.planning.work_order)
    run("pipeline", lambda: pipeline_label(machine))
    track = run("tracking_steps", lambda: tracking_steps(machine))
    run("with_track", lambda: _with_track(request.user, machine) and "ok")
    run("actions", lambda: _actions(request.user, machine))
    run("logo", current_logo)
    run("brand", lambda: static(brand_static(machine.planning.company)))
    run(
        "job_card_view",
        lambda: job_card_view(machine, submissions or [], track or [], reworks or [], until=None),
    )
    run("events", lambda: recent_events(machine))
    run("notes", lambda: list(machine.notes.select_related("author")))
    run("attachments", lambda: list(machine.attachments.select_related("uploaded_by")))
    run("progress", machine.progress_percent)
    run("can_edit", lambda: can_edit_planning(request.user, machine))
    run("can_reject", lambda: can_reject(request.user, machine))
    if any(not item["ok"] for item in steps):
        return JsonResponse({"machine_id": machine_id, "steps": steps}, status=500)
    try:
        response = _machine_detail(request, machine)
        steps.append({"step": "render", "ok": True, "detail": f"status={response.status_code}"})
    except Exception as exc:
        steps.append({"step": "render", "ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()})
        return JsonResponse({"machine_id": machine_id, "steps": steps}, status=500)
    return JsonResponse({"machine_id": machine_id, "steps": steps})


def _machine_detail(request, machine):
    submissions = machine.job_card_submissions.select_related("operator", "template").prefetch_related("responses__field", "attachments")
    reworks = machine.reworks.select_related("assigned_phase", "rejected_phase", "rejected_by").prefetch_related("actions")
    planning_state = machine.phase_states.filter(phase__code=PhaseCode.PLANNING).first()
    _with_track(request.user, machine)
    steps = machine.track_steps
    stage = request.GET.get("stage", "")
    card_meta = CARD_META.get(stage)
    until = limit_for_card(card_meta, machine) if card_meta else None
    stage_note = ""
    if card_meta and card_meta.get("limit"):
        limit = card_meta["limit"]
        if limit == "REWORK":
            stage_note = "This view shows the job card through the phase the machine was sent back to."
        else:
            stage_note = f"This view shows the job card through {STAGE_LABELS.get(limit, limit)}."
    return render(
        request,
        "machines/detail.html",
        {
            "machine": machine,
            "pipeline": pipeline_label(machine),
            "steps": steps,
            "logo": current_logo(),
            "brand_logo": static(brand_static(machine.planning.company)),
            "card": job_card_view(machine, submissions, steps, reworks, until=until),
            "stage": stage if card_meta else "",
            "stage_note": stage_note,
            "events": recent_events(machine),
            "event_label": event_label,
            "submissions": submissions,
            "reworks": reworks,
            "notes": machine.notes.select_related("author"),
            "attachments": machine.attachments.select_related("uploaded_by"),
            "actions": _actions(request.user, machine),
            "can_edit": can_edit_planning(request.user, machine),
            "can_delete": can_delete_machine(request.user, machine),
            "can_submit_planning": bool(
                planning_state
                and planning_state.status == PhaseStatus.IN_PROGRESS
                and can_operate_phase(request.user, PhaseCode.PLANNING)
                and (request.user.is_management or machine.created_by_id == request.user.id)
            ),
            "can_reject": can_reject(request.user, machine),
            "targets": reachable_rework_targets(machine) if can_reject(request.user, machine) else [],
            "progress": machine.progress_percent(),
        },
    )


@login_required
@require_POST
def machine_submit(request, machine_id):
    machine = _machine_or_404(request.user, machine_id)
    try:
        submit_planning(machine, request.user)
    except WorkflowError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"{machine.machine_id} submitted to the production leader.")
    return redirect("machines:detail", machine.machine_id)


@login_required
@require_POST
def bulk_submit(request):
    selected = request.POST.getlist("machines")
    done = 0
    for machine in visible_machines(request.user).filter(machine_id__in=selected):
        try:
            submit_planning(machine, request.user)
            done += 1
        except WorkflowError as exc:
            messages.error(request, f"{machine.machine_id}: {exc}")
    if done:
        messages.success(request, f"{done} machine{'s' if done != 1 else ''} submitted to the production leader.")
    return redirect("machines:list")


def _pass_ready(machine, code):
    if code == PhaseCode.PLANNER:
        return bool((machine.planner_serial or "").strip())
    if code == PhaseCode.PRODUCTION:
        return bool(machine.station_id)
    return True


@login_required
@require_POST
def pass_phase_view(request, machine_id, phase_code):
    machine = _machine_or_404(request.user, machine_id)
    try:
        pass_phase(machine, request.user, phase_code)
    except (WorkflowError, JobCardError) as exc:
        messages.error(request, str(exc))
    else:
        machine.refresh_from_db()
        if phase_code in {PhaseCode.ASSEMBLY, PhaseCode.ELECTRICAL}:
            other = PhaseCode.ELECTRICAL if phase_code == PhaseCode.ASSEMBLY else PhaseCode.ASSEMBLY
            other_open = machine.phase_states.filter(phase__code=other).exclude(status=PhaseStatus.COMPLETED).exists()
            if other_open:
                messages.success(request, f"{machine.machine_id} is approved. Testing opens after Assembly and Electrical are both done.")
            else:
                messages.success(request, f"{machine.machine_id} is approved. Assembly and Electrical are both done, so it is now in Testing.")
        elif machine.status == MachineStatus.COMPLETED:
            messages.success(request, f"{machine.machine_id} is approved and completed.")
        else:
            messages.success(request, f"{machine.machine_id} is approved and has moved to the next phase.")
    target = request.POST.get("next") or ""
    if target.startswith("/") and not target.startswith("//"):
        return redirect(target)
    return redirect("machines:detail", machine.machine_id)


@login_required
@require_POST
def set_test_area(request, machine_id):
    from workflow.engine import WorkflowError, assign_test_area

    machine = _machine_or_404(request.user, machine_id)
    if not can_operate_phase(request.user, PhaseCode.TESTING):
        raise PermissionDenied
    area = (request.POST.get("test_area") or "").strip()
    try:
        assign_test_area(machine, request.user, area)
        messages.success(request, f"{machine.machine_id} assigned to {area} and moved to Testing.")
    except WorkflowError as exc:
        messages.error(request, str(exc))
    target = request.POST.get("next") or ""
    if target.startswith("/") and not target.startswith("//"):
        return redirect(target)
    return redirect("workflow:phase", PhaseCode.TESTING)


@login_required
@require_POST
def add_note(request, machine_id):
    machine = _machine_or_404(request.user, machine_id)
    body = (request.POST.get("body") or "").strip()
    if body:
        MachineNote.objects.create(machine=machine, author=request.user, body=body[:2000])
        WorkflowEvent.objects.create(
            machine=machine,
            event_type="NOTE",
            actor=request.user,
            remarks=body[:2000],
        )
        log_audit(request.user, "machine.note", instance=machine, request=request)
        messages.success(request, "Note added.")
    return redirect("machines:detail", machine.machine_id)


@roles_required(Roles.PRODUCTION_LEADER)
def catalog_upload(request):
    form = ImportUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            result = replace_catalog(form.cleaned_data["source"], request.user)
        except CatalogError as exc:
            messages.error(request, str(exc))
        else:
            log_audit(
                request.user,
                "catalog.replace",
                changes=result,
                request=request,
            )
            messages.success(
                request,
                f"{result['created']} unique models are ready"
                + (f". {result['skipped']} rows were skipped." if result["skipped"] else "."),
            )
            return redirect("machines:catalog")
    query = (request.GET.get("q") or "").strip()
    items = PlanningCatalogItem.objects.all()
    if query:
        items = items.filter(
            Q(model_description__icontains=query) | Q(ccn__icontains=query) | Q(company__icontains=query) | Q(machine_type__icontains=query)
        )
    latest = PlanningCatalogItem.objects.select_related("uploaded_by").order_by("-uploaded_at").first()
    return render(
        request,
        "machines/catalog.html",
        {
            "form": form,
            "page": paginate(request, items, 25),
            "query": query,
            "querystring": querystring(request),
            "total": PlanningCatalogItem.objects.count(),
            "latest": latest,
        },
    )


@login_required
def catalog_lookup(request):
    items = [
        {"model": model, "ccn": ccn}
        for model, ccn in models_for(request.GET.get("company", ""), request.GET.get("type", ""))
    ]
    return JsonResponse({"items": items})


@management_required
def import_upload(request):
    form = ImportUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            batch, unknown = build_import_preview(form.cleaned_data["source"], request.user)
        except Exception:
            messages.error(request, "That workbook could not be read. Use the planning template and upload an .xlsx file.")
            return render(request, "machines/import_upload.html", {"form": form})
        if unknown:
            messages.warning(request, "Ignored columns: " + ", ".join(unknown[:8]))
        return redirect("machines:import_preview", batch.pk)
    return render(request, "machines/import_upload.html", {"form": form})


@management_required
def import_template(request):
    return FileResponse(planning_template_workbook(), as_attachment=True, filename="Planning_Data_Template.xlsx")


@management_required
def import_preview(request, batch_id):
    batch = get_object_or_404(ImportBatch, pk=batch_id)
    rows = list(batch.rows.all())
    return render(
        request,
        "machines/import_preview.html",
        {"batch": batch, "rows": rows, "models": batch.valid_count},
    )


@management_required
@require_POST
def import_confirm(request, batch_id):
    batch = get_object_or_404(ImportBatch, pk=batch_id)
    try:
        saved = confirm_import(batch, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("machines:import_preview", batch.pk)
    log_audit(request.user, "machine.import", instance=batch, changes={"models": saved}, request=request)
    messages.success(
        request,
        f"{saved} models are in the registration dropdown. Planning can select Brand, Type, Model description, and CCN. No machine was added or changed.",
    )
    return redirect("machines:catalog")


@management_required
def import_errors(request, batch_id):
    batch = get_object_or_404(ImportBatch, pk=batch_id)
    return FileResponse(error_workbook(batch), as_attachment=True, filename=f"import-errors-{batch.pk}.xlsx")


@management_required
def station_list(request):
    return render(request, "machines/stations.html", {"stations": ProductionStation.objects.all()})


@management_required
def station_edit(request, pk=None):
    station = get_object_or_404(ProductionStation, pk=pk) if pk else None
    form = StationForm(request.POST or None, instance=station)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        log_audit(request.user, "station.save", instance=saved, request=request)
        messages.success(request, f"Station {saved.code} saved.")
        return redirect("machines:stations")
    return render(request, "machines/station_form.html", {"form": form, "station": station})
