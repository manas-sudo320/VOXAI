"""Application-specific exception types."""


class VoxAIError(Exception):
    """Base class for recoverable VoxAI Studio errors."""


class ConfigError(VoxAIError):
    """Raised when configuration cannot be loaded, saved, or interpreted."""


class ConfigValidationError(ConfigError):
    """Raised when a configuration value fails validation."""
