"""Configuration loading, validation, and persistence.

The configuration system uses a layered model:

1. Built-in defaults are a last-resort safety net.
2. ``config/default.toml`` contains project defaults.
3. The user configuration file overrides the defaults.

Application code should access settings through :class:`ConfigManager` only.
"""

from __future__ import annotations

import copy
import logging
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - kept for older interpreters.
    tomllib = None  # type: ignore[assignment]

from voxai_studio.core.errors import ConfigError, ConfigValidationError
from voxai_studio.core.paths import AppPaths, build_app_paths
from voxai_studio.core.types import ConfigMapping, ConfigValue, MutableConfigMapping

logger = logging.getLogger(__name__)

PathLike = str | os.PathLike[str]

BUILTIN_DEFAULT_CONFIG: dict[str, ConfigValue] = {
    "app": {
        "name": "VoxAI Studio",
        "environment": "production",
        "log_level": "INFO",
    },
    "paths": {
        "data_dir": "data",
        "models_dir": "data/models",
        "plugins_dir": "data/plugins",
        "exports_dir": "exports",
    },
    "ui": {
        "theme": "system",
        "language": "en",
        "remember_window_state": True,
    },
    "audio": {
        "output_format": "wav",
        "sample_rate": 22050,
        "volume": 1.0,
    },
    "tts": {
        "engine": "piper",
        "default_voice": "",
        "speaking_rate": 1.0,
    },
    "translation": {
        "engine": "argos",
        "default_source_language": "auto",
        "default_target_language": "en",
    },
    "language_detection": {
        "engine": "lingua",
        "minimum_confidence": 0.2,
    },
    "plugins": {
        "enabled": True,
        "directories": ["data/plugins"],
    },
    "history": {
        "enabled": True,
        "max_items": 500,
    },
    "database": {
        "url": "sqlite:///voxai_studio.db",
    },
}


@dataclass(frozen=True)
class ConfigValidationIssue:
    """A non-fatal validation problem discovered while loading configuration."""

    path: str
    message: str
    fallback_value: ConfigValue | None = None


@dataclass(frozen=True)
class ConfigSchemaEntry:
    """Validation rules for one dotted configuration path."""

    expected_type: type | tuple[type, ...]
    choices: frozenset[ConfigValue] | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    allow_empty: bool = True

    def validate(self, path: str, value: ConfigValue) -> None:
        """Validate *value* and raise :class:`ConfigValidationError` on failure."""

        if not _matches_expected_type(value, self.expected_type):
            expected = _format_expected_type(self.expected_type)
            actual = type(value).__name__
            raise ConfigValidationError(
                f"Configuration value '{path}' must be {expected}; got {actual}."
            )

        if isinstance(value, str) and not self.allow_empty and not value.strip():
            raise ConfigValidationError(f"Configuration value '{path}' cannot be empty.")

        if self.choices is not None and value not in self.choices:
            choices = ", ".join(str(choice) for choice in sorted(self.choices, key=str))
            raise ConfigValidationError(
                f"Configuration value '{path}' must be one of: {choices}."
            )

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if self.minimum is not None and value < self.minimum:
                raise ConfigValidationError(
                    f"Configuration value '{path}' must be at least {self.minimum}."
                )
            if self.maximum is not None and value > self.maximum:
                raise ConfigValidationError(
                    f"Configuration value '{path}' must be at most {self.maximum}."
                )


DEFAULT_SCHEMA: dict[str, ConfigSchemaEntry] = {
    "app.name": ConfigSchemaEntry(str, allow_empty=False),
    "app.environment": ConfigSchemaEntry(str, allow_empty=False),
    "app.log_level": ConfigSchemaEntry(
        str,
        choices=frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}),
    ),
    "paths.data_dir": ConfigSchemaEntry(str, allow_empty=False),
    "paths.models_dir": ConfigSchemaEntry(str, allow_empty=False),
    "paths.plugins_dir": ConfigSchemaEntry(str, allow_empty=False),
    "paths.exports_dir": ConfigSchemaEntry(str, allow_empty=False),
    "ui.theme": ConfigSchemaEntry(
        str,
        choices=frozenset({"system", "light", "dark"}),
    ),
    "ui.language": ConfigSchemaEntry(str, allow_empty=False),
    "ui.remember_window_state": ConfigSchemaEntry(bool),
    "audio.output_format": ConfigSchemaEntry(
        str,
        choices=frozenset({"wav"}),
    ),
    "audio.sample_rate": ConfigSchemaEntry(int, minimum=8000, maximum=192000),
    "audio.volume": ConfigSchemaEntry((int, float), minimum=0.0, maximum=1.0),
    "tts.engine": ConfigSchemaEntry(str, allow_empty=False),
    "tts.default_voice": ConfigSchemaEntry(str),
    "tts.speaking_rate": ConfigSchemaEntry((int, float), minimum=0.5, maximum=2.0),
    "translation.engine": ConfigSchemaEntry(str, allow_empty=False),
    "translation.default_source_language": ConfigSchemaEntry(str, allow_empty=False),
    "translation.default_target_language": ConfigSchemaEntry(str, allow_empty=False),
    "language_detection.engine": ConfigSchemaEntry(str, allow_empty=False),
    "language_detection.minimum_confidence": ConfigSchemaEntry(
        (int, float),
        minimum=0.0,
        maximum=1.0,
    ),
    "plugins.enabled": ConfigSchemaEntry(bool),
    "plugins.directories": ConfigSchemaEntry(list),
    "history.enabled": ConfigSchemaEntry(bool),
    "history.max_items": ConfigSchemaEntry(int, minimum=0),
    "database.url": ConfigSchemaEntry(str, allow_empty=False),
}


class ConfigManager:
    """Single entry point for reading and writing VoxAI Studio configuration."""

    def __init__(
        self,
        paths: AppPaths | None = None,
        *,
        default_config_path: PathLike | None = None,
        user_config_path: PathLike | None = None,
        schema: Mapping[str, ConfigSchemaEntry] | None = None,
    ) -> None:
        """Create a configuration manager.

        Args:
            paths: Optional path bundle used by the application.
            default_config_path: Optional project default TOML path override.
            user_config_path: Optional user TOML path override.
            schema: Optional validation schema override or extension point.
        """

        app_paths = paths or build_app_paths()
        self.default_config_path = Path(default_config_path or app_paths.default_config_file)
        self.user_config_path = Path(user_config_path or app_paths.user_config_file)
        self._schema: dict[str, ConfigSchemaEntry] = dict(schema or DEFAULT_SCHEMA)
        self._lock = RLock()
        self._defaults: dict[str, ConfigValue] = copy.deepcopy(BUILTIN_DEFAULT_CONFIG)
        self._user_overrides: dict[str, ConfigValue] = {}
        self._config: dict[str, ConfigValue] = copy.deepcopy(BUILTIN_DEFAULT_CONFIG)
        self._validation_issues: list[ConfigValidationIssue] = []

    @property
    def validation_issues(self) -> tuple[ConfigValidationIssue, ...]:
        """Return validation issues from the most recent load."""

        with self._lock:
            return tuple(self._validation_issues)

    def load(self) -> None:
        """Load defaults and user overrides from TOML files.

        Missing or invalid files are logged and ignored. Invalid known values are
        replaced with their default values while valid settings remain available.
        """

        with self._lock:
            file_defaults = self._read_toml_file(self.default_config_path, required=True)
            defaults = _deep_merge(BUILTIN_DEFAULT_CONFIG, file_defaults)
            defaults, default_issues = self._sanitize_known_values(
                defaults,
                BUILTIN_DEFAULT_CONFIG,
            )

            user_overrides = self._read_toml_file(self.user_config_path, required=False)
            merged = _deep_merge(defaults, user_overrides)
            effective_config, user_issues = self._sanitize_known_values(merged, defaults)
            for issue in user_issues:
                _delete_by_path(user_overrides, issue.path)

            self._defaults = defaults
            self._user_overrides = user_overrides
            self._config = effective_config
            self._validation_issues = [*default_issues, *user_issues]

            if self._validation_issues:
                logger.warning(
                    "Configuration loaded with %s validation issue(s).",
                    len(self._validation_issues),
                )
            else:
                logger.info("Configuration loaded successfully.")

    def reload(self) -> None:
        """Reload configuration from disk."""

        self.load()

    def get(
        self,
        path: str,
        default: ConfigValue | None = None,
        *,
        expected_type: type | tuple[type, ...] | None = None,
    ) -> ConfigValue | None:
        """Return a configuration value by dotted path.

        Args:
            path: Dotted path such as ``"ui.theme"``.
            default: Value returned when the path is missing.
            expected_type: Optional runtime type check for caller convenience.
        """

        with self._lock:
            value = _get_by_path(self._config, path, default)
            if expected_type is not None and value is not None:
                if not _matches_expected_type(value, expected_type):
                    raise ConfigValidationError(
                        f"Configuration value '{path}' is not the expected type."
                    )
            return copy.deepcopy(value)

    def get_section(self, path: str) -> dict[str, ConfigValue]:
        """Return a copy of a configuration section by dotted path."""

        with self._lock:
            value = _get_by_path(self._config, path)
            if not isinstance(value, dict):
                raise ConfigError(f"Configuration section '{path}' does not exist.")
            return copy.deepcopy(value)

    def as_dict(self) -> dict[str, ConfigValue]:
        """Return a deep copy of the effective configuration."""

        with self._lock:
            return copy.deepcopy(self._config)

    def set(self, path: str, value: ConfigValue, *, persist: bool = True) -> None:
        """Set a user-level configuration override.

        Programmatic writes are strict: invalid values raise
        :class:`ConfigValidationError` instead of being silently ignored.
        """

        with self._lock:
            candidate_overrides = copy.deepcopy(self._user_overrides)
            _set_by_path(candidate_overrides, path, value)
            candidate_config = _deep_merge(self._defaults, candidate_overrides)
            self._validate_known_values(candidate_config)

            self._user_overrides = candidate_overrides
            self._config = candidate_config

            if persist:
                self.save_user_config()

    def update(self, values: ConfigMapping, *, persist: bool = True) -> None:
        """Merge multiple user-level configuration overrides."""

        with self._lock:
            candidate_overrides = _deep_merge(self._user_overrides, values)
            candidate_config = _deep_merge(self._defaults, candidate_overrides)
            self._validate_known_values(candidate_config)

            self._user_overrides = candidate_overrides
            self._config = candidate_config

            if persist:
                self.save_user_config()

    def register_schema(self, path: str, entry: ConfigSchemaEntry) -> None:
        """Register or replace validation rules for a configuration path."""

        with self._lock:
            self._schema[path] = entry
            self._validate_known_values(self._config)

    def save_user_config(self) -> None:
        """Persist user overrides to the user configuration TOML file."""

        with self._lock:
            self.user_config_path.parent.mkdir(parents=True, exist_ok=True)
            toml_text = dumps_toml(self._user_overrides)

            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.user_config_path.parent,
                delete=False,
            ) as temp_file:
                temp_file.write(toml_text)
                temp_path = Path(temp_file.name)

            temp_path.replace(self.user_config_path)
            logger.info("User configuration saved to %s.", self.user_config_path)

    def reset_user_config(self, *, persist: bool = True) -> None:
        """Clear all user-level overrides."""

        with self._lock:
            self._user_overrides = {}
            self._config = copy.deepcopy(self._defaults)
            if persist:
                self.save_user_config()

    def _read_toml_file(self, path: Path, *, required: bool) -> dict[str, ConfigValue]:
        if not path.exists():
            message = "Default configuration file missing" if required else "User configuration file missing"
            logger.warning("%s: %s.", message, path)
            return {}

        if tomllib is None:
            logger.error("TOML support is unavailable in this Python runtime.")
            return {}

        try:
            with path.open("rb") as config_file:
                data = tomllib.load(config_file)
        except tomllib.TOMLDecodeError as exc:
            logger.warning("Invalid TOML in %s: %s. Falling back to defaults.", path, exc)
            return {}
        except OSError as exc:
            logger.warning("Could not read configuration file %s: %s.", path, exc)
            return {}

        if not isinstance(data, dict):
            logger.warning("Configuration file %s did not contain a TOML table.", path)
            return {}

        return copy.deepcopy(data)

    def _sanitize_known_values(
        self,
        config: Mapping[str, ConfigValue],
        fallback: Mapping[str, ConfigValue],
    ) -> tuple[dict[str, ConfigValue], list[ConfigValidationIssue]]:
        sanitized = copy.deepcopy(dict(config))
        issues: list[ConfigValidationIssue] = []

        for path, entry in self._schema.items():
            sentinel = object()
            value = _get_by_path(sanitized, path, sentinel)
            if value is sentinel:
                fallback_value = _get_by_path(fallback, path, None)
                if fallback_value is not None:
                    _set_by_path(sanitized, path, fallback_value)
                continue

            try:
                entry.validate(path, value)  # type: ignore[arg-type]
            except ConfigValidationError as exc:
                fallback_value = _get_by_path(fallback, path, None)
                if fallback_value is not None:
                    _set_by_path(sanitized, path, fallback_value)
                issues.append(
                    ConfigValidationIssue(
                        path=path,
                        message=str(exc),
                        fallback_value=copy.deepcopy(fallback_value),
                    )
                )
                logger.warning("%s Falling back to default value.", exc)

        return sanitized, issues

    def _validate_known_values(self, config: Mapping[str, ConfigValue]) -> None:
        for path, entry in self._schema.items():
            sentinel = object()
            value = _get_by_path(config, path, sentinel)
            if value is sentinel:
                continue
            entry.validate(path, value)  # type: ignore[arg-type]


def dumps_toml(config: Mapping[str, ConfigValue]) -> str:
    """Serialize a simple configuration mapping to TOML."""

    lines: list[str] = []
    scalar_items: dict[str, ConfigValue] = {}
    table_items: dict[str, Mapping[str, ConfigValue]] = {}

    for key, value in config.items():
        if isinstance(value, Mapping):
            table_items[key] = value
        else:
            scalar_items[key] = value

    for key, value in scalar_items.items():
        lines.append(f"{key} = {_format_toml_value(value)}")

    for table_name, table in table_items.items():
        if lines:
            lines.append("")
        _append_toml_table(lines, table_name, table)

    return "\n".join(lines).rstrip() + "\n"


def _append_toml_table(
    lines: list[str],
    table_name: str,
    table: Mapping[str, ConfigValue],
) -> None:
    lines.append(f"[{table_name}]")

    nested_tables: dict[str, Mapping[str, ConfigValue]] = {}
    for key, value in table.items():
        if isinstance(value, Mapping):
            nested_tables[f"{table_name}.{key}"] = value
        else:
            lines.append(f"{key} = {_format_toml_value(value)}")

    for nested_name, nested_table in nested_tables.items():
        lines.append("")
        _append_toml_table(lines, nested_name, nested_table)


def _format_toml_value(value: ConfigValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_format_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        entries = ", ".join(f"{key} = {_format_toml_value(item)}" for key, item in value.items())
        return "{ " + entries + " }"
    raise ConfigError(f"Unsupported TOML value type: {type(value).__name__}.")


def _deep_merge(
    base: Mapping[str, ConfigValue],
    override: Mapping[str, ConfigValue],
) -> dict[str, ConfigValue]:
    merged: dict[str, ConfigValue] = copy.deepcopy(dict(base))

    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = copy.deepcopy(value)

    return merged


def _get_by_path(
    config: Mapping[str, ConfigValue],
    path: str,
    default: Any = None,
) -> Any:
    current: Any = config
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _set_by_path(config: MutableConfigMapping, path: str, value: ConfigValue) -> None:
    current: MutableConfigMapping = config
    parts = path.split(".")
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = copy.deepcopy(value)


def _delete_by_path(config: MutableConfigMapping, path: str) -> None:
    current: ConfigValue | MutableConfigMapping = config
    parts = path.split(".")
    for part in parts[:-1]:
        if not isinstance(current, dict):
            return
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            return
        current = next_value

    if isinstance(current, dict):
        current.pop(parts[-1], None)


def _matches_expected_type(value: ConfigValue, expected_type: type | tuple[type, ...]) -> bool:
    if expected_type is bool or (
        isinstance(expected_type, tuple) and bool in expected_type
    ):
        return isinstance(value, expected_type)

    if isinstance(value, bool) and _contains_numeric_type(expected_type):
        return False

    return isinstance(value, expected_type)


def _contains_numeric_type(expected_type: type | tuple[type, ...]) -> bool:
    if isinstance(expected_type, tuple):
        return int in expected_type or float in expected_type
    return expected_type in {int, float}


def _format_expected_type(expected_type: type | tuple[type, ...]) -> str:
    if isinstance(expected_type, tuple):
        return " or ".join(item.__name__ for item in expected_type)
    return expected_type.__name__
