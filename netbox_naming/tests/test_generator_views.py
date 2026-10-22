from core.models import ObjectType
from dcim.models import Device, DeviceRole, Location
from django.test import override_settings
from django.urls import reverse
from users.models import ObjectPermission
from utilities.testing import TestCase

from netbox_naming.choices import TargetFieldChoices
from netbox_naming.models import NamingCounter
from netbox_naming.tests.test_engine import EngineTestBase

CONVENTION = "netbox_naming.view_namingconvention"
DEVICE = "dcim.view_device"
# What the user needs to see in the form's role, device type and location pickers.
PICKERS = ("dcim.view_devicerole", "dcim.view_devicetype", "dcim.view_location")


@override_settings(EXEMPT_VIEW_PERMISSIONS=[])
# utilities TestCase adds the logged-in user and client
class GenerateNamesViewTest(EngineTestBase, TestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("plugins:netbox_naming:generate")
        self.convention("ap##")
        self.convention("tag##", target_field=TargetFieldChoices.ASSET_TAG)

    def get(self, **params):
        return self.client.get(self.url, params)

    def restrict(self, model, **constraints):
        """Let the test user view only the `model` objects matching `constraints`."""
        perm = ObjectPermission.objects.create(
            name=f"restricted {model._meta.model_name}", actions=["view"], constraints=constraints
        )
        perm.users.add(self.user)
        perm.object_types.add(ObjectType.objects.get_for_model(model))

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        self.assertEqual(self.get().status_code, 302)

    def test_needs_both_permissions(self):
        self.assertEqual(self.get().status_code, 403)
        self.add_permissions(CONVENTION)
        self.assertEqual(self.get().status_code, 403)
        self.remove_permissions(CONVENTION)
        self.add_permissions(DEVICE)
        self.assertEqual(self.get().status_code, 403)
        self.add_permissions(CONVENTION)
        self.assertEqual(self.get().status_code, 200)

    def test_empty_form_shows_no_results(self):
        self.add_permissions(CONVENTION, DEVICE)
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["generation"])

    def test_role_or_device_type_is_required(self):
        self.add_permissions(CONVENTION, DEVICE)
        response = self.get(count=5)
        self.assertIsNone(response.context["generation"])
        self.assertIn("Pick a role or a device type.", response.content.decode())

    def test_next_five_is_repeatable_and_uses_nothing_up(self):
        self.add_permissions(CONVENTION, DEVICE, *PICKERS)
        values = []
        for _ in range(2):
            response = self.get(role=self.role.pk, location=self.room.pk, count=5)
            self.assertEqual(response.status_code, 200)
            rows = response.context["generation"].rows
            values.append([(r.name.value, r.asset_tag.value) for r in rows])
        self.assertEqual(values[0], [(f"ap{i:02}", f"tag{i:02}") for i in range(1, 6)])
        self.assertEqual(values[0], values[1])
        self.assertFalse(NamingCounter.objects.exists())

    def test_missing_token_is_a_message(self):
        self.convention("{room}-##", role=self.other_role)
        self.add_permissions(CONVENTION, DEVICE, *PICKERS)
        response = self.get(role=self.other_role.pk, count=2)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Pick a Location", response.content.decode())

    def test_hidden_role_is_treated_as_absent(self):
        self.add_permissions(CONVENTION, DEVICE)
        self.restrict(DeviceRole, slug=self.other_role.slug)
        response = self.get(role=self.role.pk, count=5)
        self.assertEqual(response.status_code, 200)
        self.assertIn("role", response.context["form"].errors)
        self.assertIsNone(response.context["generation"])

    def test_hidden_location_is_treated_as_absent(self):
        self.add_permissions(CONVENTION, DEVICE, "dcim.view_devicerole")
        self.restrict(Location, slug=self.other_room.slug)
        response = self.get(role=self.role.pk, location=self.room.pk, count=5)
        self.assertIn("location", response.context["form"].errors)
        self.assertIsNone(response.context["generation"])

    def test_post_is_not_allowed(self):
        self.add_permissions(CONVENTION, DEVICE)
        response = self.client.post(self.url, {"role": self.role.pk, "count": 5})
        self.assertEqual(response.status_code, 405)
        self.assertFalse(NamingCounter.objects.exists())

    def test_menu_item_needs_both_permissions(self):
        home = reverse("home")
        self.add_permissions(CONVENTION)
        self.assertNotIn(self.url, self.client.get(home).content.decode())
        self.add_permissions(DEVICE)
        self.assertIn(self.url, self.client.get(home).content.decode())


@override_settings(EXEMPT_VIEW_PERMISSIONS=[])
class InventoryViewsTest(EngineTestBase, TestCase):
    def setUp(self):
        super().setUp()
        self.list_url = reverse("plugins:netbox_naming:inventory")
        self.ap = self.convention("ap##")
        self.tab_url = reverse("plugins:netbox_naming:namingconvention_inventory", args=[self.ap.pk])
        for n in (1, 2, 3, 5):
            self.device(f"ap{n:02}")
        self.device("ap09", site=self.other_site)

    def restrict_devices(self, **constraints):
        perm = ObjectPermission.objects.create(
            name="restricted device", actions=["view"], constraints=constraints
        )
        perm.users.add(self.user)
        perm.object_types.add(ObjectType.objects.get_for_model(Device))

    def test_list_needs_both_permissions(self):
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.add_permissions(CONVENTION)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.add_permissions(DEVICE)
        self.assertEqual(self.client.get(self.list_url).status_code, 200)

    def test_list_anonymous_is_sent_to_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.list_url).status_code, 302)

    def test_list_shows_count_and_next_free(self):
        self.add_permissions(CONVENTION, DEVICE)
        response = self.client.get(self.list_url)
        [(inventory, in_use)] = response.context["rows"]
        self.assertEqual((inventory.convention, in_use), (self.ap, 5))
        content = response.content.decode()
        self.assertIn("<code>ap09</code>", content)  # highest
        self.assertIn("<code>ap10</code>", content)  # next free

    def test_list_links_multi_series_to_the_tab(self):
        sw = self.convention("{site_slug}-sw##", role=self.other_role)
        self.device("lon-sw01")
        self.device("par-sw01", site=self.other_site)
        self.add_permissions(CONVENTION, DEVICE)
        content = self.client.get(self.list_url).content.decode()
        self.assertIn("per site/location", content)
        sw_tab = reverse("plugins:netbox_naming:namingconvention_inventory", args=[sw.pk])
        self.assertIn(sw_tab, content)

    def test_list_is_paginated(self):
        # NetBox's paginator folds up to 5 orphans into the last page, so 7 are needed to split.
        for i in range(6):
            role = DeviceRole.objects.create(name=f"Role {i}", slug=f"role-{i}")
            self.convention(f"r{i}-##", role=role)
        self.add_permissions(CONVENTION, DEVICE)
        response = self.client.get(self.list_url, {"per_page": 1})
        self.assertEqual(len(response.context["rows"]), 1)
        self.assertEqual(response.context["paginator"].num_pages, 2)

    def test_tab_shows_ranges_and_devices(self):
        self.add_permissions(CONVENTION, DEVICE)
        response = self.client.get(self.tab_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("1–3, 5, 9", response.content.decode())
        self.assertEqual(len(response.context["page"].object_list), 5)

    def test_tab_needs_device_permission(self):
        self.add_permissions(CONVENTION)
        detail = self.client.get(self.ap.get_absolute_url()).content.decode()
        self.assertNotIn(self.tab_url, detail)
        self.assertEqual(self.client.get(self.tab_url).status_code, 403)
        self.add_permissions(DEVICE)
        detail = self.client.get(self.ap.get_absolute_url()).content.decode()
        self.assertIn(self.tab_url, detail)

    def test_restricted_devices_are_not_listed(self):
        self.add_permissions(CONVENTION)
        self.restrict_devices(site__slug=self.site.slug)
        response = self.client.get(self.tab_url)
        values = [t.value for t in response.context["page"].object_list]
        self.assertEqual(values, ["ap01", "ap02", "ap03", "ap05"])
        self.assertNotIn("ap09", response.content.decode())

    def test_inventory_pages_use_nothing_up(self):
        self.add_permissions(CONVENTION, DEVICE)
        self.client.get(self.list_url)
        self.client.get(self.tab_url)
        self.assertFalse(NamingCounter.objects.exists())

    def test_menu_item_needs_both_permissions(self):
        home = reverse("home")
        self.add_permissions(CONVENTION)
        self.assertNotIn(self.list_url, self.client.get(home).content.decode())
        self.add_permissions(DEVICE)
        self.assertIn(self.list_url, self.client.get(home).content.decode())
