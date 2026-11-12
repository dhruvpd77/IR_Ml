from accounts.models import get_setting
from core.navigation import navigation_for as build_navigation
from notifications.models import Notification


def _nav_payload(user, match):
    navigation = build_navigation(user, match)
    if isinstance(navigation, dict):
        items = list(navigation.get("items") or [])
        sections = list(navigation.get("sections") or [])
        if sections:
            return items, sections
    else:
        items = list(navigation or [])
    sections = []
    for entry in items:
        label = entry.get("section") or "Menu"
        if not sections or sections[-1]["label"] != label:
            sections.append({"label": label, "items": []})
        sections[-1]["items"].append(entry)
    return items, sections


def shell(request):
    if not request.user.is_authenticated:
        return {"company_name": "Ingersoll Rand"}
    unread = Notification.objects.filter(recipient=request.user, is_read=False).count()
    embed = (request.GET.get("embed") or "").strip() == "1"
    nav_items, nav_sections = _nav_payload(request.user, request.resolver_match)
    return {
        "company_name": get_setting("company_name", "Ingersoll Rand"),
        "nav_items": nav_items,
        "nav_sections": nav_sections,
        "unread_notifications": unread,
        "embed_mode": embed,
    }
