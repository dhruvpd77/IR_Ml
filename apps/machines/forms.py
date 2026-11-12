from django import forms
from django.forms import BaseFormSet, formset_factory

from core.constants import Priority
from core.forms import style_form
from machines.models import ProductionStation

COMPANY_CHOICES = [
    ("Ingersoll Rand", "Ingersoll Rand"),
    ("Champion", "Champion"),
    ("Compair", "Compair"),
]
TYPE_CHOICES = [
    ("OF", "OF"),
    ("Airend", "Airend"),
    ("LIS", "LIS"),
    ("MIS", "MIS"),
    ("STN", "STN"),
]
TEST_BAR_CHOICES = [
    ("Standard", "Standard"),
    ("Other", "Other"),
]
SHIFT_CHOICES = [
    ("1st shift", "1st shift"),
    ("2nd shift", "2nd shift"),
]
REQUIREMENT_DEFAULTS = {
    "calibration": "No",
    "test_report_bar": "Standard",
    "export_packing_required": "No",
    "customer_inspection": "No",
    "priority": Priority.STANDARD,
}
YES_NO_CHOICES = [
    ("Yes", "Yes"),
    ("No", "No"),
]
SELECT = [("", "Select")]


def _keep_current(choices, current):
    current = str(current or "").strip()
    if current and current not in {value for value, _label in choices}:
        return [(current, current), *choices]
    return choices


def _merge_choices(choices, extra):
    merged = list(choices)
    seen = {value for value, _label in merged}
    for value in extra:
        text = str(value or "").strip()
        if text and text not in seen:
            merged.append((text, text))
            seen.add(text)
    return merged


class PlanningForm(forms.Form):
    company = forms.ChoiceField(choices=SELECT + COMPANY_CHOICES, required=False, label="Brand")
    machine_type = forms.ChoiceField(choices=SELECT + TYPE_CHOICES, required=False, label="Type")
    work_order = forms.CharField(required=False, label="Work order", help_text="Type the work order.")
    ccn = forms.CharField(required=False, label="CCN", help_text="Shown in this box after you select a model.")
    model_description = forms.ChoiceField(
        choices=SELECT,
        required=False,
        label="Model description",
        help_text="Search, then choose a model. The list shows every model for the brand and type.",
    )
    calibration = forms.ChoiceField(choices=SELECT + YES_NO_CHOICES, required=False, label="Calibration")
    shift = forms.ChoiceField(choices=SELECT + SHIFT_CHOICES, required=False, label="Shift of machine")
    test_report_bar = forms.ChoiceField(
        choices=SELECT + TEST_BAR_CHOICES,
        required=False,
        label="Test report required at bar",
    )
    test_report_detail = forms.CharField(
        required=False,
        label="Test report",
        help_text="Write the report in words.",
    )
    export_packing_required = forms.ChoiceField(
        choices=SELECT + YES_NO_CHOICES,
        required=False,
        label="Export packing required",
    )
    customer_inspection = forms.ChoiceField(
        choices=SELECT + YES_NO_CHOICES,
        required=False,
        label="Customer inspection",
        widget=forms.Select(attrs={"data-inspection": "1"}),
    )
    customer_inspection_date = forms.DateField(
        required=False,
        label="Customer inspection date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    priority = forms.ChoiceField(choices=SELECT + Priority.CHOICES, required=False, label="Priority")

    def __init__(self, *args, require_row=True, **kwargs):
        self.require_row = require_row
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            current_bar = str(self.initial.get("test_report_bar") or "")
            if current_bar and current_bar not in {"Standard", "Other"}:
                self.initial["test_report_detail"] = current_bar
                self.initial["test_report_bar"] = "Other"
        if self.require_row and not self.is_bound:
            for key, value in REQUIREMENT_DEFAULTS.items():
                self.initial.setdefault(key, value)
            if not (self.initial.get("company") or ""):
                self.initial["company"] = "Ingersoll Rand"
        from machines.catalog import extra_companies, extra_types, models_for

        company = self._value("company")
        machine_type = self._value("machine_type")
        model_choices = []
        for model, ccn, job_card, _job_card_format in models_for(company, machine_type):
            parts = [model]
            if ccn:
                parts.append(str(ccn))
            if job_card:
                parts.append(str(job_card))
            model_choices.append((model, "  ·  ".join(parts)))
        if (
            self.initial.get("model_description")
            and company == str(self.initial.get("company") or "").strip()
            and machine_type == str(self.initial.get("machine_type") or "").strip()
        ):
            model_choices = _keep_current(model_choices, self.initial.get("model_description"))
        self.fields["model_description"].choices = SELECT + model_choices
        self.fields["model_description"].widget.attrs["data-model"] = "1"
        self.fields["model_description"].widget.attrs["data-current"] = self._value("model_description")
        self.fields["ccn"].widget.attrs.update({"readonly": "readonly", "data-ccn": "1", "placeholder": "Fills from the model"})
        self.fields["test_report_bar"].widget.attrs["data-test-report"] = "1"
        self.fields["test_report_detail"].widget.attrs["placeholder"] = "Write the test report"
        for name, choices in (
            ("company", _merge_choices(COMPANY_CHOICES, extra_companies())),
            ("machine_type", _merge_choices(TYPE_CHOICES, extra_types())),
            ("calibration", YES_NO_CHOICES),
            ("shift", SHIFT_CHOICES),
            ("test_report_bar", TEST_BAR_CHOICES),
            ("export_packing_required", YES_NO_CHOICES),
            ("customer_inspection", YES_NO_CHOICES),
            ("priority", Priority.CHOICES),
        ):
            current = self.initial.get(name)
            self.fields[name].choices = SELECT + _keep_current(choices, current)
        style_form(self)

    def _value(self, name):
        if self.is_bound:
            return str(self.data.get(self.add_prefix(name), "") or "").strip()
        return str(self.initial.get(name, "") or "").strip()

    def clean(self):
        data = super().clean()
        content_keys = (
            "work_order",
            "model_description",
            "ccn",
            "machine_type",
            "calibration",
            "shift",
            "test_report_bar",
            "test_report_detail",
            "export_packing_required",
            "customer_inspection",
            "priority",
        )
        filled = any(str(data.get(key) or "").strip() for key in content_keys)
        if not self.require_row and not filled:
            data["blank"] = True
            return data
        required = (
            ("company", "Select a brand."),
            ("machine_type", "Select a type."),
            ("work_order", "Work order is required."),
            ("model_description", "Model description is required."),
            ("calibration", "Select calibration."),
            ("shift", "Select the shift of the machine."),
            ("test_report_bar", "Select the test report bar."),
            ("export_packing_required", "Select export packing."),
            ("customer_inspection", "Select customer inspection."),
            ("priority", "Select a priority."),
        )
        for key, message in required:
            if not str(data.get(key) or "").strip():
                self.add_error(key, message)
        if data.get("customer_inspection") == "Yes" and not data.get("customer_inspection_date"):
            self.add_error("customer_inspection_date", "Enter the customer inspection date.")
        if data.get("customer_inspection") != "Yes":
            data["customer_inspection_date"] = None
        detail = str(data.get("test_report_detail") or "").strip().upper()
        if data.get("test_report_bar") == "Other":
            if not detail:
                self.add_error("test_report_detail", "Write the test report.")
            else:
                data["test_report_bar"] = detail
                data["test_report_detail"] = detail
        elif data.get("test_report_bar") == "Standard":
            data["test_report_bar"] = "Standard"
        from machines.catalog import find_model

        model = str(data.get("model_description") or "").strip()
        match = find_model(data.get("company"), data.get("machine_type"), model)
        same_as_saved = (
            model
            and model == str(self.initial.get("model_description") or "").strip()
            and str(data.get("company") or "").strip() == str(self.initial.get("company") or "").strip()
            and str(data.get("machine_type") or "").strip() == str(self.initial.get("machine_type") or "").strip()
        )
        if match:
            data["ccn"] = str(match.ccn or "").strip().upper()
            data["model_description"] = str(match.model_description or "").strip().upper()
        elif same_as_saved:
            data["ccn"] = str(self.initial.get("ccn") or data.get("ccn") or "").strip().upper()
            data["model_description"] = model.upper()
        elif model:
            self.add_error("model_description", "Select a model from the uploaded list.")
        if "work_order" in data and data.get("work_order") is not None:
            data["work_order"] = str(data.get("work_order") or "").strip().upper()
        data["blank"] = False
        return data


class BasePlanningFormSet(BaseFormSet):
    def _construct_form(self, i, **kwargs):
        kwargs["require_row"] = False
        return super()._construct_form(i, **kwargs)


PlanningFormSet = formset_factory(PlanningForm, formset=BasePlanningFormSet, extra=3, max_num=25)


class ImportUploadForm(forms.Form):
    source = forms.FileField(label="Planning workbook")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_form(self)

    def clean_source(self):
        upload = self.cleaned_data["source"]
        name = (upload.name or "").lower()
        if not name.endswith(".xlsx"):
            raise forms.ValidationError("Upload an Excel .xlsx file.")
        return upload


class ChecklistUploadForm(forms.Form):
    source = forms.FileField(label="Production checklists workbook")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_form(self)

    def clean_source(self):
        upload = self.cleaned_data["source"]
        name = (upload.name or "").lower()
        if not name.endswith(".xlsx"):
            raise forms.ValidationError("Upload an Excel .xlsx file.")
        return upload


class StationForm(forms.ModelForm):
    class Meta:
        model = ProductionStation
        fields = ["code", "line", "name", "kind", "sort_order", "description", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["code"].disabled = True
        self.fields["line"].required = True
        self.fields["kind"].required = True
        self.fields["line"].help_text = "Shows in the location list and on Machine Analytics."
        self.fields["kind"].help_text = "Sub assembly or assembly."
        self.fields["sort_order"].help_text = "Lower numbers sit higher on the line. Use 10 for the top station."
        style_form(self)


class ProductionReleaseForm(forms.Form):
    station = forms.ModelChoiceField(queryset=ProductionStation.objects.none(), label="Production station")
    production_serial = forms.CharField(required=False, label="Production serial number")
    remarks = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), label="Production remarks")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["station"].queryset = ProductionStation.objects.filter(is_active=True).order_by("line", "sort_order", "name")
        style_form(self)
