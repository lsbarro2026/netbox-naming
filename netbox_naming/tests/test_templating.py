import ast
from pathlib import Path
from types import SimpleNamespace as NS

from django.test import SimpleTestCase

from netbox_naming import templating
from netbox_naming.exceptions import MissingToken, NamingError, TemplateError
from netbox_naming.templating import (
    TOKENS,
    Literal,
    NumberRun,
    Token,
    cf_token_names,
    is_known_token,
    parse_template,
    resolve_token,
)


class ParseValidTest(SimpleTestCase):
    def test_valid_templates(self):
        cases = {
            "core-sw": [Literal("core-sw")],
            "ap##": [Literal("ap"), NumberRun(2)],
            "#": [NumberRun(1)],
            "#########": [NumberRun(9)],
            "{room}-ap##": [Token("room"), Literal("-ap"), NumberRun(2)],
            "{room}-{asset_tag}": [Token("room"), Literal("-"), Token("asset_tag")],
            "{site_slug}-{tail}": [Token("site_slug"), Literal("-"), Token("tail")],
            "{tail}": [Token("tail")],
            "{cf_pod_id}x": [Token("cf_pod_id"), Literal("x")],
            "{role}{device_type}": [Token("role"), Token("device_type")],
            "a{site}##{rack}b": [
                Literal("a"),
                Token("site"),
                NumberRun(2),
                Token("rack"),
                Literal("b"),
            ],
        }
        for template, expected in cases.items():
            with self.subTest(template=template):
                self.assertEqual(parse_template(template), expected)


class ParseRejectionTest(SimpleTestCase):
    def assertRejected(self, templates):
        for template in templates:
            with self.subTest(template=template), self.assertRaises(TemplateError):
                parse_template(template)

    def test_empty(self):
        self.assertRejected([""])

    def test_unknown_tokens(self):
        self.assertRejected(["{nope}", "{Room}", "{ROOM}", "{1room}", "{_room}", "{room-x}"])

    def test_empty_and_whitespace_braces(self):
        self.assertRejected(["{}", "{ room }", "{ro om}", "{room\t}", "{room\n}"])

    def test_unbalanced_braces(self):
        self.assertRejected(
            ["{room", "room}", "{{room}}", "{a{room}}", "{", "}", "{room#}", "{ro#om}"]
        )

    def test_number_runs(self):
        self.assertRejected(["ap##-##", "#a#", "##########", "ap##########"])

    def test_tail_must_be_last(self):
        self.assertRejected(
            ["{tail}x", "{tail}-{room}", "{tail}{tail}", "{tail}##", "{tail}{tail}"]
        )

    def test_bare_cf_prefix(self):
        self.assertRejected(["{cf_}", "{cf}"])

    def test_injection_strings(self):
        self.assertRejected(
            [
                "{x.__class__}",
                "{x[0]}",
                "{x:>999999}",
                "{x!r}",
                "{site.name}",
                "{site:>999999999}",
                "{event.__init__.__globals__[CONFIG][SECRET_KEY]}",
                "{room!s}",
                "{room:>20}",
                "{0}",
                "{__class__}",
            ]
        )

    def test_error_is_naming_error(self):
        with self.assertRaises(NamingError):
            parse_template("{nope}")


class RegistryTest(SimpleTestCase):
    def setUp(self):
        manufacturer = NS(name="Ubiquiti", slug="ubiquiti")
        self.ctx = NS(
            location=NS(name="Room 1", slug="room-1"),
            site=NS(name="Site A", slug="site-a"),
            role=NS(name="Access Point", slug="access-point"),
            device_type=NS(model="U6 Pro", slug="u6-pro", manufacturer=manufacturer),
            rack=NS(name="R7"),
            tenant=NS(name="Acme", slug="acme"),
            platform=NS(name="UniFi", slug="unifi"),
            serial="SN123",
            custom_fields={"pod": "p4", "count": 3, "flag": False, "none": None},
            asset_tag=None,
            name=None,
        )

    def test_values(self):
        expected = {
            "room": "Room 1",
            "location_slug": "room-1",
            "site": "Site A",
            "site_slug": "site-a",
            "role": "Access Point",
            "role_slug": "access-point",
            "device_type": "U6 Pro",
            "device_type_slug": "u6-pro",
            "manufacturer": "Ubiquiti",
            "manufacturer_slug": "ubiquiti",
            "rack": "R7",
            "tenant": "Acme",
            "tenant_slug": "acme",
            "platform": "UniFi",
            "platform_slug": "unifi",
            "serial": "SN123",
        }
        for name, value in expected.items():
            with self.subTest(token=name):
                self.assertEqual(resolve_token(name, self.ctx), value)

    def test_registry_covers_plan_table(self):
        self.assertEqual(
            set(TOKENS),
            {
                "room", "location_slug", "site", "site_slug", "role", "role_slug", "device_type",
                "device_type_slug", "manufacturer", "manufacturer_slug", "rack", "tenant",
                "tenant_slug", "platform", "platform_slug", "serial", "asset_tag", "name", "tail",
            },
        )  # fmt: skip

    def test_none_at_each_hop(self):
        for attr in ("location", "site", "role", "device_type", "rack", "tenant", "platform"):
            setattr(self.ctx, attr, None)
        for name in TOKENS:
            if name in ("serial", "asset_tag", "name", "tail"):
                continue
            with self.subTest(token=name):
                self.assertIsNone(resolve_token(name, self.ctx))

    def test_manufacturer_none_through_device_type(self):
        self.ctx.device_type = NS(model="X", slug="x", manufacturer=None)
        self.assertIsNone(resolve_token("manufacturer", self.ctx))
        self.assertIsNone(resolve_token("manufacturer_slug", self.ctx))

    def test_empty_serial_is_none(self):
        self.ctx.serial = ""
        self.assertIsNone(resolve_token("serial", self.ctx))

    def test_nested_values_come_from_context(self):
        self.assertIsNone(resolve_token("asset_tag", self.ctx))
        self.assertIsNone(resolve_token("name", self.ctx))
        self.ctx.asset_tag = "ap07"
        self.ctx.name = "r1-ap07"
        self.assertEqual(resolve_token("asset_tag", self.ctx), "ap07")
        self.assertEqual(resolve_token("name", self.ctx), "r1-ap07")

    def test_tail_comes_from_argument(self):
        self.assertIsNone(resolve_token("tail", self.ctx))
        self.assertEqual(resolve_token("tail", self.ctx, tail="lobby"), "lobby")

    def test_custom_fields(self):
        self.assertEqual(resolve_token("cf_pod", self.ctx), "p4")
        self.assertEqual(resolve_token("cf_count", self.ctx), "3")
        self.assertEqual(resolve_token("cf_flag", self.ctx), "False")
        self.assertIsNone(resolve_token("cf_none", self.ctx))
        self.assertIsNone(resolve_token("cf_missing", self.ctx))

    def test_unknown_token_raises(self):
        with self.assertRaises(TemplateError):
            resolve_token("nope", self.ctx)

    def test_is_known_token(self):
        self.assertTrue(is_known_token("room"))
        self.assertTrue(is_known_token("cf_x"))
        self.assertFalse(is_known_token("cf_"))
        self.assertFalse(is_known_token("nope"))

    def test_cf_token_names(self):
        parts = parse_template("{cf_pod}-{room}-{cf_zone}")
        self.assertEqual(cf_token_names(parts), ["pod", "zone"])

    def test_missing_token_carries_name(self):
        error = MissingToken("room")
        self.assertEqual(error.token, "room")
        self.assertIn("{room}", str(error))


class NoFormattingTest(SimpleTestCase):
    """The module must never hand user input to a formatting or template engine."""

    def test_module_avoids_format_apis(self):
        tree = ast.parse(Path(templating.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(
                    node.attr, {"format", "format_map", "substitute", "safe_substitute"}
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], {"string", "jinja2"})
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], {"string", "jinja2"})
