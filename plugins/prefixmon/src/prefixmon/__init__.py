__version__ = "0.1.0"

from prefixmon.plugin import PrefixmonPluginConfig

# NetBox requires this to be the PluginConfig class (object), not a string
config = PrefixmonPluginConfig
