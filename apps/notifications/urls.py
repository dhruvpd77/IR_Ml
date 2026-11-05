from django.urls import path

from notifications import views

app_name = "notifications"

urlpatterns = [
    path("", views.notification_list, name="list"),
    path("<int:pk>/", views.open_notification, name="open"),
    path("read-all/", views.read_all, name="read_all"),
    path("unread-count/", views.unread_count, name="unread_count"),
]
