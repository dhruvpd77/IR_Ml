from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def management_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_management:
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
