from dcim.models import DeviceRole, DeviceType, Location
from django import forms
from django.core.exceptions import ValidationError
from netbox.forms import PrimaryModelFilterSetForm, PrimaryModelForm, PrimaryModelImportForm
from utilities.forms.fields import (
    CSVChoiceField,
    CSVModelChoiceField,
    DynamicModelChoiceField,
    DynamicModelMultipleChoiceField,
    TagFilterField,
)
from utilities.forms.rendering import FieldSet

from .choices import CounterScopeChoices, KindChoices, TargetFieldChoices
from .generator import MAX_COUNT
from .models import NamingConvention

__all__ = (
    "GenerateForm",
    "NamingConventionFilterForm",
    "NamingConventionForm",
    "NamingConventionImportForm",
)


class NamingConventionForm(PrimaryModelForm):
    role = DynamicModelChoiceField(queryset=DeviceRole.objects.all(), required=False)
    device_type = DynamicModelChoiceField(queryset=DeviceType.objects.all(), required=False)

    fieldsets = (
        FieldSet("name", "kind", "target_field", "template", "description", "owner", "tags", name="Convention"),
        FieldSet("role", "device_type", name="Applies to"),
        FieldSet("counter_scope", "tail_max_length", name="Numbering"),
    )

    class Meta:
        model = NamingConvention
        fields = (
            "name",
            "kind",
            "target_field",
            "template",
            "role",
            "device_type",
            "counter_scope",
            "tail_max_length",
            "description",
            "owner",
            "comments",
            "tags",
        )
        help_texts = {
            "kind": "Static: a fixed name. Numbered: includes one <code>#</code> run. "
            "Custom tail: ends in <code>{tail}</code>, typed by the user.",
            "target_field": "The device field this convention generates.",
            "template": "Tokens in braces, <code>#</code> for the number run; "
            "e.g. <code>{site}-AP-###</code>",
            "counter_scope": "Numbered conventions only: where the number counter restarts.",
            "tail_max_length": "Custom-tail conventions only: the longest tail a user may type.",
        }


class NamingConventionFilterForm(PrimaryModelFilterSetForm):
    model = NamingConvention
    fieldsets = (
        FieldSet("q", "filter_id", "tag"),
        FieldSet("kind", "target_field", "counter_scope", name="Convention"),
        FieldSet("role_id", "device_type_id", name="Applies to"),
        FieldSet("owner_group_id", "owner_id", name="Ownership"),
    )
    kind = forms.MultipleChoiceField(choices=KindChoices, required=False)
    target_field = forms.MultipleChoiceField(choices=TargetFieldChoices, required=False)
    counter_scope = forms.MultipleChoiceField(choices=CounterScopeChoices, required=False)
    role_id = DynamicModelMultipleChoiceField(
        queryset=DeviceRole.objects.all(), required=False, label="Device role"
    )
    device_type_id = DynamicModelMultipleChoiceField(
        queryset=DeviceType.objects.all(), required=False, label="Device type"
    )
    tag = TagFilterField(model)


class NamingConventionImportForm(PrimaryModelImportForm):
    kind = CSVChoiceField(choices=KindChoices)
    target_field = CSVChoiceField(choices=TargetFieldChoices)
    counter_scope = CSVChoiceField(choices=CounterScopeChoices, required=False)
    role = CSVModelChoiceField(
        queryset=DeviceRole.objects.all(),
        to_field_name="slug",
        required=False,
        help_text="Slug of the device role",
    )
    device_type = CSVModelChoiceField(
        queryset=DeviceType.objects.all(),
        to_field_name="slug",
        required=False,
        help_text="Slug of the device type",
    )

    def clean_counter_scope(self):
        return self.cleaned_data["counter_scope"] or CounterScopeChoices.GLOBAL

    class Meta:
        model = NamingConvention
        fields = (
            "name",
            "kind",
            "target_field",
            "template",
            "role",
            "device_type",
            "counter_scope",
            "tail_max_length",
            "description",
            "owner",
            "comments",
            "tags",
        )


class GenerateForm(forms.Form):
    role = DynamicModelChoiceField(queryset=DeviceRole.objects.all(), required=False)
    device_type = DynamicModelChoiceField(queryset=DeviceType.objects.all(), required=False)
    location = DynamicModelChoiceField(
        queryset=Location.objects.all(),
        required=False,
        help_text="Gives the Site and Location tokens a value.",
    )
    tail = forms.CharField(required=False, help_text="For custom-tail conventions.")
    count = forms.IntegerField(min_value=1, max_value=MAX_COUNT, initial=5)

    fieldsets = (
        FieldSet("role", "device_type", "location", name="Applies to"),
        FieldSet("tail", "count", name="Options"),
    )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("role") and not cleaned.get("device_type"):
            raise ValidationError("Pick a role or a device type.")
        return cleaned
