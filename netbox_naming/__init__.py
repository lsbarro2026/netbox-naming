from netbox.plugins import PluginConfig


class NetBoxNamingConfig(PluginConfig):
    name = "netbox_naming"
    verbose_name = "Naming Conventions"
    description = "Generate and validate device names from naming conventions."
    version = "0.1.0"
    author = "lsbarro"
    base_url = "naming"
    min_version = "4.6.0"
    max_version = "4.7.99"


config = NetBoxNamingConfig
