from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core import views as core_views

admin.site.site_header = "Ingersoll Rand ROTARY"
admin.site.site_title = "IR Rotary"
admin.site.index_title = "Administration"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", core_views.health, name="health"),
    path("sw.js", core_views.service_worker, name="service_worker"),
    path("manifest.webmanifest", core_views.web_manifest, name="web_manifest"),
    path("", include("core.urls")),
    path("", include("accounts.urls")),
    path("machines/", include("machines.urls")),
    path("workflow/", include("workflow.urls")),
    path("job-cards/", include("jobcards.urls")),
    path("rework/", include("rework.urls")),
    path("reports/", include("reports.urls")),
    path("notifications/", include("notifications.urls")),
    path("audit/", include("audit.urls")),
    path("api/v1/", include("core.api_urls")),
]

handler403 = "core.views.permission_denied_page"
handler404 = "core.views.not_found_page"

if settings.DEBUG or settings.SERVE_MEDIA:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
