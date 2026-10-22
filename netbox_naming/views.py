from dcim.models import DeviceRole, DeviceType, Location
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.views.generic import View
from extras.ui.panels import TagsPanel
from netbox.object_actions import AddObject, BulkDelete, BulkExport, BulkImport
from netbox.ui import attrs, layout
from netbox.ui.panels import CommentsPanel, ObjectAttributesPanel, ObjectPanel, TextCodePanel
from netbox.views import generic
from utilities.views import register_model_view

from . import filtersets, forms, generator, tables
from .choices import CounterScopeChoices
from .engine import NamingContext
from .models import NamingConvention
from .preview import preview_convention

__all__ = (
    "GenerateNamesView",
    "NamingConventionBulkDeleteView",
    "NamingConventionBulkImportView",
    "NamingConventionDeleteView",
    "NamingConventionEditView",
    "NamingConventionListView",
    "NamingConventionView",
    "SampleValuesPanel",
    "TemplatePreviewView",
)

DEVICE_PERMISSION = "dcim.view_device"


class NamingConventionPanel(ObjectAttributesPanel):
    name = attrs.TextAttr("name")
    kind = attrs.ChoiceAttr("kind")
    target_field = attrs.ChoiceAttr("target_field")
    role = attrs.RelatedObjectAttr("role", linkify=True)
    device_type = attrs.RelatedObjectAttr("device_type", linkify=True)
    counter_scope = attrs.ChoiceAttr("counter_scope")
    tail_max_length = attrs.NumericAttr("tail_max_length")
    description = attrs.TextAttr("description")


class SampleValuesPanel(ObjectPanel):
    """The saved convention's next values, with only its own role and device type as context."""

    template_name = "netbox_naming/inc/sample_values_panel.html"
    title = "Sample values"

    def get_context(self, context):
        ctx = super().get_context(context)
        convention = ctx["object"]
        ctx["allowed"] = ctx["request"].user.has_perm(DEVICE_PERMISSION)
        if ctx["allowed"]:
            ctx["preview"] = preview_convention(
                convention,
                NamingContext(role=convention.role, device_type=convention.device_type),
            )
        return ctx


@register_model_view(NamingConvention, "list", path="", detail=False)
class NamingConventionListView(generic.ObjectListView):
    queryset = NamingConvention.objects.select_related("role", "device_type")
    filterset = filtersets.NamingConventionFilterSet
    filterset_form = forms.NamingConventionFilterForm
    table = tables.NamingConventionTable
    actions = (AddObject, BulkImport, BulkExport, BulkDelete)


@register_model_view(NamingConvention)
class NamingConventionView(generic.ObjectView):
    queryset = NamingConvention.objects.select_related("role", "device_type")
    layout = layout.SimpleLayout(
        left_panels=[
            NamingConventionPanel(),
            TextCodePanel("template"),
        ],
        right_panels=[
            SampleValuesPanel(),
            TagsPanel(),
        ],
        bottom_panels=[
            CommentsPanel(),
        ],
    )


@register_model_view(NamingConvention, "add", detail=False)
@register_model_view(NamingConvention, "edit")
class NamingConventionEditView(generic.ObjectEditView):
    queryset = NamingConvention.objects.all()
    form = forms.NamingConventionForm


@register_model_view(NamingConvention, "delete")
class NamingConventionDeleteView(generic.ObjectDeleteView):
    queryset = NamingConvention.objects.all()


@register_model_view(NamingConvention, "bulk_import", path="import", detail=False)
class NamingConventionBulkImportView(generic.BulkImportView):
    queryset = NamingConvention.objects.all()
    model_form = forms.NamingConventionImportForm


@register_model_view(NamingConvention, "bulk_delete", path="delete", detail=False)
class NamingConventionBulkDeleteView(generic.BulkDeleteView):
    queryset = NamingConvention.objects.select_related("role", "device_type")
    filterset = filtersets.NamingConventionFilterSet
    table = tables.NamingConventionTable


class GenerateNamesView(PermissionRequiredMixin, View):
    """Preview the next N names and asset tags. GET only: nothing is written or used up."""

    http_method_names = ["get", "head", "options"]
    permission_required = ("netbox_naming.view_namingconvention", "dcim.view_device")
    template_name = "netbox_naming/generate_names.html"

    def get(self, request):
        form = forms.GenerateForm(request.GET or None)
        # Ids the user can't see fail field validation, so they count as absent.
        for field, model in (
            ("role", DeviceRole),
            ("device_type", DeviceType),
            ("location", Location),
        ):
            form.fields[field].queryset = model.objects.restrict(request.user, "view")
        generation = None
        if form.is_valid():
            generation = generator.generate(**form.cleaned_data)
        return render(request, self.template_name, {"form": form, "generation": generation})


class TemplatePreviewView(LoginRequiredMixin, View):
    """Render the editor's preview partial. Read-only; the gate is plan Decision 4."""

    http_method_names = ["post"]
    template_name = "netbox_naming/inc/template_preview.html"

    def post(self, request):
        user, data = request.user, request.POST
        if not user.has_perm(DEVICE_PERMISSION):
            return self._denied(request, DEVICE_PERMISSION)
        if pk := data.get("pk"):
            if not pk.isdigit():
                raise Http404
            convention = get_object_or_404(NamingConvention.objects.restrict(user, "change"), pk=pk)
        elif user.has_perm("netbox_naming.add_namingconvention"):
            convention = NamingConvention()
        else:
            return self._denied(request, "netbox_naming.add_namingconvention")

        # Ids the user can't see count as absent.
        role = _visible(DeviceRole, user, data.get("role"))
        device_type = _visible(DeviceType, user, data.get("device_type"))
        location = _visible(Location, user, data.get("preview_location"))
        tail_max_length = data.get("tail_max_length", "")
        convention.kind = data.get("kind", "")
        convention.target_field = data.get("target_field", "")
        convention.template = data.get("template", "")
        convention.counter_scope = data.get("counter_scope") or CounterScopeChoices.GLOBAL
        convention.tail_max_length = int(tail_max_length) if tail_max_length.isdigit() else None
        convention.role, convention.device_type = role, device_type

        context = NamingContext(
            role=role,
            device_type=device_type,
            site=location.site if location is not None else None,
            location=location,
        )
        preview = preview_convention(convention, context, tail=data.get("preview_tail"))
        return render(request, self.template_name, {"preview": preview})

    def _denied(self, request, permission):
        return render(request, self.template_name, {"missing_permission": permission}, status=403)


def _visible(model, user, pk):
    if not pk or not pk.isdigit():
        return None
    return model.objects.restrict(user, "view").filter(pk=pk).first()
