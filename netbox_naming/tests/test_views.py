from dcim.models import DeviceRole, DeviceType, Manufacturer
from django.test import override_settings
from django.urls import reverse
from utilities.testing import ViewTestCases
from utilities.testing.views import ModelViewTestCase

from netbox_naming.choices import CounterScopeChoices, KindChoices, TargetFieldChoices
from netbox_naming.models import NamingConvention


class NamingConventionViewTestCase(
    ViewTestCases.GetObjectViewTestCase,
    ViewTestCases.GetObjectChangelogViewTestCase,
    ViewTestCases.CreateObjectViewTestCase,
    ViewTestCases.EditObjectViewTestCase,
    ViewTestCases.DeleteObjectViewTestCase,
    ViewTestCases.ListObjectsViewTestCase,
    ViewTestCases.BulkImportObjectsViewTestCase,
    ViewTestCases.BulkDeleteObjectsViewTestCase,
):
    model = NamingConvention

    def _get_base_url(self):
        return "plugins:netbox_naming:namingconvention_{}"

    @classmethod
    def setUpTestData(cls):
        manufacturer = Manufacturer.objects.create(name="Acme", slug="acme")
        other_manufacturer = Manufacturer.objects.create(name="Beta", slug="beta")
        device_type = DeviceType.objects.create(manufacturer=manufacturer, model="AP-1", slug="ap-1")
        DeviceType.objects.create(manufacturer=manufacturer, model="Dup", slug="dup")
        DeviceType.objects.create(manufacturer=other_manufacturer, model="Dup", slug="dup")
        role = DeviceRole.objects.create(name="Access Point", slug="access-point")
        DeviceRole.objects.create(name="Switch", slug="switch")
        cls.role = role
        cls.device_type = device_type

        switch = DeviceRole.objects.get(slug="switch")
        # One slot per (target_field, role, device_type), so each row takes a different one
        slots = (
            (TargetFieldChoices.NAME, role, device_type),
            (TargetFieldChoices.ASSET_TAG, role, None),
            (TargetFieldChoices.NAME, switch, None),
        )
        for i, (target_field, slot_role, slot_type) in enumerate(slots, start=1):
            NamingConvention.objects.create(
                name=f"Convention {i}",
                kind=KindChoices.NUMBERED,
                target_field=target_field,
                template=f"AP{i}-##",
                role=slot_role,
                device_type=slot_type,
            )

        cls.form_data = {
            "name": "New convention",
            "kind": KindChoices.NUMBERED,
            "target_field": TargetFieldChoices.NAME,
            "template": "SW-###",
            "role": switch.pk,
            "device_type": device_type.pk,
            "counter_scope": CounterScopeChoices.SITE,
            "description": "Switches",
            "tags": [],
        }
        cls.csv_data = (
            "name,kind,target_field,template,role,device_type,counter_scope",
            "Import 1,numbered,name,IMP1-##,access-point,,global",
            "Import 2,static,asset_tag,IMP2,,ap-1,",
            "Import 3,tail,name,X-{tail},switch,ap-1,global",
        )
        cls.csv_update_data = (
            "id,description",
            f"{NamingConvention.objects.get(name='Convention 1').pk},Updated 1",
            f"{NamingConvention.objects.get(name='Convention 2').pk},Updated 2",
            f"{NamingConvention.objects.get(name='Convention 3').pk},Updated 3",
        )

    @override_settings(EXEMPT_VIEW_PERMISSIONS=["*"], EXEMPT_EXCLUDE_MODELS=[])
    def _import_response(self, csv_rows):
        self.add_permissions("netbox_naming.add_namingconvention")
        return self.client.post(
            self._get_url("bulk_import"),
            {"data": "\n".join(csv_rows), "format": "csv", "csv_delimiter": ","},
        )

    def test_import_defaults_counter_scope(self):
        response = self._import_response(self.csv_data[:1] + ("Import 2,static,asset_tag,IMP2,,ap-1,",))
        errors = response.context["form"].errors if response.status_code == 200 else None
        self.assertEqual(response.status_code, 302, errors)
        self.assertEqual(
            NamingConvention.objects.get(name="Import 2").counter_scope, CounterScopeChoices.GLOBAL
        )

    def test_import_ambiguous_device_type_slug_is_a_row_error(self):
        rows = (
            self.csv_data[0],
            "Ambiguous,static,name,AMB,,dup,",
        )
        response = self._import_response(rows)
        self.assertHttpStatus(response, 200)
        self.assertIn("device_type", str(response.context["form"].errors))
        self.assertFalse(NamingConvention.objects.filter(name="Ambiguous").exists())

    def test_list_renders_declared_actions_only(self):
        self.add_permissions(
            "netbox_naming.view_namingconvention",
            "netbox_naming.add_namingconvention",
            "netbox_naming.delete_namingconvention",
            "netbox_naming.change_namingconvention",
        )
        content = self.client.get(self._get_url("list")).content.decode()
        self.assertIn(self._get_url("add"), content)
        self.assertIn(self._get_url("bulk_import"), content)
        self.assertNotIn("bulk_edit", content)
        self.assertNotIn("bulk_rename", content)
        self.assertNotIn("Rename Selected", content)
        self.assertNotIn("Edit Selected", content)


class NamingMenuTest(ModelViewTestCase):
    """Menu item visibility, driven by the `view_namingconvention` permission."""

    model = NamingConvention

    def _menu_html(self):
        return self.client.get(reverse("home")).content.decode()

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_menu_hidden_without_permission(self):
        html = self._menu_html()
        self.assertNotIn("Naming Conventions", html)

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_menu_visible_with_permission(self):
        self.add_permissions("netbox_naming.view_namingconvention")
        html = self._menu_html()
        self.assertIn("Naming Conventions", html)
        self.assertIn(reverse("plugins:netbox_naming:namingconvention_list"), html)
