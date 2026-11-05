from django.db import models

from accounts.models import User
from machines.models import Machine


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=180)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=240, blank=True)
    category = models.CharField(max_length=40, default="workflow")
    machine = models.ForeignKey(Machine, null=True, blank=True, on_delete=models.CASCADE, related_name="notifications")
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title
