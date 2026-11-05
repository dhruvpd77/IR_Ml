from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import Department, SystemSetting, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Organisation", {"fields": ("role", "department", "employee_id", "phone", "designation")}),
    )
    list_display = ("username", "display_name", "role", "department", "is_active")
    list_filter = ("role", "department", "is_active")


admin.site.register(Department)
admin.site.register(SystemSetting)
