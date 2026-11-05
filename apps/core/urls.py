from django.urls import path

from core import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("dashboard/<slug:key>/", views.dashboard_card, name="dashboard_card"),
    path("analytics/", views.machine_analytics, name="analytics"),
]
