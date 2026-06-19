"""Base contracts for VoxAI Studio plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from voxai_studio.core.config import ConfigManager
    from voxai_studio.core.logging import LoggerManager


class PluginCategory(str, Enum):
    """Supported plugin categories.

    The framework defines category contracts now, while concrete engines and
    readers can be implemented later without changing the plugin manager.
    """

    TEXT_TO_SPEECH = "tts"
    TRANSLATION = "translation"
    DOCUMENT_READER = "document_reader"
    AUDIO_EXPORTER = "audio_exporter"
    OCR = "ocr"
    THEME = "theme"


@dataclass(frozen=True)
class PluginMetadata:
    """Metadata every plugin must expose."""

    id: str
    name: str
    version: str
    author: str
    description: str
    supported_application_version: str
    categories: tuple[PluginCategory, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PluginContext:
    """Runtime context passed to loaded plugins."""

    plugin_id: str
    plugin_path: Path
    config_manager: ConfigManager
    logger_manager: LoggerManager


class BasePlugin(ABC):
    """Base class for all VoxAI Studio plugins."""

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata."""

    def initialize(self, context: PluginContext) -> None:
        """Initialize the plugin after it is loaded.

        Plugins may override this hook to read configuration or prepare local
        resources. The default implementation intentionally does nothing.
        """

    def on_enable(self) -> None:
        """Run after the plugin has been enabled."""

    def on_disable(self) -> None:
        """Run before the plugin is disabled."""

    def shutdown(self) -> None:
        """Release plugin resources before unloading."""


class TextToSpeechPlugin(BasePlugin):
    """Interface for future text-to-speech plugins."""

    @abstractmethod
    def create_tts_engine(self) -> object:
        """Return a text-to-speech engine adapter."""


class TranslationPlugin(BasePlugin):
    """Interface for future translation plugins."""

    @abstractmethod
    def create_translation_engine(self) -> object:
        """Return a translation engine adapter."""


class DocumentReaderPlugin(BasePlugin):
    """Interface for future document reader plugins."""

    @abstractmethod
    def create_document_reader(self) -> object:
        """Return a document reader adapter."""


class AudioExporterPlugin(BasePlugin):
    """Interface for future audio exporter plugins."""

    @abstractmethod
    def create_audio_exporter(self) -> object:
        """Return an audio exporter adapter."""


class OCRPlugin(BasePlugin):
    """Interface for future OCR plugins."""

    @abstractmethod
    def create_ocr_engine(self) -> object:
        """Return an OCR engine adapter."""


class ThemePlugin(BasePlugin):
    """Interface for future theme plugins."""

    @abstractmethod
    def get_theme_resources(self) -> Mapping[str, Any]:
        """Return theme resource descriptors."""
