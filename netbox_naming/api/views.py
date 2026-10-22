from netbox.api.viewsets import NetBoxModelViewSet

from .. import filtersets
from ..models import NamingConvention
from .serializers import NamingConventionSerializer


class NamingConventionViewSet(NetBoxModelViewSet):
    queryset = NamingConvention.objects.select_related("role", "device_type")
    serializer_class = NamingConventionSerializer
    filterset_class = filtersets.NamingConventionFilterSet
