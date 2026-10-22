from netbox.plugins import PluginMenu, PluginMenuButton, PluginMenuItem

conventions_item = PluginMenuItem(
    link="plugins:netbox_naming:namingconvention_list",
    link_text="Naming Conventions",
    permissions=["netbox_naming.view_namingconvention"],
    buttons=(
        PluginMenuButton(
            link="plugins:netbox_naming:namingconvention_add",
            title="Add",
            icon_class="mdi mdi-plus-thick",
            permissions=["netbox_naming.add_namingconvention"],
        ),
    ),
)

menu = PluginMenu(
    label="Naming",
    groups=(("Conventions", (conventions_item,)),),
    icon_class="mdi mdi-label-outline",
)
