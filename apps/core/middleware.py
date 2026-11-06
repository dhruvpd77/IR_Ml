from django.shortcuts import redirect

from core.bootstrap import ensure_reference_data
from core.constants import Roles

BOARD_PREFIXES = (
    "/dashboard/monthly",
    "/dashboard/daily",
    "/analytics",
    "/slideshow",
    "/accounts/logout",
    "/accounts/login",
    "/notifications",
    "/health",
    "/static",
    "/media",
)


class ReferenceDataMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith("/static/") or path.startswith("/health"):
            return self.get_response(request)
        ensure_reference_data()
        return self.get_response(request)


class GeneralUserBoardMiddleware:
    """General User may only open the live boards and slideshow."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and getattr(user, "role", None) == Roles.GENERAL_USER:
            path = request.path or "/"
            if path == "/" or any(path.startswith(prefix) for prefix in BOARD_PREFIXES):
                return self.get_response(request)
            # Allow dashboard card drill-downs from monthly/daily boards.
            if path.startswith("/dashboard/"):
                return self.get_response(request)
            return redirect("core:slideshow")
        return self.get_response(request)
