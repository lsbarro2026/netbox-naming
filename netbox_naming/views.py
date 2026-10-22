from extras.ui.panels import TagsPanel
from netbox.object_actions import AddObject, BulkDelete, BulkExport, BulkImport
from netbox.ui import attrs, layout
from netbox.ui.panels import CommentsPanel, ObjectAttributesPanel, TextCodePanel
from netbox.views import generic
from utilities.views import register_model_view

from . import filtersets, forms, tables
from .models import NamingConvention

__all__ = (
    "NamingConventionBulkDeleteView",
    "NamingConventionBulkImportView",
    "NamingConventionDeleteView",
    "NamingConventionEditView",
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
