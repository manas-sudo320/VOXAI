"""Plugin discovery from configured plugin directories."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - kept for older interpreters.
    tomllib = None  # type: ignore[assignment]

from voxai_studio.core.config import ConfigManager
from voxai_studio.core.logging import LoggerManager
from voxai_studio.core.paths import AppPaths, build_app_paths
from voxai_studio.plugins.base import PluginCategory, PluginMetadata
from voxai_studio.plugins.exceptions import PluginManifestError

PLUGIN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class PluginDescriptor:
    """A discovered plugin manifest and its filesystem location."""

    metadata: PluginMetadata
    plugin_path: Path
    manifest_path: Path
    entry_point: str


class PluginDiscovery:
    """Discover plugin descriptors from configured plugin directories."""

    def __init__(
        self,
        config_manager: ConfigManager,
        logger_manager: LoggerManager,
        *,
        paths: AppPaths | None = None,
    ) -> None:
        """Create a plugin discovery service."""

        self._config_manager = config_manager
        self._logger = logger_manager.get_logger(__name__)
        self._paths = paths or build_app_paths()

    def discover(self) -> list[PluginDescriptor]:
        """Return descriptors for valid plugin manifests.

        Invalid plugin manifests are logged and skipped so discovery never
        prevents the application from starting.
        """

        if not self._plugins_enabled():
            self._logger.info("Plugin discovery skipped because plugins are disabled.")
            return []

        manifest_name = self._manifest_name()
        discovered: dict[str, PluginDescriptor] = {}

        for plugin_directory in self._plugin_directories():
            if not plugin_directory.exists():
                self._logger.debug("Plugin directory does not exist: %s", plugin_directory)
                continue
            if not plugin_directory.is_dir():
                self._logger.warning(
                    "Configured plugin path is not a directory: %s",
                    plugin_directory,
                )
                continue

            for manifest_path in sorted(plugin_directory.glob(f"*/{manifest_name}")):
                try:
                    descriptor = self._read_manifest(manifest_path)
                except PluginManifestError as exc:
                    self._logger.warning("Skipping invalid plugin manifest: %s", exc)
                    continue

                plugin_id = descriptor.metadata.id
                if plugin_id in discovered:
                    self._logger.warning(
                        "Duplicate plugin id '%s' found at %s. Keeping first plugin.",
                        plugin_id,
                        manifest_path,
                    )
                    continue

                discovered[plugin_id] = descriptor
                self._logger.debug("Discovered plugin '%s'.", plugin_id)

        return list(discovered.values())

    def _plugins_enabled(self) -> bool:
        value = self._config_manager.get("plugins.enabled", True, expected_type=bool)
        return value if isinstance(value, bool) else True

    def _manifest_name(self) -> str:
        value = self._config_manager.get(
            "plugins.manifest_name",
            "plugin.toml",
            expected_type=str,
        )
        if isinstance(value, str) and value.strip():
            return value.strip()
        return "plugin.toml"

    def _plugin_directories(self) -> list[Path]:
        value = self._config_manager.get("plugins.directories", [], expected_type=list)
        if not isinstance(value, list):
            self._logger.warning("Plugin directories configuration is invalid.")
            return []

        directories: list[Path] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                self._logger.warning("Ignoring invalid plugin directory value: %r", item)
                continue
            directories.append(self._resolve_plugin_directory(item))

        return directories

    def _resolve_plugin_directory(self, directory: str) -> Path:
        expanded = Path(os.path.expandvars(directory)).expanduser()
        if expanded.is_absolute():
            return expanded
        return self._paths.project_root / expanded

    def _read_manifest(self, manifest_path: Path) -> PluginDescriptor:
        if tomllib is None:
            raise PluginManifestError("TOML support is unavailable.")

        try:
            with manifest_path.open("rb") as manifest_file:
                manifest = tomllib.load(manifest_file)
        except tomllib.TOMLDecodeError as exc:
            raise PluginManifestError(f"{manifest_path}: invalid TOML: {exc}") from exc
        except OSError as exc:
            raise PluginManifestError(f"{manifest_path}: could not be read: {exc}") from exc

        plugin_data = manifest.get("plugin")
        if not isinstance(plugin_data, dict):
            raise PluginManifestError(f"{manifest_path}: missing [plugin] table.")

        metadata = self._read_metadata(manifest_path, plugin_data)
        entry_point = self._required_string(manifest_path, plugin_data, "entry_point")

        return PluginDescriptor(
            metadata=metadata,
            plugin_path=manifest_path.parent,
            manifest_path=manifest_path,
            entry_point=entry_point,
        )

    def _read_metadata(
        self,
        manifest_path: Path,
        plugin_data: dict[str, Any],
    ) -> PluginMetadata:
        plugin_id = self._required_string(manifest_path, plugin_data, "id")
        if not PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise PluginManifestError(
                f"{manifest_path}: plugin id '{plugin_id}' contains unsupported characters."
            )

        return PluginMetadata(
            id=plugin_id,
            name=self._required_string(manifest_path, plugin_data, "name"),
            version=self._required_string(manifest_path, plugin_data, "version"),
            author=self._required_string(manifest_path, plugin_data, "author"),
            description=self._required_string(manifest_path, plugin_data, "description"),
            supported_application_version=self._required_string(
                manifest_path,
                plugin_data,
                "supported_application_version",
            ),
            categories=self._read_categories(manifest_path, plugin_data),
        )

    def _read_categories(
        self,
        manifest_path: Path,
        plugin_data: dict[str, Any],
    ) -> tuple[PluginCategory, ...]:
        raw_categories = plugin_data.get("categories", [])
        if not isinstance(raw_categories, list):
            raise PluginManifestError(f"{manifest_path}: categories must be a list.")

        categories: list[PluginCategory] = []
        for raw_category in raw_categories:
            if not isinstance(raw_category, str):
                raise PluginManifestError(
                    f"{manifest_path}: category values must be strings."
                )
            try:
                categories.append(PluginCategory(raw_category))
            except ValueError as exc:
                raise PluginManifestError(
                    f"{manifest_path}: unsupported plugin category '{raw_category}'."
                ) from exc

        return tuple(categories)

    def _required_string(
        self,
        manifest_path: Path,
        plugin_data: dict[str, Any],
        key: str,
    ) -> str:
        value = plugin_data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise PluginManifestError(
                f"{manifest_path}: plugin field '{key}' is required."
            )
        return value.strip()
