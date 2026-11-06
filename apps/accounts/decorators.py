from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def super_admin_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not (user.is_superuser or user.role == "SUPER_ADMIN"):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def management_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_management:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def board_viewer_required(view):
    """Management plus General User (big-screen dashboards / analytics / slideshow)."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_board_viewer:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def roles_required(*roles):
    allowed = set(roles)

    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.user.is_management or request.user.role in allowed:
                return view(request, *args, **kwargs)
            raise PermissionDenied
        return wrapper

    return decorator
