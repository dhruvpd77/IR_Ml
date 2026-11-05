from django import forms
from django.contrib.auth.password_validation import validate_password

from accounts.models import Department, User, default_department_for_role
from core.forms import style_form


class UserForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Required for a new user. Leave blank to keep the current password.",
    )

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "employee_id",
            "phone",
            "designation",
            "role",
            "department",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True)
        self.fields["department"].required = False
        style_form(self)

    def clean_password(self):
        password = self.cleaned_data.get("password") or ""
        if not self.instance.pk and not password:
            raise forms.ValidationError("Set a password for the new user.")
        if password:
            validate_password(password, self.instance)
        return password

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("department") and cleaned.get("role"):
            cleaned["department"] = default_department_for_role(cleaned["role"])
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        user.is_superuser = user.role == "SUPER_ADMIN"
        user.is_staff = user.role in {"SUPER_ADMIN", "ADMIN"}
        if commit:
            user.save()
        return user


class SettingsForm(forms.Form):
    company_name = forms.CharField(label="Company name")
    machine_id_prefix = forms.CharField(label="Machine ID prefix")
    duplicate_fields = forms.CharField(
        label="Duplicate check fields",
        help_text="Comma-separated planning fields. Example: work_order,ccn,model_description",
    )
    retention_note = forms.CharField(label="Retention note", widget=forms.Textarea(attrs={"rows": 3}))
    logo = forms.ImageField(
        required=False,
        label="Job card logo",
        help_text="Shown above the assembly, testing, and end-of-line card. PNG or JPG.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_form(self)
