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
from machines.forms import ChecklistUploadForm, ImportUploadForm, PlanningForm, PlanningFormSet, StationForm
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
        if state.phase.code in {PhaseCode.PLANNER, PhaseCode.PRODUCTION}:
            if not any(item.get("label") == "Assign serial & station" for item in actions):
                actions.append({"label": "Assign serial & station", "href": f"/workflow/planner/?focus={machine.machine_id}"})
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
    body = (request.POST.get("body") or "").strip().upper()
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
            word_count = PlanningCatalogItem.objects.filter(job_card_format="word").exclude(job_card_key="").count()
            if word_count:
                try:
                    from jobcards.word_checklist_import import import_word_job_cards

                    word_result = import_word_job_cards()
                    word_msg = (
                        f"Word job cards: {word_result['created']} created, "
                        f"{word_result['updated']} refreshed."
                    )
                    if word_result["missing"]:
                        messages.warning(
                            request,
                            word_msg + f" Missing files: {', '.join(word_result['missing'])}.",
                        )
                    else:
                        messages.success(request, word_msg)
                except Exception as exc:
                    messages.warning(request, f"Model list saved, but Word job cards failed: {exc}")
            return redirect("machines:catalog")
    query = (request.GET.get("q") or "").strip()
    brand = (request.GET.get("brand") or "").strip()
    machine_type = (request.GET.get("type") or "").strip()
    model_q = (request.GET.get("model") or "").strip()
    ccn_q = (request.GET.get("ccn") or "").strip()
    job_card_q = (request.GET.get("job_card") or "").strip()
    format_q = (request.GET.get("format") or "").strip().lower()
    items = PlanningCatalogItem.objects.all()
    if query:
        items = items.filter(
            Q(model_description__icontains=query)
            | Q(ccn__icontains=query)
            | Q(company__icontains=query)
            | Q(machine_type__icontains=query)
            | Q(job_card_key__icontains=query)
        )
    if brand:
        items = items.filter(company=brand)
    if machine_type:
        items = items.filter(machine_type=machine_type)
    if model_q:
        items = items.filter(model_description__icontains=model_q)
    if ccn_q:
        items = items.filter(ccn__icontains=ccn_q)
    if job_card_q == "__none__":
        items = items.filter(job_card_key="")
    elif job_card_q:
        items = items.filter(job_card_key=job_card_q)
    if format_q in {"excel", "word"}:
        items = items.filter(job_card_format=format_q)
    items = items.order_by("company", "machine_type", "model_description")
    latest = PlanningCatalogItem.objects.select_related("uploaded_by").order_by("-uploaded_at").first()
    from jobcards.models import JobCardTemplate

    checklist_count = (
        JobCardTemplate.objects.filter(phase_code__in=["ASSEMBLY", "TESTING"], is_active=True)
        .exclude(checklist_key="")
        .values("checklist_key")
        .distinct()
        .count()
    )
    brands = list(PlanningCatalogItem.objects.order_by("company").values_list("company", flat=True).distinct())
    types = list(PlanningCatalogItem.objects.order_by("machine_type").values_list("machine_type", flat=True).distinct())
    job_cards = list(
        PlanningCatalogItem.objects.exclude(job_card_key="")
        .order_by("job_card_key")
        .values_list("job_card_key", flat=True)
        .distinct()
    )
    return render(
        request,
        "machines/catalog.html",
        {
            "form": form,
            "checklist_form": ChecklistUploadForm(),
            "page": paginate(request, items, 25),
            "query": query,
            "filter_brand": brand,
            "filter_type": machine_type,
            "filter_model": model_q,
            "filter_ccn": ccn_q,
            "filter_job_card": job_card_q,
            "filter_format": format_q,
            "filter_brands": brands,
            "filter_types": types,
            "filter_job_cards": job_cards,
            "querystring": querystring(request),
            "total": PlanningCatalogItem.objects.count(),
            "filtered_total": items.count(),
            "latest": latest,
            "checklist_count": checklist_count,
        },
    )


@roles_required(Roles.PRODUCTION_LEADER)
def catalog_job_card(request):
    """Read-only preview of Assembly + Testing fields for a catalog Job Card Detail name."""
    from machines.catalog import normalize_job_card_format, normalize_job_card_key, resolve_checklist_key
    from jobcards.models import JobCardTemplate

    catalog_key = normalize_job_card_key(request.GET.get("key") or "")
    if not catalog_key:
        messages.error(request, "Choose a job card name from the catalog.")
        return redirect("machines:catalog")
    sample = PlanningCatalogItem.objects.filter(job_card_key=catalog_key).order_by("pk").first()
    source_format = normalize_job_card_format(getattr(sample, "job_card_format", "") or "")
    resolved = resolve_checklist_key(catalog_key, source_format) or catalog_key
    lookup_keys = []
    for key in (catalog_key, resolved):
        if key and key.lower() not in {item.lower() for item in lookup_keys}:
            lookup_keys.append(key)
    phases = []
    for phase_code, title in (("ASSEMBLY", "Assembly"), ("TESTING", "Testing")):
        template = None
        for key in lookup_keys:
            template = (
                JobCardTemplate.objects.filter(phase_code=phase_code, checklist_key__iexact=key, is_active=True)
                .order_by("-version")
                .first()
            )
            if template is None:
                for candidate in JobCardTemplate.objects.filter(phase_code=phase_code, is_active=True).order_by(
                    "-version"
                ):
                    if normalize_job_card_key(candidate.checklist_key).lower() == key.lower():
                        template = candidate
                        break
            if template is not None:
                break
        fields = list(template.active_fields()) if template else []
        sections = []
        current = None
        for field in fields:
            if current is None or current["name"] != field.section:
                current = {"name": field.section or "Fields", "fields": []}
                sections.append(current)
            current["fields"].append(field)
        phases.append(
            {
                "code": phase_code,
                "title": title,
                "template": template,
                "sections": sections,
                "field_count": len(fields),
            }
        )
    model_count = PlanningCatalogItem.objects.filter(job_card_key=catalog_key).count()
    return render(
        request,
        "machines/catalog_job_card.html",
        {
            "catalog_key": catalog_key,
            "resolved_key": resolved,
            "source_format": source_format,
            "aliased": resolved.lower() != catalog_key.lower(),
            "phases": phases,
            "model_count": model_count,
            "missing": all(phase["template"] is None for phase in phases),
        },
    )


@roles_required(Roles.PRODUCTION_LEADER)
@require_POST
def checklist_upload(request):
    """Re-import UPDATED Production Checklists so Assembly/Testing fields match the Excel."""
    import tempfile
    from pathlib import Path

    from jobcards.checklist_import import import_checklists_workbook

    form = ChecklistUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Upload an Excel .xlsx Production Checklists workbook.")
        return redirect("machines:catalog")
    upload = form.cleaned_data["source"]
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        for chunk in upload.chunks():
            tmp.write(chunk)
        tmp_path = Path(tmp.name)
    try:
        result = import_checklists_workbook(tmp_path)
    except Exception as exc:
        messages.error(request, f"Checklist import failed: {exc}")
        return redirect("machines:catalog")
    finally:
        tmp_path.unlink(missing_ok=True)
    log_audit(
        request.user,
        "checklists.import",
        changes={"created": result["created"], "updated": result["updated"], "sheets": result["sheets"]},
        request=request,
    )
    messages.success(
        request,
        f"Job cards updated from {result['sheets']} sheets: "
        f"{result['created']} created, {result['updated']} refreshed.",
    )
    return redirect("machines:catalog")


@roles_required(Roles.PRODUCTION_LEADER)
@require_POST
def word_checklist_import_view(request):
    """Load Assembly/Testing cards from jobcard_word_file for Word-tagged catalog models."""
    from jobcards.word_checklist_import import import_word_job_cards

    try:
        result = import_word_job_cards()
    except Exception as exc:
        messages.error(request, f"Word job card import failed: {exc}")
        return redirect("machines:catalog")
    log_audit(
        request.user,
        "checklists.word_import",
        changes={
            "created": result["created"],
            "updated": result["updated"],
            "missing": result["missing"],
            "keys": result["keys"],
        },
        request=request,
    )
    msg = (
        f"Word job cards: {result['created']} created, {result['updated']} refreshed "
        f"({result['keys']} Word catalog names)."
    )
    if result["missing"]:
        messages.warning(
            request,
            msg + f" Missing files for: {', '.join(result['missing'])}.",
        )
    else:
        messages.success(request, msg)
    return redirect("machines:catalog")


@login_required
def catalog_lookup(request):
    items = [
        {
            "model": model,
            "ccn": ccn,
            "job_card": job_card or "",
            "job_card_format": (job_card_format or ""),
        }
        for model, ccn, job_card, job_card_format in models_for(
            request.GET.get("company", ""), request.GET.get("type", "")
        )
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
