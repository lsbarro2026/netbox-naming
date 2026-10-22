from dcim.api.serializers import DeviceRoleSerializer, DeviceTypeSerializer
from netbox.api.fields import ChoiceField
from netbox.api.serializers import PrimaryModelSerializer

from ..choices import CounterScopeChoices, KindChoices, TargetFieldChoices
from ..models import NamingConvention

__all__ = ("NamingConventionSerializer",)


class NamingConventionSerializer(PrimaryModelSerializer):
    kind = ChoiceField(choices=KindChoices)
    target_field = ChoiceField(choices=TargetFieldChoices)
    counter_scope = ChoiceField(choices=CounterScopeChoices, required=False)
    role = DeviceRoleSerializer(nested=True, required=False, allow_null=True)
    device_type = DeviceTypeSerializer(nested=True, required=False, allow_null=True)

    class Meta:
        model = NamingConvention
        fields = [
            "id", "url", "display_url", "display", "name", "kind", "target_field", "template", "role",
            "device_type", "counter_scope", "tail_max_length", "description", "owner", "comments", "tags",
            "custom_fields", "created", "last_updated",
        ]  # fmt: skip
        brief_fields = ("id", "url", "display", "name", "description")
