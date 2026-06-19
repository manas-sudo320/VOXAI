"""Exception types used by the plugin framework."""


class PluginError(Exception):
    """Base class for plugin framework errors."""


class PluginDiscoveryError(PluginError):
    """Raised when plugin discovery cannot complete as requested."""


class PluginManifestError(PluginDiscoveryError):
    """Raised when a plugin manifest is missing or invalid."""


class PluginLoadError(PluginError):
    """Raised when a plugin cannot be imported or instantiated."""


class PluginLifecycleError(PluginError):
    """Raised when a plugin lifecycle hook fails."""
