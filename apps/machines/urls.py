from django.urls import path

from machines import views

app_name = "machines"

urlpatterns = [
    path("", views.machine_list, name="list"),
    path("new/", views.machine_create, name="create"),
    path("bulk/", views.machine_bulk, name="bulk"),
    path("submit/", views.bulk_submit, name="bulk_submit"),
    path("catalog/", views.catalog_upload, name="catalog"),
    path("catalog/lookup/", views.catalog_lookup, name="catalog_lookup"),
    path("import/", views.import_upload, name="import"),
    path("import/template/", views.import_template, name="import_template"),
    path("import/<int:batch_id>/", views.import_preview, name="import_preview"),
    path("import/<int:batch_id>/confirm/", views.import_confirm, name="import_confirm"),
    path("import/<int:batch_id>/errors/", views.import_errors, name="import_errors"),
    path("stations/", views.station_list, name="stations"),
    path("stations/new/", views.station_edit, name="station_create"),
    path("stations/<int:pk>/", views.station_edit, name="station_edit"),
    path("track/", views.machine_track, name="track"),
    path("<str:machine_id>/pass/<str:phase_code>/", views.pass_phase_view, name="pass_phase"),
    path("<str:machine_id>/", views.machine_detail, name="detail"),
    path("<str:machine_id>/edit/", views.machine_edit, name="edit"),
    path("<str:machine_id>/delete/", views.machine_delete, name="delete"),
    path("<str:machine_id>/submit/", views.machine_submit, name="submit"),
    path("<str:machine_id>/notes/", views.add_note, name="add_note"),
]
