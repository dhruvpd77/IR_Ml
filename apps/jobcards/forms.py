from django import forms
from django.utils.text import slugify

from core.forms import style_form
from jobcards.models import JobCardField, JobCardTemplate


class TemplateForm(forms.ModelForm):
    class Meta:
        model = JobCardTemplate
        fields = ["phase_code", "name", "description"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["phase_code"].disabled = True
        style_form(self)


class FieldForm(forms.ModelForm):
    options_text = forms.CharField(
        required=False,
        label="Options",
        help_text="Comma-separated values for dropdown, radio, and checkbox fields.",
    )

    class Meta:
        model = JobCardField
        fields = [
            "label",
            "field_key",
            "field_type",
            "section",
            "help_text",
            "placeholder",
            "unit",
            "required",
            "sort_order",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["field_key"].required = False
        if self.instance.pk:
            self.fields["options_text"].initial = ", ".join(self.instance.options or [])
        style_form(self)

    def clean_field_type(self):
        value = self.cleaned_data["field_type"]
        if self.instance.pk and self.instance.responses.exists() and value != self.instance.field_type:
            raise forms.ValidationError("This field already has answers. Create a new template version to change its type.")
        return value

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("field_key"):
            cleaned["field_key"] = (slugify(cleaned.get("label") or "") or "")[:70]
        if not cleaned.get("field_key"):
            self.add_error("label", "Enter a label so a field key can be created.")
        cleaned["options"] = [part.strip() for part in (cleaned.get("options_text") or "").split(",") if part.strip()]
        return cleaned

    def save(self, template, commit=True):
        field = super().save(commit=False)
        field.template = template
        field.options = self.cleaned_data.get("options") or []
        if commit:
            field.save()
        return field
