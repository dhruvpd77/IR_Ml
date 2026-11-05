from django.urls import path

from rework import views

app_name = "rework"

urlpatterns = [
    path("", views.rework_list, name="list"),
    path("new/<str:machine_id>/", views.rework_create, name="create"),
    path("<int:pk>/", views.rework_detail, name="detail"),
]
