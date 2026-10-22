from dcim.models import DeviceRole, DeviceType, Manufacturer
from django.urls import reverse
from rest_framework import status
from utilities.api import get_serializer_for_model
from utilities.testing import APITestCase, APIViewTestCases

from netbox_naming.api.serializers import NamingConventionSerializer
from netbox_naming.choices import CounterScopeChoices, KindChoices, TargetFieldChoices
from netbox_naming.models import NamingConvention


class NamingConventionAPITest(
    APIViewTestCases.GetObjectViewTestCase,
    APIViewTestCases.ListObjectsViewTestCase,
    APIViewTestCases.CreateObjectViewTestCase,
    APIViewTestCases.UpdateObjectViewTestCase,
    APIViewTestCases.DeleteObjectViewTestCase,
):
    model = NamingConvention
    view_namespace = "plugins-api:netbox_naming"
    brief_fields = ["description", "display", "id", "name", "url"]

    @classmethod
    def setUpTestData(cls):
        manufacturer = Manufacturer.objects.create(name="Acme", slug="acme")
        cls.device_type = DeviceType.objects.create(manufacturer=manufacturer, model="AP-1", slug="ap-1")
        cls.roles = [DeviceRole.objects.create(name=f"Role {i}", slug=f"role-{i}") for i in range(1, 5)]

        # One slot per (target_field, role, device_type), so each row takes a different one
        for i, role in enumerate(cls.roles[:3], start=1):
            NamingConvention.objects.create(
                name=f"Convention {i}",
                kind=KindChoices.NUMBERED,
                target_field=TargetFieldChoices.NAME,
                template=f"AP{i}-##",
                role=role,
            )

        cls.create_data = [
            {
                "name": "API convention 1",
                "kind": KindChoices.NUMBERED,
                "target_field": TargetFieldChoices.NAME,
                "template": "SW-###",
                "role": cls.roles[3].pk,
                "counter_scope": CounterScopeChoices.SITE,
            },
            {
                "name": "API convention 2",
                "kind": KindChoices.STATIC,
                "target_field": TargetFieldChoices.ASSET_TAG,
                "template": "FIXED",
                "device_type": cls.device_type.pk,
            },
            {
                "name": "API convention 3",
                "kind": KindChoices.TAIL,
                "target_field": TargetFieldChoices.ASSET_TAG,
                "template": "X-{tail}",
                "role": cls.roles[0].pk,
                "tail_max_length": 8,
            },
        ]
        cls.bulk_update_data = {"description": "Bulk updated"}
        # Numbered conventions need a '#' run, so this fails the model's clean()
        cls.bulk_update_invalid_data = {"template": "NO-NUMBER"}


class NamingConventionAPIBehaviourTest(APITestCase):
    model = NamingConvention
    view_namespace = "plugins-api:netbox_naming"

    @classmethod
    def setUpTestData(cls):
        cls.role = DeviceRole.objects.create(name="Access Point", slug="access-point")
        cls.other_role = DeviceRole.objects.create(name="Switch", slug="switch")
        NamingConvention.objects.create(
            name="Numbered",
            kind=KindChoices.NUMBERED,
            target_field=TargetFieldChoices.NAME,
            template="AP-###",
            role=cls.role,
        )
        NamingConvention.objects.create(
            name="Tail",
            kind=KindChoices.TAIL,
            target_field=TargetFieldChoices.NAME,
            template="SW-{tail}",
            role=cls.other_role,
            tail_max_length=6,
        )

    def _post(self, **overrides):
        data = {
            "name": "New",
            "kind": KindChoices.NUMBERED,
            "target_field": TargetFieldChoices.ASSET_TAG,
            "template": "T-###",
            "role": self.role.pk,
            **overrides,
        }
        return self.client.post(self._get_list_url(), data, format="json", **self.header)

    def test_serializer_resolves_for_event_rules(self):
        self.assertIs(get_serializer_for_model(NamingConvention), NamingConventionSerializer)

    def test_invalid_template_rejected(self):
        self.add_permissions("netbox_naming.add_namingconvention")
        response = self._post(template="T-")
        self.assertHttpStatus(response, status.HTTP_400_BAD_REQUEST)
        self.assertIn("template", response.data)
        self.assertFalse(NamingConvention.objects.filter(name="New").exists())

    def test_missing_role_and_device_type_rejected(self):
        self.add_permissions("netbox_naming.add_namingconvention")
        response = self._post(role=None)
        self.assertHttpStatus(response, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(NamingConvention.objects.filter(name="New").exists())

    def test_counter_scope_defaults_to_global(self):
        self.add_permissions("netbox_naming.add_namingconvention")
        response = self._post()
        self.assertHttpStatus(response, status.HTTP_201_CREATED)
        self.assertEqual(response.data["counter_scope"]["value"], CounterScopeChoices.GLOBAL)

    def test_choice_fields_serialized_with_labels(self):
        self.add_permissions("netbox_naming.view_namingconvention")
        obj = NamingConvention.objects.get(name="Numbered")
        response = self.client.get(self._get_detail_url(obj), **self.header)
        self.assertHttpStatus(response, status.HTTP_200_OK)
        for field, value in (("kind", KindChoices.NUMBERED), ("target_field", TargetFieldChoices.NAME)):
            self.assertEqual(response.data[field]["value"], value)
            self.assertTrue(response.data[field]["label"])
        self.assertEqual(response.data["role"]["slug"], "access-point")
        self.assertIsNone(response.data["device_type"])

    def test_filter_by_kind(self):
        self.add_permissions("netbox_naming.view_namingconvention")
        response = self.client.get(f"{self._get_list_url()}?kind={KindChoices.TAIL}", **self.header)
        self.assertHttpStatus(response, status.HTTP_200_OK)
        self.assertEqual([r["name"] for r in response.data["results"]], ["Tail"])

    def test_route_is_under_plugins_api(self):
        self.assertEqual(self._get_list_url(), reverse("plugins-api:netbox_naming-api:namingconvention-list"))
