# Configuration

VoxAI Studio uses layered TOML configuration.

1. Built-in defaults protect startup if files are missing or invalid.
2. `config/default.toml` stores application defaults.
3. A user-specific `config.toml` overrides the defaults.

Application modules should not read TOML files directly. They should receive or
use `ConfigManager` and ask for values by dotted path, for example
`ui.theme` or `tts.engine`.

## Responsibilities

`ConfigManager` is responsible for:

- loading default and user configuration;
- merging user overrides over defaults;
- validating known configuration values;
- falling back to defaults when files or values are invalid;
- writing user overrides;
- providing thread-safe access where practical.

## Extension

Future modules can add settings by adding default values to `config/default.toml`
and registering validation rules with `ConfigManager.register_schema()`. This
keeps the storage format and access pattern stable as themes, engines, plugins,
audio settings, and UI preferences grow.
