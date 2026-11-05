from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.http import paginate, querystring
from notifications.models import Notification


@login_required
def notification_list(request):
    queryset = Notification.objects.filter(recipient=request.user).select_related("machine")
    return render(
        request,
        "notifications/list.html",
        {"page": paginate(request, queryset), "querystring": querystring(request)},
    )


@login_required
def open_notification(request, pk):
    item = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if not item.is_read:
        item.is_read = True
        item.save(update_fields=["is_read"])
    return redirect(item.url or "notifications:list")


@login_required
@require_POST
def read_all(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return redirect("notifications:list")


@login_required
def unread_count(request):
    return JsonResponse({"unread": Notification.objects.filter(recipient=request.user, is_read=False).count()})
