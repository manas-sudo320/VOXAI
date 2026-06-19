"""In-memory plugin registry."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import RLock

from voxai_studio.plugins.base import BasePlugin, PluginMetadata
from voxai_studio.plugins.discovery import PluginDescriptor


class PluginState(str, Enum):
    """Lifecycle state tracked for discovered plugins."""

    DISCOVERED = "discovered"
    LOADED = "loaded"
    ENABLED = "enabled"
    DISABLED = "disabled"
    FAILED = "failed"


@dataclass
class PluginRecord:
    """Registry entry for one plugin."""

    descriptor: PluginDescriptor
    state: PluginState = PluginState.DISCOVERED
    instance: BasePlugin | None = None
    module_name: str | None = None
    error: str | None = None

    @property
    def metadata(self) -> PluginMetadata:
        """Return the plugin metadata."""

        return self.descriptor.metadata


class PluginRegistry:
    """Thread-safe in-memory registry for plugin records."""

    def __init__(self) -> None:
        """Create an empty plugin registry."""

        self._records: dict[str, PluginRecord] = {}
        self._lock = RLock()

    def register_descriptor(
        self,
        descriptor: PluginDescriptor,
        *,
        disabled: bool = False,
    ) -> PluginRecord:
        """Register a discovered plugin descriptor."""

        with self._lock:
            existing = self._records.get(descriptor.metadata.id)
            state = PluginState.DISABLED if disabled else PluginState.DISCOVERED

            if existing is not None:
                existing.descriptor = descriptor
                if existing.instance is None:
                    existing.state = state
                existing.error = None
                return existing

            record = PluginRecord(descriptor=descriptor, state=state)
            self._records[descriptor.metadata.id] = record
            return record

    def get(self, plugin_id: str) -> PluginRecord | None:
        """Return a plugin record by id."""

        with self._lock:
            return self._records.get(plugin_id)

    def all(self) -> tuple[PluginRecord, ...]:
        """Return all plugin records."""

        with self._lock:
            return tuple(self._records.values())

    def metadata(self) -> tuple[PluginMetadata, ...]:
        """Return metadata for all registered plugins."""

        with self._lock:
            return tuple(record.metadata for record in self._records.values())

    def mark_loaded(
        self,
        plugin_id: str,
        instance: BasePlugin,
        module_name: str,
    ) -> None:
        """Mark a plugin as loaded."""

        with self._lock:
            record = self._require(plugin_id)
            record.instance = instance
            record.module_name = module_name
            record.state = PluginState.LOADED
            record.error = None

    def mark_enabled(self, plugin_id: str) -> None:
        """Mark a plugin as enabled."""

        with self._lock:
            self._require(plugin_id).state = PluginState.ENABLED

    def mark_disabled(self, plugin_id: str) -> None:
        """Mark a plugin as disabled."""

        with self._lock:
            record = self._require(plugin_id)
            record.state = PluginState.DISABLED
            record.instance = None
            record.module_name = None

    def mark_unloaded(self, plugin_id: str) -> None:
        """Mark a plugin as unloaded."""

        with self._lock:
            record = self._require(plugin_id)
            record.instance = None
            record.module_name = None
            record.state = PluginState.DISCOVERED
            record.error = None

    def mark_failed(self, plugin_id: str, error: str) -> None:
        """Mark a plugin as failed."""

        with self._lock:
            record = self._require(plugin_id)
            record.instance = None
            record.module_name = None
            record.state = PluginState.FAILED
            record.error = error

    def _require(self, plugin_id: str) -> PluginRecord:
        record = self._records.get(plugin_id)
        if record is None:
            raise KeyError(f"Unknown plugin id: {plugin_id}")
        return record
