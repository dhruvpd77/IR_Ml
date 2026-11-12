from django.db.models import Count
from django.urls import reverse

from core.constants import PHASE_ROLE, PhaseCode, PhaseStatus, Roles


BOARD_URLS = {"core:monthly", "core:daily", "core:analytics", "core:details_analytics", "core:slideshow"}


def _visible(user, item):
    if getattr(user, "is_general_user", False):
        return item["url"] in BOARD_URLS
    if item.get("hide_management") and user.is_management:
        return False
    if item.get("super_admin") and not (user.is_superuser or user.role == Roles.SUPER_ADMIN):
        return False
    if item.get("management") and not user.is_management:
        roles = item.get("roles") or set()
        if user.role not in roles:
            return False
    roles = item.get("roles")
    if roles is None:
        return True
    return user.is_management or user.role in roles


NAV_ITEMS = [
    {"label": "Dashboard", "url": "core:dashboard", "icon": "layout-dashboard", "highlight": ["dashboard"], "hide_management": True, "section": "Overview"},
    {"label": "Monthly dashboard", "url": "core:monthly", "icon": "layout-dashboard", "management": True, "roles": {Roles.GENERAL_USER}, "highlight": ["monthly"], "section": "Overview"},
    {"label": "Daily dashboard", "url": "core:daily", "icon": "calendar-days", "management": True, "roles": {Roles.GENERAL_USER}, "highlight": ["daily"], "section": "Overview"},
    {"label": "Tentative planning", "url": "core:tentative", "icon": "calendar-range", "super_admin": True, "highlight": ["tentative"], "section": "Overview"},
    {"label": "Machine Analytics", "url": "core:analytics", "icon": "layout-grid", "management": True, "roles": {Roles.GENERAL_USER}, "highlight": ["analytics"], "section": "Overview"},
    {"label": "Details Analytics", "url": "core:details_analytics", "icon": "bar-chart-2", "management": True, "roles": {Roles.GENERAL_USER}, "highlight": ["details_analytics"], "section": "Overview"},
    {"label": "Slideshow", "url": "core:slideshow", "icon": "monitor-play", "management": True, "roles": {Roles.GENERAL_USER}, "highlight": ["slideshow"], "section": "Overview"},
    {"label": "All Machines", "url": "machines:list", "icon": "cpu", "highlight": ["list", "detail", "edit", "create", "bulk"], "section": "Machines"},
    {
        "label": "History of Machine",
        "url": "machines:history",
        "icon": "history",
        "highlight": ["history", "history_timeline", "history_jobcard"],
        "section": "Machines",
    },
    {"label": "Track", "url": "machines:track", "icon": "route", "management": True, "highlight": ["track"], "section": "Machines"},
    {"label": "Register Machine", "url": "machines:create", "icon": "plus-circle", "roles": {Roles.PLANNING_DATA_ENTRY}, "section": "Machines"},
    {"label": "Planning Excel", "url": "machines:import", "icon": "file-spreadsheet", "management": True, "highlight": ["import", "import_preview"], "section": "Machines"},
    {"label": "Model Catalog", "url": "machines:catalog", "icon": "file-spreadsheet", "roles": {Roles.PRODUCTION_LEADER}, "highlight": ["catalog"], "section": "Machines"},
    {
        "label": "Serial numbers",
        "url": "workflow:planner",
        "icon": "hash",
        "roles": {Roles.PRODUCTION_LEADER},
        "highlight": ["planner", "production", "production_machine"],
        "count": "planner",
        "section": "Shop floor",
    },
    {"label": "Assembly", "url": "workflow:phase", "args": ["ASSEMBLY"], "icon": "wrench", "roles": {Roles.ASSEMBLY}, "count": "ASSEMBLY", "section": "Shop floor"},
    {"label": "Electrical", "url": "workflow:phase", "args": ["ELECTRICAL"], "icon": "zap", "roles": {Roles.ELECTRICAL}, "count": "ELECTRICAL", "section": "Shop floor"},
    {"label": "Waiting Area", "url": "workflow:phase", "args": ["WAITING"], "icon": "hourglass", "roles": {Roles.TESTING}, "count": "WAITING", "section": "Shop floor"},
    {"label": "Testing", "url": "workflow:phase", "args": ["TESTING"], "icon": "gauge", "roles": {Roles.TESTING}, "count": "TESTING", "section": "Shop floor"},
    {"label": "End of Line", "url": "workflow:phase", "args": ["EOL"], "icon": "package-check", "roles": {Roles.EOL}, "count": "EOL", "section": "Shop floor"},
    {"label": "Quality Control", "url": "workflow:phase", "args": ["QC"], "icon": "shield-check", "roles": {Roles.QC}, "count": "QC", "section": "Shop floor"},
    {"label": "Rework", "url": "rework:list", "icon": "rotate-ccw", "highlight": ["list", "detail", "resolve"], "count": "rework", "section": "Shop floor"},
    {"label": "Reports", "url": "reports:index", "icon": "bar-chart-3", "roles": {Roles.PRODUCTION_LEADER, Roles.QC}, "section": "Shop floor"},
    {"label": "Job Card Setup", "url": "jobcards:templates", "icon": "clipboard-list", "management": True, "highlight": ["templates", "template_edit", "template_create"], "section": "Admin"},
    {"label": "Users", "url": "accounts:users", "icon": "users", "management": True, "highlight": ["users", "user_create", "user_edit"], "section": "Admin"},
    {"label": "Stations", "url": "machines:stations", "icon": "map-pin", "management": True, "highlight": ["stations", "station_create", "station_edit"], "section": "Admin"},
    {"label": "Phases", "url": "workflow:phases", "icon": "git-branch", "management": True, "highlight": ["phases", "phase_edit"], "section": "Admin"},
    {"label": "Settings", "url": "accounts:settings", "icon": "settings", "management": True, "section": "Admin"},
    {"label": "Audit Log", "url": "audit:list", "icon": "scroll-text", "management": True, "section": "Admin"},
]


def queue_counts_for(user):
    """Open queue sizes for sidebar badges (phase work + open rework)."""
    from machines.services import visible_machines
    from rework.models import ReworkRequest
    from workflow.models import MachinePhaseState

    counts = {}
    machines = visible_machines(user)
    phase_codes = [
        PhaseCode.ASSEMBLY,
        PhaseCode.ELECTRICAL,
        PhaseCode.WAITING,
        PhaseCode.TESTING,
        PhaseCode.EOL,
        PhaseCode.QC,
        PhaseCode.PLANNER,
        PhaseCode.PRODUCTION,
    ]
    rows = (
        MachinePhaseState.objects.filter(
            machine__in=machines,
            status=PhaseStatus.IN_PROGRESS,
            phase__code__in=phase_codes,
        )
        .values("phase__code")
        .annotate(total=Count("id"))
    )
    for row in rows:
        counts[row["phase__code"]] = row["total"]

    planner_open = counts.get(PhaseCode.PLANNER, 0) + counts.get(PhaseCode.PRODUCTION, 0)
    counts["planner"] = planner_open

    rework_qs = ReworkRequest.objects.filter(status=ReworkRequest.Status.OPEN, machine__in=machines)
    if not user.is_management and user.role != Roles.QC:
        if getattr(user, "department_id", None):
            rework_qs = rework_qs.filter(assigned_phase__department_id=user.department_id)
        elif user.role == Roles.TESTING:
            rework_qs = rework_qs.filter(assigned_phase__code__in=[PhaseCode.WAITING, PhaseCode.TESTING])
        elif user.role == Roles.PRODUCTION_LEADER:
            rework_qs = rework_qs.filter(
                assigned_phase__code__in=[PhaseCode.PLANNER, PhaseCode.PRODUCTION]
            )
        else:
            role_phases = [code for code, role in PHASE_ROLE.items() if role == user.role]
            rework_qs = rework_qs.filter(assigned_phase__code__in=role_phases) if role_phases else rework_qs.none()
    counts["rework"] = rework_qs.count()
    return counts


def navigation_for(user, match):
    counts = queue_counts_for(user) if getattr(user, "is_authenticated", False) else {}
    items = []
    for item in NAV_ITEMS:
        if not _visible(user, item):
            continue
        href = reverse(item["url"], args=item.get("args") or [])
        url_name = item["url"].split(":")[-1]
        active = False
        if match:
            highlights = item.get("highlight") or [url_name]
            same_name = match.url_name in highlights
            if item.get("args"):
                active = same_name and match.kwargs.get("phase_code") == item["args"][0]
            elif url_name == "list" and item["url"] == "rework:list":
                active = match.namespace == "rework" and match.url_name in highlights
            elif url_name == "list" and item["url"] == "machines:list":
                active = match.namespace == "machines" and match.url_name in highlights
            else:
                active = match.namespace == item["url"].split(":")[0] and same_name
        count_key = item.get("count")
        count = counts.get(count_key, 0) if count_key else 0
        items.append(
            {
                "label": item["label"],
                "href": href,
                "icon": item["icon"],
                "active": active,
                "count": count,
                "section": item.get("section") or "Menu",
            }
        )
    sections = []
    for entry in items:
        if not sections or sections[-1]["label"] != entry["section"]:
            sections.append({"label": entry["section"], "items": []})
        sections[-1]["items"].append(entry)
    return {"items": items, "sections": sections}


def home_phase(user):
    if user.is_management or getattr(user, "is_general_user", False):
        return None
    if user.role == Roles.PRODUCTION_LEADER:
        return PhaseCode.PLANNER
    if user.role == Roles.TESTING:
        return PhaseCode.WAITING
    for phase, role in PHASE_ROLE.items():
        if user.role == role:
            return phase
    return None
