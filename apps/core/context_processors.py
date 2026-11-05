from accounts.models import get_setting
from core.navigation import navigation_for
from notifications.models import Notification


def shell(request):
    if not request.user.is_authenticated:
        return {"company_name": "Ingersoll Rand"}
    unread = Notification.objects.filter(recipient=request.user, is_read=False).count()
    return {
        "company_name": get_setting("company_name", "Ingersoll Rand"),
        "nav_items": navigation_for(request.user, request.resolver_match),
        "unread_notifications": unread,
    }
