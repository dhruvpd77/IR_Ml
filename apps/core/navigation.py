from django.urls import reverse

from core.constants import PHASE_ROLE, PhaseCode, Roles


def _visible(user, item):
    if item.get("hide_management") and user.is_management:
        return False
    if item.get("super_admin") and not (user.is_superuser or user.role == Roles.SUPER_ADMIN):
        return False
    if item.get("management") and not user.is_management:
        return False
    roles = item.get("roles")
    if roles is None:
        return True
    return user.is_management or user.role in roles


NAV_ITEMS = [
    {"label": "Dashboard", "url": "core:dashboard", "icon": "layout-dashboard", "highlight": ["dashboard"], "hide_management": True},
    {"label": "Monthly dashboard", "url": "core:monthly", "icon": "layout-dashboard", "management": True, "highlight": ["monthly"]},
    {"label": "Daily dashboard", "url": "core:daily", "icon": "calendar-days", "management": True, "highlight": ["daily"]},
    {"label": "Tentative planning", "url": "core:tentative", "icon": "calendar-range", "super_admin": True, "highlight": ["tentative"]},
    {"label": "Machine Analytics", "url": "core:analytics", "icon": "layout-grid", "management": True, "highlight": ["analytics"]},
    {"label": "All Machines", "url": "machines:list", "icon": "cpu", "highlight": ["list", "detail", "edit", "create", "bulk"]},
    {"label": "Track", "url": "machines:track", "icon": "route", "management": True, "highlight": ["track"]},
    {"label": "Register Machine", "url": "machines:create", "icon": "plus-circle", "roles": {Roles.PLANNING_DATA_ENTRY}},
    {"label": "Planning Excel", "url": "machines:import", "icon": "file-spreadsheet", "management": True, "highlight": ["import", "import_preview"]},
    {"label": "Model Catalog", "url": "machines:catalog", "icon": "file-spreadsheet", "roles": {Roles.PRODUCTION_LEADER}, "highlight": ["catalog"]},
    {"label": "Serial numbers", "url": "workflow:planner", "icon": "hash", "roles": {Roles.PRODUCTION_LEADER}, "highlight": ["planner"]},
    {"label": "Stations", "url": "workflow:production", "icon": "factory", "roles": {Roles.PRODUCTION_LEADER}, "highlight": ["production", "production_machine"]},
    {"label": "Assembly", "url": "workflow:phase", "args": ["ASSEMBLY"], "icon": "wrench", "roles": {Roles.ASSEMBLY}},
    {"label": "Electrical", "url": "workflow:phase", "args": ["ELECTRICAL"], "icon": "zap", "roles": {Roles.ELECTRICAL}},
    {"label": "Testing", "url": "workflow:phase", "args": ["TESTING"], "icon": "gauge", "roles": {Roles.TESTING}},
    {"label": "End of Line", "url": "workflow:phase", "args": ["EOL"], "icon": "package-check", "roles": {Roles.EOL}},
    {"label": "Quality Control", "url": "workflow:phase", "args": ["QC"], "icon": "shield-check", "roles": {Roles.QC}},
    {"label": "Rework", "url": "rework:list", "icon": "rotate-ccw", "highlight": ["list", "detail"]},
    {"label": "Reports", "url": "reports:index", "icon": "bar-chart-3", "roles": {Roles.PRODUCTION_LEADER, Roles.QC}},
    {"label": "Job Card Setup", "url": "jobcards:templates", "icon": "clipboard-list", "management": True, "highlight": ["templates", "template_edit", "template_create"]},
    {"label": "Users", "url": "accounts:users", "icon": "users", "management": True, "highlight": ["users", "user_create", "user_edit"]},
    {"label": "Stations", "url": "machines:stations", "icon": "map-pin", "management": True, "highlight": ["stations", "station_create", "station_edit"]},
    {"label": "Phases", "url": "workflow:phases", "icon": "git-branch", "management": True, "highlight": ["phases", "phase_edit"]},
    {"label": "Settings", "url": "accounts:settings", "icon": "settings", "management": True},
    {"label": "Audit Log", "url": "audit:list", "icon": "scroll-text", "management": True},
]


def navigation_for(user, match):
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
        items.append({"label": item["label"], "href": href, "icon": item["icon"], "active": active})
    return items


def home_phase(user):
    if user.is_management:
        return None
    if user.role == Roles.PRODUCTION_LEADER:
        return PhaseCode.PRODUCTION
    for phase, role in PHASE_ROLE.items():
        if user.role == role:
            return phase
    return None
