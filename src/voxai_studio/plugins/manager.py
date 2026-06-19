"""High-level plugin manager for VoxAI Studio."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from threading import RLock
from types import ModuleType

from voxai_studio.core.config import ConfigManager
from voxai_studio.core.logging import LoggerManager
from voxai_studio.core.paths import AppPaths, build_app_paths
from voxai_studio.plugins.base import BasePlugin, PluginContext, PluginMetadata
from voxai_studio.plugins.discovery import PluginDescriptor, PluginDiscovery
from voxai_studio.plugins.exceptions import PluginLoadError
from voxai_studio.plugins.registry import PluginRecord, PluginRegistry, PluginState

EXTERNAL_PLUGIN_NAMESPACE = "voxai_studio_external_plugins"


class PluginManager:
    """Discover, load, unload, enable, and disable plugins."""

    def __init__(
        self,
        config_manager: ConfigManager,
        logger_manager: LoggerManager,
        *,
        discovery: PluginDiscovery | None = None,
        registry: PluginRegistry | None = None,
        paths: AppPaths | None = None,
    ) -> None:
        """Create a plugin manager."""

        self._config_manager = config_manager
        self._logger_manager = logger_manager
        self._paths = paths or build_app_paths()
        self._logger = logger_manager.get_logger(__name__)
        self._discovery = discovery or PluginDiscovery(
            config_manager,
            logger_manager,
            paths=self._paths,
        )
        self._registry = registry or PluginRegistry()
        self._lock = RLock()

    def discover_plugins(self) -> tuple[PluginMetadata, ...]:
        """Discover installed plugins and register their metadata."""

        with self._lock:
            try:
                descriptors = self._discovery.discover()
            except Exception as exc:
                self._logger.exception("Plugin discovery failed: %s", exc)
                return ()

            disabled_plugin_ids = self._disabled_plugin_ids()
            for descriptor in descriptors:
                self._registry.register_descriptor(
                    descriptor,
                    disabled=descriptor.metadata.id in disabled_plugin_ids,
                )

            self._logger.info("Discovered %s plugin(s).", len(descriptors))
            return self.get_installed_plugins()

    def load_plugin(self, plugin_id: str) -> bool:
        """Load and initialize a plugin by id.

        Returns ``False`` when loading fails or the plugin is disabled. Failures
        are logged and recorded without bubbling into the application.
        """

        with self._lock:
            record = self._registry.get(plugin_id)
            if record is None:
                self.discover_plugins()
                record = self._registry.get(plugin_id)
            if record is None:
                self._logger.warning("Plugin '%s' is not installed.", plugin_id)
                return False
            if record.state == PluginState.DISABLED:
                self._logger.info("Plugin '%s' is disabled and will not be loaded.", plugin_id)
                return False
            if record.instance is not None:
                return True

            try:
                module, module_name = self._import_plugin_module(record.descriptor)
                plugin = self._create_plugin_instance(record.descriptor, module)
                self._validate_loaded_plugin(record.descriptor, plugin)

                context = PluginContext(
                    plugin_id=plugin_id,
                    plugin_path=record.descriptor.plugin_path,
                    config_manager=self._config_manager,
                    logger_manager=self._logger_manager,
                )
                plugin.initialize(context)
                self._registry.mark_loaded(plugin_id, plugin, module_name)
                self._logger.info("Loaded plugin '%s'.", plugin_id)
                return True
            except Exception as exc:
                self._registry.mark_failed(plugin_id, str(exc))
                self._logger.exception("Failed to load plugin '%s': %s", plugin_id, exc)
                return False

    def load_all_plugins(self) -> tuple[PluginMetadata, ...]:
        """Load every discovered plugin that is not disabled."""

        with self._lock:
            if not self._registry.all():
                self.discover_plugins()

            loaded: list[PluginMetadata] = []
            for record in self._registry.all():
                if record.state == PluginState.DISABLED:
                    continue
                if self.load_plugin(record.metadata.id):
                    loaded.append(record.metadata)
            return tuple(loaded)

    def unload_plugin(self, plugin_id: str) -> bool:
        """Unload a plugin by id."""

        with self._lock:
            record = self._registry.get(plugin_id)
            if record is None:
                self._logger.warning("Plugin '%s' is not installed.", plugin_id)
                return False
            if record.instance is None:
                self._registry.mark_unloaded(plugin_id)
                return True

            try:
                record.instance.shutdown()
            except Exception as exc:
                self._registry.mark_failed(plugin_id, str(exc))
                self._logger.exception("Failed to unload plugin '%s': %s", plugin_id, exc)
                return False

            module_name = record.module_name
            self._registry.mark_unloaded(plugin_id)
            if module_name:
                self._remove_imported_modules(module_name)
            self._logger.info("Unloaded plugin '%s'.", plugin_id)
            return True

    def enable_plugin(self, plugin_id: str) -> bool:
        """Enable a plugin and run its enable hook if it is loaded."""

        with self._lock:
            record = self._registry.get(plugin_id)
            if record is None:
                self.discover_plugins()
                record = self._registry.get(plugin_id)
            if record is None:
                self._logger.warning("Plugin '%s' is not installed.", plugin_id)
                return False

            self._set_plugin_disabled(plugin_id, disabled=False)
            if record.state == PluginState.DISABLED:
                record.state = PluginState.DISCOVERED

            if record.instance is None and not self.load_plugin(plugin_id):
                return False

            record = self._registry.get(plugin_id)
            if record is None or record.instance is None:
                return False

            try:
                record.instance.on_enable()
            except Exception as exc:
                self._registry.mark_failed(plugin_id, str(exc))
                self._logger.exception("Failed to enable plugin '%s': %s", plugin_id, exc)
                return False

            self._registry.mark_enabled(plugin_id)
            self._logger.info("Enabled plugin '%s'.", plugin_id)
            return True

    def disable_plugin(self, plugin_id: str) -> bool:
        """Disable a plugin and unload it if necessary."""

        with self._lock:
            record = self._registry.get(plugin_id)
            if record is None:
                self._logger.warning("Plugin '%s' is not installed.", plugin_id)
                return False

            if record.instance is not None:
                try:
                    record.instance.on_disable()
                except Exception as exc:
                    self._registry.mark_failed(plugin_id, str(exc))
                    self._logger.exception(
                        "Failed to disable plugin '%s': %s",
                        plugin_id,
                        exc,
                    )
                    return False

                if not self.unload_plugin(plugin_id):
                    return False

            self._set_plugin_disabled(plugin_id, disabled=True)
            self._registry.mark_disabled(plugin_id)
            self._logger.info("Disabled plugin '%s'.", plugin_id)
            return True

    def get_installed_plugins(self) -> tuple[PluginMetadata, ...]:
        """Return metadata for installed plugins."""

        return self._registry.metadata()

    def get_plugin_record(self, plugin_id: str) -> PluginRecord | None:
        """Return the registry record for a plugin id."""

        return self._registry.get(plugin_id)

    def get_plugin(self, plugin_id: str) -> BasePlugin | None:
        """Return a loaded plugin instance."""

        record = self._registry.get(plugin_id)
        return None if record is None else record.instance

    def unload_all_plugins(self) -> None:
        """Unload all loaded plugins."""

        with self._lock:
            for record in self._registry.all():
                if record.instance is not None:
                    self.unload_plugin(record.metadata.id)

    def _import_plugin_module(
        self,
        descriptor: PluginDescriptor,
    ) -> tuple[ModuleType, str]:
        module_name, _ = self._split_entry_point(descriptor.entry_point)
        module_path, is_package = self._resolve_module_path(
            descriptor.plugin_path,
            module_name,
        )
        unique_module_name = self._module_name_for_plugin(descriptor.metadata.id)

        if is_package:
            spec = importlib.util.spec_from_file_location(
                unique_module_name,
                module_path,
                submodule_search_locations=[str(module_path.parent)],
            )
        else:
            spec = importlib.util.spec_from_file_location(unique_module_name, module_path)

        if spec is None or spec.loader is None:
            raise PluginLoadError(f"Could not create import spec for {module_path}.")

        module = importlib.util.module_from_spec(spec)
        sys.modules[unique_module_name] = module

        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(unique_module_name, None)
            raise

        return module, unique_module_name

    def _module_name_for_plugin(self, plugin_id: str) -> str:
        self._ensure_external_plugin_namespace()
        safe_plugin_id = re.sub(r"[^0-9A-Za-z_]", "_", plugin_id)
        return f"{EXTERNAL_PLUGIN_NAMESPACE}.plugin_{safe_plugin_id}"

    def _ensure_external_plugin_namespace(self) -> None:
        namespace_module = sys.modules.get(EXTERNAL_PLUGIN_NAMESPACE)
        if namespace_module is None:
            namespace_module = ModuleType(EXTERNAL_PLUGIN_NAMESPACE)
            namespace_module.__path__ = []  # type: ignore[attr-defined]
            sys.modules[EXTERNAL_PLUGIN_NAMESPACE] = namespace_module

    def _remove_imported_modules(self, module_name: str) -> None:
        for loaded_module_name in list(sys.modules):
            if loaded_module_name == module_name or loaded_module_name.startswith(
                f"{module_name}."
            ):
                sys.modules.pop(loaded_module_name, None)

    def _create_plugin_instance(
        self,
        descriptor: PluginDescriptor,
        module: ModuleType,
    ) -> BasePlugin:
        _, factory_name = self._split_entry_point(descriptor.entry_point)
        factory = getattr(module, factory_name, None)
        if not callable(factory):
            raise PluginLoadError(
                f"Plugin '{descriptor.metadata.id}' entry point '{factory_name}' is not callable."
            )

        plugin = factory()
        if not isinstance(plugin, BasePlugin):
            raise PluginLoadError(
                f"Plugin '{descriptor.metadata.id}' did not return a BasePlugin instance."
            )
        return plugin

    def _validate_loaded_plugin(
        self,
        descriptor: PluginDescriptor,
        plugin: BasePlugin,
    ) -> None:
        if plugin.metadata.id != descriptor.metadata.id:
            raise PluginLoadError(
                "Loaded plugin metadata id does not match manifest id: "
                f"{plugin.metadata.id!r} != {descriptor.metadata.id!r}."
            )

    def _resolve_module_path(
        self,
        plugin_path: Path,
        module_name: str,
    ) -> tuple[Path, bool]:
        module_parts = module_name.split(".")
        if not module_parts or any(not part for part in module_parts):
            raise PluginLoadError(f"Invalid plugin module name: {module_name}.")

        module_file = plugin_path.joinpath(*module_parts).with_suffix(".py")
        if module_file.is_file():
            return module_file, False

        package_file = plugin_path.joinpath(*module_parts, "__init__.py")
        if package_file.is_file():
            return package_file, True

        raise PluginLoadError(
            f"Plugin module '{module_name}' was not found under {plugin_path}."
        )

    def _split_entry_point(self, entry_point: str) -> tuple[str, str]:
        if ":" not in entry_point:
            raise PluginLoadError(
                f"Plugin entry point '{entry_point}' must use 'module:function'."
            )

        module_name, factory_name = entry_point.split(":", 1)
        if not module_name.strip() or not factory_name.strip():
            raise PluginLoadError(
                f"Plugin entry point '{entry_point}' must use 'module:function'."
            )
        return module_name.strip(), factory_name.strip()

    def _disabled_plugin_ids(self) -> set[str]:
        value = self._config_manager.get("plugins.disabled", [], expected_type=list)
        if not isinstance(value, list):
            return set()
        return {item for item in value if isinstance(item, str)}

    def _set_plugin_disabled(self, plugin_id: str, *, disabled: bool) -> None:
        disabled_ids = self._disabled_plugin_ids()
        if disabled:
            disabled_ids.add(plugin_id)
        else:
            disabled_ids.discard(plugin_id)

        self._config_manager.set(
            "plugins.disabled",
            sorted(disabled_ids),
            persist=True,
        )
