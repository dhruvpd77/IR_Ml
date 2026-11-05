from django.urls import path

from jobcards import views

app_name = "jobcards"

urlpatterns = [
    path("", views.template_list, name="templates"),
    path("new/", views.template_edit, name="template_create"),
    path("<int:pk>/edit/", views.template_edit, name="template_edit"),
    path("<int:pk>/version/", views.template_version, name="template_version"),
    path("<int:pk>/import/", views.template_import, name="template_import"),
    path("<int:template_id>/fields/new/", views.field_edit, name="field_create"),
    path("<int:template_id>/fields/<int:pk>/", views.field_edit, name="field_edit"),
    path("fields/<int:pk>/toggle/", views.field_toggle, name="field_toggle"),
    path("fields/<int:pk>/move/", views.field_move, name="field_move"),
    path("submissions/<int:pk>/", views.submission_detail, name="submission"),
    path("submissions/<int:pk>/revise/", views.revise, name="revise"),
    path("attachments/<int:pk>/", views.attachment, name="attachment"),
    path("qc-videos/<str:machine_id>/", views.qc_video_upload, name="qc_video_upload"),
    path("qc-videos/<str:machine_id>/<int:pk>/remove/", views.qc_video_remove, name="qc_video_remove"),
    path("<str:phase_code>/<str:machine_id>/", views.fill, name="fill"),
]
