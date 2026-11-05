from django.contrib.auth.models import AbstractUser
from django.db import models

from core.constants import DEPARTMENTS, ROLE_DEPARTMENT, Roles


class Department(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPER_ADMIN = Roles.SUPER_ADMIN, "Super Admin"
        ADMIN = Roles.ADMIN, "Admin"
        PLANNING_DATA_ENTRY = Roles.PLANNING_DATA_ENTRY, "Planning Data Entry"
        PRODUCTION_LEADER = Roles.PRODUCTION_LEADER, "Production Leader"
        ASSEMBLY = Roles.ASSEMBLY, "Assembly"
        ELECTRICAL = Roles.ELECTRICAL, "Electrical"
        TESTING = Roles.TESTING, "Testing"
        EOL = Roles.EOL, "EOL"
        QC = Roles.QC, "Quality Control"

    role = models.CharField(max_length=32, choices=Role.choices, default=Role.PLANNING_DATA_ENTRY)
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="users",
    )
    employee_id = models.CharField(max_length=32, unique=True, null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    designation = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["first_name", "last_name", "username"]

    def save(self, *args, **kwargs):
        if self.employee_id == "":
            self.employee_id = None
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.get_full_name().strip() or self.username

    @property
    def is_management(self):
        return self.is_superuser or self.role in Roles.MANAGEMENT

    @property
    def role_label(self):
        return self.get_role_display()


class SystemSetting(models.Model):
    key = models.CharField(max_length=80, unique=True)
    value = models.TextField(blank=True)
    label = models.CharField(max_length=160, blank=True)
    updated_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="setting_updates",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key


class CompanyLogo(models.Model):
    image = models.ImageField(upload_to="brand/")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="logo_uploads")

    def __str__(self):
        return "Job card logo"


def current_logo():
    from django.db.utils import OperationalError, ProgrammingError

    try:
        return CompanyLogo.objects.order_by("-pk").first()
    except (OperationalError, ProgrammingError):
        return None


def get_setting(key, default=""):
    from django.db.utils import OperationalError, ProgrammingError

    try:
        row = SystemSetting.objects.filter(key=key).only("value").first()
    except (OperationalError, ProgrammingError):
        return default
    if row is None or row.value == "":
        return default
    return row.value


def set_setting(key, value, user=None, label=""):
    row, _created = SystemSetting.objects.get_or_create(key=key, defaults={"label": label, "value": value})
    row.value = value
    if label:
        row.label = label
    if user and getattr(user, "is_authenticated", False):
        row.updated_by = user
    row.save()
    return row


def default_department_for_role(role):
    code = ROLE_DEPARTMENT.get(role, "ADMIN")
    department = Department.objects.filter(code=code).first()
    if department:
        return department
    fallback = dict((item[0], item[1]) for item in DEPARTMENTS).get(code, code)
    return Department.objects.create(code=code, name=fallback, sort_order=0)
