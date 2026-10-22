import ast
import inspect

from dcim.models import Device

from netbox_naming import generator
from netbox_naming.choices import CounterScopeChoices, TargetFieldChoices
from netbox_naming.engine import NamingContext, allocate, preview
from netbox_naming.generator import (
    MAX_COUNT,
    NUMBER,
    collapse_ranges,
    generate,
    inventory,
    series_pattern,
)
from netbox_naming.models import NamingCounter
from netbox_naming.tests.test_engine import EngineTestBase

NAME = TargetFieldChoices.NAME
ASSET_TAG = TargetFieldChoices.ASSET_TAG


class CollapseRangesTest(EngineTestBase):
    def test_collapse_ranges(self):
        self.assertEqual(collapse_ranges([]), [])
        self.assertEqual(collapse_ranges([5]), [(5, 5)])
        self.assertEqual(collapse_ranges([12, 3, 1, 2, 2, 7, 9, 8]), [(1, 3), (7, 9), (12, 12)])


class SeriesPatternTest(EngineTestBase):
    def test_literals_are_escaped(self):
        pattern, names = series_pattern(self.convention("a.b-##", save=False))
        self.assertEqual(names, [NUMBER])
        self.assertTrue(pattern.fullmatch("a.b-01"))
        self.assertIsNone(pattern.fullmatch("axb-01"))
        self.assertIsNone(pattern.fullmatch("a.b-1"))

    def test_tokens_and_case(self):
        pattern, names = series_pattern(self.convention("{site_slug}-sw##", save=False))
        self.assertEqual(names, ["site_slug", NUMBER])
        self.assertEqual(pattern.fullmatch("LON-SW07").groups(), ("LON", "07"))

    def test_asset_tag_is_case_sensitive(self):
        pattern, _ = series_pattern(self.convention(target_field=ASSET_TAG, save=False))
        self.assertTrue(pattern.fullmatch("ap01"))
        self.assertIsNone(pattern.fullmatch("AP01"))

    def test_tail(self):
        pattern, names = series_pattern(self.convention("x-{tail}", save=False))
        self.assertEqual(names, ["tail"])
        self.assertTrue(pattern.fullmatch("x-foo.1_a"))
        self.assertIsNone(pattern.fullmatch("x-a b"))


class InventoryTest(EngineTestBase):
    def numbers(self, series):
        return [t.number for t in series.taken]

    def test_near_misses_are_excluded(self):
        convention = self.convention(target_field=ASSET_TAG)
        for tag in ("ap04", "ap01", "ap02", "ap01-old", "xap05", "ap5"):
            self.device(asset_tag=tag)
        [series] = inventory(convention, Device.objects.all()).series
        self.assertEqual(series.label, "ap##")
        self.assertIsNone(series.scope)
        self.assertEqual([t.value for t in series.taken], ["ap01", "ap02", "ap04"])
        self.assertEqual(series.ranges, [(1, 2), (4, 4)])
        self.assertEqual(series.highest.value, "ap04")
        self.assertEqual(series.next, preview(convention, self.context())[0])
        self.assertEqual(series.next.value, "ap05")

    def test_name_series_ignores_case(self):
        convention = self.convention()
        self.device("AP01")
        self.device("ap02")
        [series] = inventory(convention, Device.objects.all()).series
        self.assertEqual(self.numbers(series), [1, 2])
        self.assertEqual(series.next.value, "ap03")

    def test_next_free_is_past_the_counter(self):
        convention = self.convention(target_field=ASSET_TAG)
        allocate(convention, self.context(), 3)
        self.device(asset_tag="ap01")
        [series] = inventory(convention, Device.objects.all()).series
        self.assertEqual(series.ranges, [(1, 1)])
        self.assertEqual(series.next.value, "ap04")

    def test_series_split_by_token(self):
        convention = self.convention("{site_slug}-sw##")
        self.device("lon-sw01")
        self.device("lon-sw02")
        self.device("par-sw01", site=self.other_site)
        series = inventory(convention, Device.objects.all()).series
        self.assertEqual([s.label for s in series], ["lon-sw##", "par-sw##"])
        self.assertEqual([self.numbers(s) for s in series], [[1, 2], [1]])
        self.assertEqual([s.next.value for s in series], ["lon-sw03", "par-sw02"])

    def test_series_split_by_location_scope(self):
        convention = self.convention(counter_scope=CounterScopeChoices.LOCATION)
        self.device("ap01", location=self.room)
        self.device("ap02", location=self.room)
        self.device("ap03", location=self.other_room)
        self.device("ap05")
        series = {s.scope: s for s in inventory(convention, Device.objects.all()).series}
        self.assertEqual(set(series), {self.room, self.other_room, None})
        self.assertEqual(self.numbers(series[self.room]), [1, 2])
        self.assertEqual(self.numbers(series[self.other_room]), [3])
        self.assertEqual(self.numbers(series[None]), [5])
        # R101's counter is at 2, but ap03 is taken by name in the site.
        self.assertEqual(series[self.room].next.value, "ap04")
        self.assertEqual(series[self.other_room].next.value, "ap04")
        self.assertIsNone(series[None].next)

    def test_moved_device_has_no_next_free(self):
        convention = self.convention("{site_slug}-sw##")
        device = self.device("lon-sw01")
        device.site = self.other_site
        device.save()
        [series] = inventory(convention, Device.objects.all()).series
        self.assertEqual(series.label, "lon-sw##")
        self.assertEqual(series.highest.device, device)
        self.assertIsNone(series.next)

    def test_nested_token_keeps_the_representatives_value(self):
        self.convention(target_field=ASSET_TAG)
        convention = self.convention("{asset_tag}-##")
        self.device("ap07-01", "ap07")
        [series] = inventory(convention, Device.objects.all()).series
        self.assertEqual(series.label, "ap07-##")
        self.assertEqual(series.next.value, "ap07-02")

    def test_static_lists_values_from_the_given_devices(self):
        convention = self.convention("{site_slug}-core")
        self.device("lon-core")
        self.device("par-core", site=self.other_site)
        self.device("lon-edge")
        [series] = inventory(convention, Device.objects.all()).series
        self.assertEqual(series.label, "{site_slug}-core")
        self.assertEqual([t.value for t in series.taken], ["lon-core", "par-core"])
        self.assertEqual({t.number for t in series.taken}, {None})
        self.assertEqual((series.ranges, series.highest, series.next), ([], None, None))

        [series] = inventory(convention, Device.objects.filter(site=self.site)).series
        self.assertEqual([t.value for t in series.taken], ["lon-core"])

    def test_no_values(self):
        convention = self.convention()
        self.assertEqual(inventory(convention, Device.objects.all()).series, [])


class GenerateTest(EngineTestBase):
    def column(self, generation, field):
        return [getattr(row, field) and getattr(row, field).value for row in generation.rows]

    def test_nested_name_pairs_with_its_tags(self):
        tag_convention = self.convention(target_field=ASSET_TAG)
        name_convention = self.convention("{room}-{asset_tag}")
        generation = generate(role=self.role, location=self.room, count=3)
        self.assertEqual(generation.messages, [])
        self.assertEqual(generation.name_convention, name_convention)
        self.assertEqual(generation.asset_tag_convention, tag_convention)
        self.assertEqual([row.index for row in generation.rows], [1, 2, 3])
        self.assertEqual(self.column(generation, "name"), ["R101-ap01", "R101-ap02", "R101-ap03"])
        self.assertEqual(self.column(generation, "asset_tag"), ["ap01", "ap02", "ap03"])
        self.assertEqual(
            [row.name.parts["asset_tag"] for row in generation.rows],
            self.column(generation, "asset_tag"),
        )

    def test_separate_conventions_pair_by_row(self):
        self.convention(target_field=ASSET_TAG)
        self.convention("{site_slug}-ap##", device_type=self.ap_type)
        generation = generate(role=self.role, device_type=self.ap_type, location=self.room, count=2)
        self.assertEqual(self.column(generation, "name"), ["lon-ap01", "lon-ap02"])
        self.assertEqual(self.column(generation, "asset_tag"), ["ap01", "ap02"])

    def test_role_or_device_type_is_required(self):
        generation = generate()
        self.assertEqual(generation.rows, [])
        self.assertEqual(generation.messages, ["Pick a role or a device type."])

    def test_missing_convention_leaves_its_column_empty(self):
        self.convention()
        generation = generate(role=self.role, count=2)
        self.assertEqual(self.column(generation, "name"), ["ap01", "ap02"])
        self.assertEqual(self.column(generation, "asset_tag"), [None, None])
        self.assertIsNone(generation.asset_tag_convention)
        self.assertEqual(
            generation.messages,
            ["No asset tag convention matches this role and device type."],
        )

    def test_missing_nested_convention_is_reported_once(self):
        self.convention("{room}-{asset_tag}")
        generation = generate(role=self.role, location=self.room)
        self.assertEqual(generation.rows, [])
        self.assertEqual(
            generation.messages,
            ["No asset tag convention matches this role and device type."],
        )

    def test_missing_location_token(self):
        self.convention(target_field=ASSET_TAG)
        self.convention("{room}-##")
        generation = generate(role=self.role, count=2)
        self.assertEqual(self.column(generation, "name"), [None, None])
        self.assertEqual(self.column(generation, "asset_tag"), ["ap01", "ap02"])
        self.assertEqual(generation.messages, ["Pick a Location: the name template uses {room}."])

    def test_other_missing_token(self):
        self.convention("{rack}-##")
        generation = generate(role=self.role)
        self.assertIn(
            "The name template uses {rack}, which has no value here.", generation.messages
        )

    def test_tail(self):
        self.convention("ap-{tail}")
        generation = generate(role=self.role, tail="x1", count=1)
        self.assertEqual(self.column(generation, "name"), ["ap-x1"])
        self.assertIn(
            "Enter a tail: the name template uses {tail}.", generate(role=self.role).messages
        )
        messages = generate(role=self.role, tail="bad tail").messages
        self.assertTrue(any(m.startswith("Name: Tail 'bad tail'") for m in messages))

    def test_conflict_is_flagged(self):
        self.convention("{site_slug}-core")
        self.device("lon-core")
        [row] = generate(role=self.role, location=self.room, count=1).rows
        self.assertEqual((row.name.value, row.name.conflict), ("lon-core", True))

    def test_count_is_clamped(self):
        self.convention("ap###")
        self.assertEqual(len(generate(role=self.role, count=0).rows), 1)
        self.assertEqual(len(generate(role=self.role, count=99).rows), MAX_COUNT)


class ReadOnlyTest(EngineTestBase):
    def test_counters_unchanged(self):
        tag_convention = self.convention(target_field=ASSET_TAG)
        name_convention = self.convention("{room}-{asset_tag}")
        numbered = self.convention("sw##", role=self.other_role)
        allocate(tag_convention, self.context(), 2)
        allocate(numbered, NamingContext(role=self.other_role), 1)
        self.device("R101-ap01", "ap01", location=self.room)
        before = list(NamingCounter.objects.order_by("pk").values_list())

        for convention in (tag_convention, name_convention, numbered):
            inventory(convention, Device.objects.all())
        generate(role=self.role, location=self.room, count=5)
        generate(role=self.other_role, count=5)

        self.assertEqual(list(NamingCounter.objects.order_by("pk").values_list()), before)

    def test_never_imports_allocate(self):
        tree = ast.parse(inspect.getsource(generator))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom | ast.Import)
            for alias in node.names
        }
        self.assertNotIn("allocate", imported)
        self.assertFalse(hasattr(generator, "allocate"))
