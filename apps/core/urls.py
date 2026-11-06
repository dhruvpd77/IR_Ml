from django.urls import path

from core import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("dashboard/monthly/", views.monthly_dashboard, name="monthly"),
    path("dashboard/daily/", views.daily_dashboard, name="daily"),
    path("dashboard/tentative/", views.tentative_plan, name="tentative"),
    path("dashboard/phase/<slug:key>/", views.department_card, name="department_card"),
    path("dashboard/<slug:key>/", views.dashboard_card, name="dashboard_card"),
    path("analytics/", views.machine_analytics, name="analytics"),
    path("slideshow/", views.dashboard_slideshow, name="slideshow"),
]
