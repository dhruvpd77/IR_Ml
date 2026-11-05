from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render

from accounts.decorators import management_required
from audit.models import AuditLog
from core.http import paginate, querystring


@management_required
def audit_list(request):
    queryset = AuditLog.objects.select_related("user")
    query = (request.GET.get("q") or "").strip()
    if query:
        queryset = queryset.filter(Q(action__icontains=query) | Q(object_repr__icontains=query) | Q(user__username__icontains=query))
    return render(
        request,
        "audit/list.html",
        {"page": paginate(request, queryset), "querystring": querystring(request), "query": query},
    )
