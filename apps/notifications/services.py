from django.urls import reverse

from notifications.models import Notification


def notify_roles(roles, *, title, body, url="", machine=None, exclude_user=None, category="workflow"):
    from accounts.models import User

    queryset = User.objects.filter(is_active=True, role__in=list(roles))
    if exclude_user is not None and getattr(exclude_user, "is_authenticated", False):
        queryset = queryset.exclude(pk=exclude_user.pk)
    rows = [
        Notification(
            recipient=user,
            title=title[:180],
            body=body,
            url=url,
            category=category,
            machine=machine,
        )
        for user in queryset
    ]
    if rows:
        Notification.objects.bulk_create(rows)


def machine_path(machine):
    return reverse("machines:detail", args=[machine.machine_id])


def machine_label(machine):
    planning = getattr(machine, "planning", None)
    if planning is None:
        return machine.machine_id
    return f"{machine.machine_id} · WO {planning.work_order} · {planning.model_description}"
