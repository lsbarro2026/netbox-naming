from dcim.models import DeviceRole, DeviceType, Manufacturer
from django.test import TestCase

try:
    from utilities.testing import BaseFilterSetTestMixin
except ImportError:  # NetBox 4.6 names the same mixin BaseFilterSetTests
    from utilities.testing import BaseFilterSetTests as BaseFilterSetTestMixin

from netbox_naming.choices import CounterScopeChoices, KindChoices, TargetFieldChoices
from netbox_naming.filtersets import NamingConventionFilterSet
from netbox_naming.models import NamingConvention


class NamingConventionFilterSetTest(BaseFilterSetTestMixin, TestCase):
    queryset = NamingConvention.objects.all()
    filterset = NamingConventionFilterSet
    ignore_fields = ("owner", "comments", "custom_field_data")

    @classmethod
    def setUpTestData(cls):
        manufacturer = Manufacturer.objects.create(name="Acme", slug="acme")
        cls.types = [
            DeviceType.objects.create(manufacturer=manufacturer, model=f"T{i}", slug=f"t{i}") for i in (1, 2)
        ]
        cls.roles = [DeviceRole.objects.create(name=f"Role {i}", slug=f"role-{i}") for i in (1, 2)]

        NamingConvention.objects.bulk_create(
            [
                NamingConvention(
                    name="AP numbers",
                    kind=KindChoices.NUMBERED,
                    target_field=TargetFieldChoices.NAME,
                    template="AP-###",
                    role=cls.roles[0],
                    counter_scope=CounterScopeChoices.SITE,
                    description="Wireless access points",
                ),
                NamingConvention(
                    name="Switch tags",
                    kind=KindChoices.TAIL,
                    target_field=TargetFieldChoices.ASSET_TAG,
                    template="SW-{tail}",
                    role=cls.roles[1],
                    tail_max_length=8,
                ),
                NamingConvention(
                    name="Fixed type name",
                    kind=KindChoices.STATIC,
                    target_field=TargetFieldChoices.NAME,
                    template="gateway",
                    device_type=cls.types[0],
                    counter_scope=CounterScopeChoices.LOCATION,
                ),
            ]
        )

    def _names(self, params):
        return set(self.filterset(params, self.queryset).qs.values_list("name", flat=True))

    def test_name(self):
        self.assertEqual(self._names({"name": ["AP numbers"]}), {"AP numbers"})

    def test_kind(self):
        self.assertEqual(self._names({"kind": [KindChoices.TAIL]}), {"Switch tags"})

    def test_target_field(self):
        self.assertEqual(self._names({"target_field": [TargetFieldChoices.ASSET_TAG]}), {"Switch tags"})

    def test_counter_scope(self):
        self.assertEqual(
            self._names({"counter_scope": [CounterScopeChoices.SITE, CounterScopeChoices.LOCATION]}),
            {"AP numbers", "Fixed type name"},
        )

    def test_tail_max_length(self):
        self.assertEqual(self._names({"tail_max_length": [8]}), {"Switch tags"})

    def test_role(self):
        self.assertEqual(self._names({"role_id": [self.roles[0].pk]}), {"AP numbers"})
        self.assertEqual(self._names({"role": [self.roles[1].slug]}), {"Switch tags"})

    def test_device_type(self):
        self.assertEqual(self._names({"device_type_id": [self.types[0].pk]}), {"Fixed type name"})
        self.assertEqual(self._names({"device_type": [self.types[0].slug]}), {"Fixed type name"})
        self.assertEqual(self._names({"device_type_id": [self.types[1].pk]}), set())

    def test_q(self):
        self.assertEqual(self._names({"q": "switch"}), {"Switch tags"})
        self.assertEqual(self._names({"q": "AP-###"}), {"AP numbers"})
        self.assertEqual(self._names({"q": "wireless"}), {"AP numbers"})
        self.assertEqual(self._names({"q": "  "}), set(NamingConvention.objects.values_list("name", flat=True)))
