from netbox.plugins import PluginMenu, PluginMenuItem

cloud_subnets_item = PluginMenuItem(
    link="plugins:prefixmon:cloud_subnets",
    link_text="Cloud Subnets",
)

settings_item = PluginMenuItem(
    link="plugins:prefixmon:settings",
    link_text="Settings",
    staff_only=True,
)

menu = PluginMenu(
    label="Prefixmon",
    groups=(("Cloud", (cloud_subnets_item, settings_item)),),
    icon_class="mdi mdi-cloud-network",
)

menu_items = [cloud_subnets_item, settings_item]
