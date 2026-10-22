from netbox.search import SearchIndex, register_search

from .models import NamingConvention


@register_search
class NamingConventionIndex(SearchIndex):
    model = NamingConvention
    fields = (
        ("name", 100),
        ("template", 300),
        ("description", 500),
    )
    display_attrs = ("kind", "target_field", "role", "device_type")
