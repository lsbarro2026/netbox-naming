import itertools

from dcim.models import Device, DeviceRole, DeviceType, Location, Manufacturer, Site
from django.test import TestCase
from tenancy.models import Tenant

from netbox_naming.choices import CounterScopeChoices, KindChoices, TargetFieldChoices
from netbox_naming.engine import (
    NamingContext,
    _scope_key,
    allocate,
    find_convention,
    preview,
)
from netbox_naming.exceptions import (
    Conflict,
    InvalidTail,
    MissingToken,
    NumbersExhausted,
    TemplateError,
    TooLong,
)
from netbox_naming.models import NamingConvention, NamingCounter

NAME = TargetFieldChoices.NAME
ASSET_TAG = TargetFieldChoices.ASSET_TAG


def _kind(template):
    if "#" in template:
        return KindChoices.NUMBERED
    if template.endswith("{tail}"):
        return KindChoices.TAIL
    return KindChoices.STATIC


class EngineTestBase(TestCase):
    _names = itertools.count()

    @classmethod
    def setUpTestData(cls):
        manufacturer = Manufacturer.objects.create(name="Acme", slug="acme")
        cls.ap_type = DeviceType.objects.create(
            manufacturer=manufacturer, model="AP-1", slug="ap-1"
        )
        cls.other_type = DeviceType.objects.create(
            manufacturer=manufacturer, model="SW-1", slug="sw-1"
        )
        cls.role = DeviceRole.objects.create(name="Access Point", slug="access-point")
        cls.other_role = DeviceRole.objects.create(name="Switch", slug="switch")
        cls.site = Site.objects.create(name="London", slug="lon")
        cls.other_site = Site.objects.create(name="Paris", slug="par")
        cls.room = Location.objects.create(name="R101", slug="r101", site=cls.site)
        cls.other_room = Location.objects.create(name="R102", slug="r102", site=cls.site)
        cls.tenant = Tenant.objects.create(name="Blue", slug="blue")

    def convention(self, template="ap##", *, save=True, **kwargs):
        attrs = {
            "name": f"conv-{next(self._names)}",
            "kind": _kind(template),
            "target_field": NAME,
            "template": template,
            "role": self.role,
        }
        attrs.update(kwargs)
        convention = NamingConvention(**attrs)
        if save:
            convention.full_clean()
            convention.save()
        return convention

    def context(self, **kwargs):
        attrs = {
            "role": self.role,
            "device_type": self.ap_type,
            "site": self.site,
            "location": self.room,
        }
        attrs.update(kwargs)
        return NamingContext(**attrs)

    def device(self, name=None, asset_tag=None, *, site=None, location=None, tenant=None):
        return Device.objects.create(
            device_type=self.ap_type,
            role=self.role,
            site=site or self.site,
            location=location,
            tenant=tenant,
            name=name,
            asset_tag=asset_tag,
        )

    def values(self, proposals):
        return [p.value for p in proposals]


class MatchingTest(EngineTestBase):
    def test_precedence(self):
        by_role = self.convention(role=self.role)
        by_type = self.convention(role=None, device_type=self.ap_type)
        by_both = self.convention(role=self.role, device_type=self.ap_type)
        self.assertEqual(find_convention(NAME, self.role, self.ap_type), by_both)
        by_both.delete()
        self.assertEqual(find_convention(NAME, self.role, self.ap_type), by_type)
        by_type.delete()
        self.assertEqual(find_convention(NAME, self.role, self.ap_type), by_role)

    def test_no_match(self):
        self.convention(role=self.role, device_type=self.ap_type)
        self.assertIsNone(find_convention(NAME, self.role, self.other_type))
        self.assertIsNone(find_convention(NAME, self.other_role, self.ap_type))
        self.assertIsNone(find_convention(NAME, None, None))
        self.assertIsNone(find_convention(ASSET_TAG, self.role, self.ap_type))

    def test_none_role_matches_type_slot(self):
        by_type = self.convention(role=None, device_type=self.ap_type)
        self.assertEqual(find_convention(NAME, None, self.ap_type), by_type)
        self.assertIsNone(find_convention(NAME, self.role, None))

    def test_context_from_device(self):
        device = self.device("ap01", "tag01", location=self.room, tenant=self.tenant)
        context = NamingContext.from_device(device)
        self.assertEqual(context.role, self.role)
        self.assertEqual(context.device_type, self.ap_type)
        self.assertEqual(context.site, self.site)
        self.assertEqual(context.location, self.room)
        self.assertEqual(context.tenant, self.tenant)
        self.assertEqual(context.serial, "")
        self.assertEqual((context.name, context.asset_tag), ("ap01", "tag01"))


class NumberedTest(EngineTestBase):
    def test_preview_from_empty(self):
        proposals = preview(self.convention(), self.context(), 5)
        self.assertEqual(self.values(proposals), ["ap01", "ap02", "ap03", "ap04", "ap05"])
        self.assertEqual([p.number for p in proposals], [1, 2, 3, 4, 5])
        self.assertFalse(any(p.conflict for p in proposals))
        self.assertFalse(NamingCounter.objects.exists())

    def test_scan_counts_hand_entered_values(self):
        for name in ("ap03", "AP07", "ap01-old", "xap05", "ap100"):
            self.device(name)
        self.assertEqual(
            self.values(preview(self.convention(), self.context(), 2)), ["ap08", "ap09"]
        )

    def test_asset_tag_scan_is_case_sensitive(self):
        self.device(asset_tag="ap05")
        self.device(asset_tag="AP03")
        convention = self.convention("AP##", target_field=ASSET_TAG)
        self.assertEqual(self.values(preview(convention, self.context())), ["AP04"])

    def test_allocate_spends_numbers_and_never_reuses(self):
        convention = self.convention()
        self.device("ap02")
        self.assertEqual(
            self.values(allocate(convention, self.context(), 3)), ["ap03", "ap04", "ap05"]
        )
        self.assertEqual(NamingCounter.objects.get().last_value, 5)
        Device.objects.filter(name="ap02").delete()
        # The counter is above the scan, so it wins; previews don't move it.
        self.assertEqual(self.values(preview(convention, self.context())), ["ap06"])
        self.assertEqual(self.values(preview(convention, self.context())), ["ap06"])
        self.assertEqual(NamingCounter.objects.get().last_value, 5)
        self.assertEqual(self.values(allocate(convention, self.context())), ["ap06"])
        self.assertEqual(NamingCounter.objects.get().last_value, 6)

    def test_conventions_rendering_one_pattern_share_a_counter(self):
        first = self.convention()
        second = self.convention(role=self.other_role)
        allocate(first, self.context(), 2)
        context = self.context(role=self.other_role)
        self.assertEqual(self.values(preview(second, context)), ["ap03"])
        self.assertEqual(NamingCounter.objects.count(), 1)

    def test_site_scoped_counters_are_separate(self):
        convention = self.convention(counter_scope=CounterScopeChoices.SITE)
        allocate(convention, self.context(), 2)
        other = self.context(site=self.other_site, location=None)
        self.assertEqual(self.values(preview(convention, other)), ["ap01"])

    def test_scope_needs_its_object(self):
        site_scoped = self.convention(counter_scope=CounterScopeChoices.SITE)
        with self.assertRaises(MissingToken) as ctx:
            preview(site_scoped, self.context(site=None))
        self.assertEqual(ctx.exception.token, "site")
        location_scoped = self.convention(
            counter_scope=CounterScopeChoices.LOCATION, role=self.other_role
        )
        with self.assertRaises(MissingToken) as ctx:
            preview(location_scoped, self.context(location=None))
        self.assertEqual(ctx.exception.token, "location")

    def test_long_scope_key_is_hashed(self):
        key = _scope_key(NAME, "global", None, "x" * 300, 2, "")
        self.assertTrue(key.startswith("sha256:"))
        self.assertLessEqual(len(key), 255)
        self.assertNotIn("\x00", _scope_key(NAME, "site", 3, "ap", 2, "-x"))


class CollisionTest(EngineTestBase):
    def test_asset_tag_skips_tags_outside_the_counter_scope(self):
        self.device(asset_tag="ap02", site=self.other_site)
        convention = self.convention(target_field=ASSET_TAG, counter_scope=CounterScopeChoices.SITE)
        self.assertEqual(
            self.values(preview(convention, self.context(), 3)), ["ap01", "ap03", "ap04"]
        )

    def test_name_skips_names_elsewhere_in_the_site(self):
        self.device("AP02", location=self.other_room)
        convention = self.convention(counter_scope=CounterScopeChoices.LOCATION)
        self.assertEqual(self.values(preview(convention, self.context(), 2)), ["ap01", "ap03"])

    def test_name_under_another_tenant_is_not_taken(self):
        self.device("ap02", location=self.other_room, tenant=self.tenant)
        convention = self.convention(counter_scope=CounterScopeChoices.LOCATION)
        self.assertEqual(self.values(preview(convention, self.context(), 2)), ["ap01", "ap02"])
        context = self.context(tenant=self.tenant)
        self.assertEqual(self.values(preview(convention, context, 2)), ["ap01", "ap03"])

    def test_name_at_another_site_is_not_taken(self):
        self.device("ap01", site=self.other_site)
        convention = self.convention(counter_scope=CounterScopeChoices.SITE)
        self.assertEqual(self.values(preview(convention, self.context())), ["ap01"])


class FixedTest(EngineTestBase):
    def test_static_value(self):
        proposals = preview(self.convention("core-{site_slug}"), self.context())
        self.assertEqual(self.values(proposals), ["core-lon"])
        self.assertEqual((proposals[0].number, proposals[0].conflict), (None, False))

    def test_static_name_conflict_is_case_insensitive(self):
        self.device("CORE-LON")
        convention = self.convention("core-{site_slug}")
        self.assertTrue(preview(convention, self.context())[0].conflict)
        with self.assertRaises(Conflict):
            allocate(convention, self.context())

    def test_static_asset_tag_conflict_is_exact_and_global(self):
        self.device(asset_tag="CORE-LON", site=self.other_site)
        convention = self.convention("core-{site_slug}", target_field=ASSET_TAG)
        self.assertFalse(preview(convention, self.context())[0].conflict)
        self.device(asset_tag="core-lon", site=self.other_site)
        self.assertTrue(preview(convention, self.context())[0].conflict)

    def test_repeat_within_a_batch_conflicts(self):
        convention = self.convention("core-{site_slug}")
        self.assertEqual(
            [p.conflict for p in preview(convention, self.context(), 2)], [False, True]
        )
        with self.assertRaises(Conflict):
            allocate(convention, self.context(), 2)

    def test_tail(self):
        convention = self.convention("{room}-{tail}", tail_max_length=6)
        self.assertEqual(
            self.values(preview(convention, self.context(), tail="a1.b-c")), ["R101-a1.b-c"]
        )
        for bad in ("a b", "a/b", "abcdefg"):
            with self.subTest(tail=bad), self.assertRaises(InvalidTail):
                preview(convention, self.context(), tail=bad)
        for missing in (None, ""):
            with self.subTest(tail=missing), self.assertRaises(MissingToken) as ctx:
                preview(convention, self.context(), tail=missing)
            self.assertEqual(ctx.exception.token, "tail")


class NestingTest(EngineTestBase):
    def test_nested_values_pair_row_by_row(self):
        self.convention(target_field=ASSET_TAG)
        convention = self.convention("{room}-{asset_tag}")
        proposals = preview(convention, self.context(), 3)
        self.assertEqual(self.values(proposals), ["R101-ap01", "R101-ap02", "R101-ap03"])
        self.assertEqual(
            [p.parts for p in proposals], [{"asset_tag": f"ap0{i}"} for i in (1, 2, 3)]
        )
        self.assertEqual({p.number for p in proposals}, {None})

    def test_context_value_wins_over_nesting(self):
        convention = self.convention("{room}-{asset_tag}")
        proposals = preview(convention, self.context(asset_tag="ap42"))
        self.assertEqual(self.values(proposals), ["R101-ap42"])
        self.assertEqual(proposals[0].parts, {})

    def test_missing_dependency(self):
        convention = self.convention("{room}-{asset_tag}")
        with self.assertRaises(MissingToken) as ctx:
            preview(convention, self.context())
        self.assertEqual(ctx.exception.token, "asset_tag")

    def test_allocate_advances_dependency_and_outer_counters(self):
        self.convention(target_field=ASSET_TAG)
        convention = self.convention("{asset_tag}-##")
        proposals = allocate(convention, self.context(), 2)
        self.assertEqual(self.values(proposals), ["ap01-01", "ap02-01"])
        self.assertEqual(
            sorted(NamingCounter.objects.values_list("last_value", flat=True)), [1, 1, 2]
        )

    def test_nested_conflict_flags_the_outer_proposal(self):
        self.device(asset_tag="SN1")
        self.convention("{serial}", target_field=ASSET_TAG)
        convention = self.convention("{room}-{asset_tag}")
        proposal = preview(convention, self.context(serial="SN1"))[0]
        self.assertEqual((proposal.value, proposal.conflict), ("R101-SN1", True))
        with self.assertRaises(Conflict):
            allocate(convention, self.context(serial="SN1"))

    def test_outer_conflict_rolls_back_dependency_numbers(self):
        self.device("R101-ap01")
        self.convention(target_field=ASSET_TAG)
        convention = self.convention("{room}-{asset_tag}")
        with self.assertRaises(Conflict):
            allocate(convention, self.context())
        self.assertFalse(NamingCounter.objects.exists())

    def test_preview_accepts_an_unsaved_convention(self):
        convention = self.convention(save=False)
        self.assertEqual(self.values(preview(convention, self.context())), ["ap01"])

    def test_nesting_deeper_than_one_level_is_refused(self):
        self.convention(target_field=ASSET_TAG)
        self.convention("{room}-{asset_tag}")
        unsaved = self.convention("{name}-x", target_field=ASSET_TAG, save=False)
        with self.assertRaises(TemplateError):
            preview(unsaved, self.context())


class ErrorTest(EngineTestBase):
    def test_missing_token(self):
        with self.assertRaises(MissingToken) as ctx:
            preview(self.convention("{room}-##"), self.context(location=None))
        self.assertEqual(ctx.exception.token, "room")

    def test_numbers_exhausted(self):
        with self.assertRaises(NumbersExhausted):
            preview(self.convention("ap#"), self.context(), 10)

    def test_too_long(self):
        with self.assertRaises(TooLong):
            preview(self.convention("x" * 63 + "##"), self.context())

    def test_template_error(self):
        with self.assertRaises(TemplateError):
            preview(self.convention("{bogus}", save=False), self.context())

    def test_count_must_be_positive(self):
        with self.assertRaises(ValueError):
            preview(self.convention(), self.context(), 0)
