from django.urls import path

from workflow import views

app_name = "workflow"

urlpatterns = [
    path("planner/", views.planner_queue, name="planner"),
    path("production/", views.production_queue, name="production"),
    path("production/<str:machine_id>/", views.production_machine, name="production_machine"),
    path("phase/<str:phase_code>/", views.phase_queue, name="phase"),
    path("phases/", views.phase_settings, name="phases"),
    path("phases/<int:pk>/", views.phase_edit, name="phase_edit"),
]
