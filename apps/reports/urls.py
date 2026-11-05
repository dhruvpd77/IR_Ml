from django.urls import path

from reports import views

app_name = "reports"

urlpatterns = [
    path("", views.index, name="index"),
    path("export/excel/", views.export_excel, name="excel"),
    path("export/pdf/", views.export_pdf, name="pdf"),
    path("machine/<str:machine_id>/excel/", views.machine_excel, name="machine_excel"),
    path("machine/<str:machine_id>/pdf/", views.machine_pdf, name="machine_pdf"),
]
