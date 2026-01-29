from netbox.plugins import PluginConfig


class PrefixmonPluginConfig(PluginConfig):
    name = "prefixmon"
    verbose_name = "Prefixmon"
    description = "Prefix monitoring for NetBox (cloud subnets, Zabbix LLD)"
    version = "0.1.0"
    author = "Your Name"
    base_url = "prefixmon"
    default_settings = {}


config = PrefixmonPluginConfig
