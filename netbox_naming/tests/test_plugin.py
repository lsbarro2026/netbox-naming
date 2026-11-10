from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase


class PluginLoadedTest(SimpleTestCase):
    def test_plugin_enabled(self):
        self.assertIn("netbox_naming", settings.PLUGINS)

    def test_app_installed(self):
        self.assertTrue(apps.is_installed("netbox_naming"))

    def test_config(self):
        config = apps.get_app_config("netbox_naming")
        self.assertEqual(config.base_url, "naming")
        self.assertEqual(config.min_version, "4.6.0")
        self.assertEqual(config.max_version, "4.7.99")
