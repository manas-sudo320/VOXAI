"""Plugin framework for VoxAI Studio."""

from voxai_studio.plugins.base import (
    AudioExporterPlugin,
    BasePlugin,
    DocumentReaderPlugin,
    OCRPlugin,
    PluginCategory,
    PluginContext,
    PluginMetadata,
    TextToSpeechPlugin,
    ThemePlugin,
    TranslationPlugin,
)
from voxai_studio.plugins.discovery import PluginDescriptor, PluginDiscovery
from voxai_studio.plugins.manager import PluginManager
from voxai_studio.plugins.registry import PluginRecord, PluginRegistry, PluginState

__all__ = [
    "AudioExporterPlugin",
    "BasePlugin",
    "DocumentReaderPlugin",
    "OCRPlugin",
    "PluginCategory",
    "PluginContext",
    "PluginDescriptor",
    "PluginDiscovery",
    "PluginManager",
    "PluginMetadata",
    "PluginRecord",
    "PluginRegistry",
    "PluginState",
    "TextToSpeechPlugin",
    "ThemePlugin",
    "TranslationPlugin",
]
