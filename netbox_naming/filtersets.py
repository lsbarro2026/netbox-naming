import django_filters
from dcim.models import DeviceRole, DeviceType
from django.db.models import Q
from netbox.filtersets import PrimaryModelFilterSet
from utilities.filters import TreeNodeMultipleChoiceFilter
from utilities.filtersets import register_filterset

from .choices import CounterScopeChoices, KindChoices, TargetFieldChoices
from .models import NamingConvention

__all__ = ("NamingConventionFilterSet",)


@register_filterset
class NamingConventionFilterSet(PrimaryModelFilterSet):
    kind = django_filters.MultipleChoiceFilter(choices=KindChoices, distinct=False)
    target_field = django_filters.MultipleChoiceFilter(choices=TargetFieldChoices, distinct=False)
    counter_scope = django_filters.MultipleChoiceFilter(choices=CounterScopeChoices, distinct=False)
    # DeviceRole is a tree, so (as on dcim's device filterset) a role filter includes descendants
    role_id = TreeNodeMultipleChoiceFilter(
        field_name="role",
        queryset=DeviceRole.objects.all(),
        lookup_expr="in",
        label="Device role (ID)",
    )
    role = TreeNodeMultipleChoiceFilter(
        field_name="role",
        queryset=DeviceRole.objects.all(),
        lookup_expr="in",
        to_field_name="slug",
        label="Device role (slug)",
    )
    device_type_id = django_filters.ModelMultipleChoiceFilter(
        queryset=DeviceType.objects.all(),
        distinct=False,
        label="Device type (ID)",
    )
    device_type = django_filters.ModelMultipleChoiceFilter(
        field_name="device_type__slug",
        queryset=DeviceType.objects.all(),
        to_field_name="slug",
        distinct=False,
        label="Device type (slug)",
    )

    class Meta:
        model = NamingConvention
        fields = ("id", "name", "template", "tail_max_length", "description")

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(
            Q(name__icontains=value) | Q(template__icontains=value) | Q(description__icontains=value)
        )
