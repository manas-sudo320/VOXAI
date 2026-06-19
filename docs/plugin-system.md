# Plugin System

VoxAI Studio uses a manifest-driven plugin framework. The framework is in place
only; no built-in plugins are implemented yet.

## Manifest

Each plugin lives in its own folder inside a configured plugin directory. The
default manifest file is `plugin.toml`.

```toml
[plugin]
id = "example.plugin"
name = "Example Plugin"
version = "0.1.0"
author = "Example Author"
description = "Short description."
supported_application_version = "0.1.x"
categories = ["tts"]
entry_point = "plugin:create_plugin"
```

The entry point uses `module:function`. The factory function must return an
instance of `BasePlugin`.

## Lifecycle

`PluginManager` is responsible for:

- discovering plugin manifests;
- loading plugin modules;
- initializing plugin instances;
- enabling and disabling plugins;
- unloading plugins;
- exposing installed plugin metadata.

Plugin failures are logged and recorded. A broken plugin must not crash the
application.

## Contracts

All plugins inherit from `BasePlugin` and expose `PluginMetadata`. Category
contracts exist for future extension:

- `TextToSpeechPlugin`
- `TranslationPlugin`
- `DocumentReaderPlugin`
- `AudioExporterPlugin`
- `OCRPlugin`
- `ThemePlugin`

These are framework interfaces only. Engine, reader, OCR, exporter, and theme
implementations will be added later.

## Configuration

Plugin discovery reads the existing configuration system:

- `plugins.enabled`
- `plugins.directories`
- `plugins.manifest_name`
- `plugins.disabled`

Future modules should use `PluginManager` to query or load plugins. They should
not scan plugin folders or import plugin modules directly.
