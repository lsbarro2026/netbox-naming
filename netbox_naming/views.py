from dcim.models import Device, DeviceRole, DeviceType, Location
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.shortcuts import render
from django.views.generic import View
from extras.ui.panels import TagsPanel
from netbox.object_actions import AddObject, BulkDelete, BulkExport, BulkImport
from netbox.ui import attrs, layout
from netbox.ui.panels import CommentsPanel, ObjectAttributesPanel, TextCodePanel
from netbox.views import generic
from utilities.paginator import EnhancedPaginator, get_paginate_count
from utilities.views import ViewTab, register_model_view

from . import filtersets, forms, generator, tables
from .models import NamingConvention

__all__ = (
    "GenerateNamesView",
    "NameInventoryListView",
    "NamingConventionBulkDeleteView",
    "NamingConventionBulkImportView",
    "NamingConventionDeleteView",
    "NamingConventionEditView",
    "NamingConventionInventoryView",
    "NamingConventionListView",
    "NamingConventionView",
)


class NamingConventionPanel(ObjectAttributesPanel):
    name = attrs.TextAttr("name")
    kind = attrs.ChoiceAttr("kind")
    target_field = attrs.ChoiceAttr("target_field")
    role = attrs.RelatedObjectAttr("role", linkify=True)
    device_type = attrs.RelatedObjectAttr("device_type", linkify=True)
    counter_scope = attrs.ChoiceAttr("counter_scope")
    tail_max_length = attrs.NumericAttr("tail_max_length")
    description = attrs.TextAttr("description")


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


def _page(request, items):
    """One page of `items`, sized by NetBox's per-page setting."""
    paginator = EnhancedPaginator(items, get_paginate_count(request))
    return paginator, paginator.get_page(request.GET.get("page"))


class NameInventoryListView(PermissionRequiredMixin, View):
    """Values in use, per convention. Read-only; the inventory runs only for the visible page."""

    http_method_names = ["get", "head", "options"]
    permission_required = ("netbox_naming.view_namingconvention", "dcim.view_device")
    template_name = "netbox_naming/name_inventory.html"

    def get(self, request):
        conventions = NamingConvention.objects.restrict(request.user, "view").order_by("name")
        paginator, page = _page(request, conventions)
        devices = Device.objects.restrict(request.user, "view")
        rows = []
        for convention in page:
            inventory = generator.inventory(convention, devices)
            in_use = sum(len(series.taken) for series in inventory.series)
            rows.append((inventory, in_use))
        return render(
            request, self.template_name, {"rows": rows, "paginator": paginator, "page": page}
        )


@register_model_view(NamingConvention, "inventory", path="inventory")
class NamingConventionInventoryView(generic.ObjectView):
    queryset = NamingConvention.objects.all()
    template_name = "netbox_naming/namingconvention_inventory.html"
    additional_permissions = ["dcim.view_device"]
    tab = ViewTab(label="Inventory", permission="dcim.view_device")

    def get_extra_context(self, request, instance):
        devices = Device.objects.restrict(request.user, "view")
        inventory = generator.inventory(instance, devices)
        taken = [value for series in inventory.series for value in series.taken]
        paginator, page = _page(request, taken)
        return {"inventory": inventory, "paginator": paginator, "page": page}
