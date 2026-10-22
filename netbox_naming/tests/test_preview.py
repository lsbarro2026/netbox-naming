from core.models import ObjectType
from dcim.models import DeviceRole, Location
from django.test import override_settings
from django.urls import reverse
from users.models import ObjectPermission
from utilities.testing import TestCase

from netbox_naming.choices import KindChoices, TargetFieldChoices
from netbox_naming.models import NamingConvention, NamingCounter
from netbox_naming.preview import SAMPLE_COUNT
from netbox_naming.tests.test_engine import EngineTestBase

ADD = "netbox_naming.add_namingconvention"
DEVICE = "dcim.view_device"
# What the user needs to see the form's role, device type and location picks.
PICKERS = ("dcim.view_devicerole", "dcim.view_devicetype", "dcim.view_location")


@override_settings(EXEMPT_VIEW_PERMISSIONS=[])
# utilities TestCase adds the logged-in user and client
class TemplatePreviewViewTest(EngineTestBase, TestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("plugins:netbox_naming:namingconvention_preview")

    def post(self, **data):
        fields = {
            "kind": KindChoices.NUMBERED,
            "target_field": TargetFieldChoices.NAME,
            "template": "ap##",
            "role": self.role.pk,
        }
        fields.update(data)
        return self.client.post(self.url, fields)

    def preview(self, **data):
        response = self.post(**data)
        self.assertEqual(response.status_code, 200)
        return response.context["preview"]

    def allow(self, model, action, **constraints):
        perm = ObjectPermission.objects.create(
            name=f"{action} some {model._meta.model_name}",
            actions=[action],
            constraints=constraints,
        )
        perm.users.add(self.user)
        perm.object_types.add(ObjectType.objects.get_for_model(model))

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        self.assertEqual(self.post().status_code, 302)

    def test_get_is_not_allowed(self):
        self.add_permissions(ADD, DEVICE)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_add_needs_add_and_device_permissions(self):
        self.assertEqual(self.post().status_code, 403)
        self.add_permissions("netbox_naming.view_namingconvention", DEVICE)
        response = self.post()
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, ADD, status_code=403)
        self.remove_permissions(DEVICE)
        self.add_permissions(ADD)
        self.assertContains(self.post(), DEVICE, status_code=403)
        self.add_permissions(DEVICE)
        self.assertEqual(self.post().status_code, 200)

    def test_edit_needs_change_on_that_convention(self):
        convention = self.convention("ap##")
        other = self.convention("sw##", role=self.other_role)
        self.add_permissions(ADD, DEVICE)
        # Add alone doesn't cover an existing convention.
        self.assertEqual(self.post(pk=convention.pk).status_code, 404)
        self.allow(NamingConvention, "change", pk=other.pk)
        self.assertEqual(self.post(pk=convention.pk).status_code, 404)
        self.assertEqual(self.post(pk=other.pk).status_code, 200)
        self.assertEqual(self.post(pk="x").status_code, 404)

    def test_hidden_ids_count_as_absent(self):
        self.add_permissions(ADD, DEVICE, "dcim.view_devicetype")
        self.allow(DeviceRole, "view", pk=self.other_role.pk)
        self.allow(Location, "view", pk=self.other_room.pk)
        preview = self.preview(template="{role_slug}-{room}-##", preview_location=self.room.pk)
        self.assertEqual(preview.shape, "‹role_slug›-‹room›-##")
        self.assertIn(
            "A convention must name a device role, a device type, or both.", preview.messages
        )

    def test_visible_ids_render(self):
        self.add_permissions(ADD, DEVICE, *PICKERS)
        preview = self.preview(template="{role_slug}-{room}-##", preview_location=self.room.pk)
        self.assertIsNone(preview.shape)
        self.assertEqual(
            self.values(preview.proposals)[:2], ["access-point-R101-01", "access-point-R101-02"]
        )

    def test_unknown_token_is_highlighted(self):
        self.add_permissions(ADD, DEVICE, *PICKERS)
        response = self.post(template="ap-{bogus}##")
        self.assertContains(response, "<code>ap-<mark>{bogus}</mark>##</code>", html=True)
        self.assertEqual(response.context["preview"].proposals, [])

    def test_shape_mode_without_a_location(self):
        self.add_permissions(ADD, DEVICE, *PICKERS)
        preview = self.preview(template="{room}-ap##")
        self.assertEqual(preview.shape, "‹room›-ap##")
        self.assertEqual(preview.proposals, [])
        self.assertIn("Needs a Location to show real numbers.", preview.messages)
        preview = self.preview(template="{room}-ap##", preview_location=self.room.pk)
        self.assertEqual(self.values(preview.proposals)[0], "R101-ap01")

    def test_tail_needs_a_sample_tail(self):
        self.add_permissions(ADD, DEVICE, *PICKERS)
        preview = self.preview(kind=KindChoices.TAIL, template="ap-{tail}")
        self.assertEqual(preview.shape, "ap-‹tail›")
        preview = self.preview(kind=KindChoices.TAIL, template="ap-{tail}", preview_tail="lobby")
        self.assertEqual(self.values(preview.proposals), ["ap-lobby"])

    def test_conflict_is_marked(self):
        self.add_permissions(ADD, DEVICE, *PICKERS)
        self.device(asset_tag="TAG-1")
        response = self.post(
            kind=KindChoices.STATIC, target_field=TargetFieldChoices.ASSET_TAG, template="TAG-1"
        )
        self.assertTrue(response.context["preview"].proposals[0].conflict)
        self.assertContains(response, "Already taken")

    def test_count_is_capped(self):
        self.add_permissions(ADD, DEVICE, *PICKERS)
        self.assertEqual(len(self.preview(count=50).proposals), SAMPLE_COUNT)

    def test_kind_mismatch_hints_the_implied_kind(self):
        self.add_permissions(ADD, DEVICE, *PICKERS)
        preview = self.preview(kind=KindChoices.STATIC)
        self.assertIn("This template looks like a numbered convention.", preview.messages)
        self.assertEqual(preview.proposals, [])

    def test_previews_write_nothing(self):
        convention = self.convention("ap##")
        NamingCounter.objects.create(scope_key="some-key", last_value=7)
        self.device(name="ap01")
        self.add_permissions(ADD, "netbox_naming.change_namingconvention", DEVICE, *PICKERS)
        before = list(NamingCounter.objects.values_list("scope_key", "last_value"))
        self.preview()
        self.preview(pk=convention.pk, template="ap###")
        self.preview(template="{room}-ap##", preview_location=self.room.pk)
        self.assertEqual(list(NamingCounter.objects.values_list("scope_key", "last_value")), before)
        self.assertEqual(NamingConvention.objects.count(), 1)
        convention.refresh_from_db()
        self.assertEqual(convention.template, "ap##")


@override_settings(EXEMPT_VIEW_PERMISSIONS=[])
class SampleValuesPanelTest(EngineTestBase, TestCase):
    def setUp(self):
        super().setUp()
        self.url = self.convention("ap##").get_absolute_url()
        self.add_permissions("netbox_naming.view_namingconvention")

    def test_shows_sample_values(self):
        self.add_permissions(DEVICE)
        response = self.client.get(self.url)
        self.assertContains(response, "Sample values")
        self.assertContains(response, "<code>ap05</code>", html=True)

    def test_hidden_without_device_permission(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Hidden: sample values need")
        self.assertNotContains(response, "<code>ap01</code>", html=True)
