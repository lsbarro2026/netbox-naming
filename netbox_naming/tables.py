import django_tables2 as tables
from netbox.tables import PrimaryModelTable, columns

from .models import NamingConvention

__all__ = ("NamingConventionTable",)


class NamingConventionTable(PrimaryModelTable):
    name = tables.Column(linkify=True)
    kind = columns.ChoiceFieldColumn()
    target_field = columns.ChoiceFieldColumn()
    template = columns.TemplateColumn(template_code="<code>{{ value }}</code>")
    role = tables.Column(linkify=True)
    device_type = tables.Column(linkify=True)
    counter_scope = columns.ChoiceFieldColumn()
    tags = columns.TagColumn(url_name="plugins:netbox_naming:namingconvention_list")

    class Meta(PrimaryModelTable.Meta):
        model = NamingConvention
        fields = (
            "pk",
            "id",
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
            "created",
            "last_updated",
        )
        default_columns = ("pk", "name", "kind", "target_field", "template", "role", "device_type")
