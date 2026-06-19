from __future__ import annotations

from pathlib import Path

from voxai_studio.core.config import ConfigManager
from voxai_studio.core.logging import LoggerManager
from voxai_studio.core.paths import AppPaths
from voxai_studio.plugins import BasePlugin, PluginManager, PluginState


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_paths(root: Path) -> AppPaths:
    return AppPaths(
        project_root=root,
        default_config_file=root / "default.toml",
        user_config_file=root / "user.toml",
        user_data_dir=root / "user-data",
        user_config_dir=root / "user-config",
    )


def write_default_config(paths: AppPaths) -> None:
    write_text(
        paths.default_config_file,
        """
[logging]
level = "CRITICAL"
directory = "logs"
file_name = "test.log"
format = "%(levelname)s:%(name)s:%(message)s"
date_format = "%Y-%m-%d"
console_enabled = false
file_enabled = false
max_bytes = 1024
backup_count = 1

[plugins]
enabled = true
directories = ["plugins"]
manifest_name = "plugin.toml"
disabled = []
""",
    )


def build_managers(root: Path) -> tuple[ConfigManager, LoggerManager, PluginManager]:
    paths = build_paths(root)
    write_default_config(paths)

    config_manager = ConfigManager(
        default_config_path=paths.default_config_file,
        user_config_path=paths.user_config_file,
    )
    config_manager.load()

    logger_manager = LoggerManager(
        config_manager,
        paths=paths,
        namespace=f"voxai_test_{root.name}",
    )

    return (
        config_manager,
        logger_manager,
        PluginManager(config_manager, logger_manager, paths=paths),
    )


def create_test_plugin(root: Path, plugin_id: str = "test.plugin") -> None:
    plugin_dir = root / "plugins" / "test_plugin"
    write_text(
        plugin_dir / "plugin.toml",
        f"""
[plugin]
id = "{plugin_id}"
name = "Test Plugin"
version = "0.1.0"
author = "Tests"
description = "A test plugin."
supported_application_version = "0.1.x"
categories = ["theme"]
entry_point = "plugin:create_plugin"
""",
    )
    write_text(
        plugin_dir / "plugin.py",
        f"""
from voxai_studio.plugins import BasePlugin, PluginCategory, PluginMetadata


class TestPlugin(BasePlugin):
    def __init__(self):
        self.enabled = False
        self.shutdown_called = False

    @property
    def metadata(self):
        return PluginMetadata(
            id="{plugin_id}",
            name="Test Plugin",
            version="0.1.0",
            author="Tests",
            description="A test plugin.",
            supported_application_version="0.1.x",
            categories=(PluginCategory.THEME,),
        )

    def on_enable(self):
        self.enabled = True

    def on_disable(self):
        self.enabled = False

    def shutdown(self):
        self.shutdown_called = True


def create_plugin():
    return TestPlugin()
""",
    )


def test_discovers_plugin_metadata(tmp_path: Path) -> None:
    create_test_plugin(tmp_path)
    _, logger_manager, plugin_manager = build_managers(tmp_path)

    metadata = plugin_manager.discover_plugins()

    assert len(metadata) == 1
    assert metadata[0].id == "test.plugin"

    logger_manager.shutdown()


def test_loads_enables_disables_and_unloads_plugin(tmp_path: Path) -> None:
    create_test_plugin(tmp_path)
    config_manager, logger_manager, plugin_manager = build_managers(tmp_path)
    plugin_manager.discover_plugins()

    assert plugin_manager.load_plugin("test.plugin") is True
    plugin = plugin_manager.get_plugin("test.plugin")
    assert isinstance(plugin, BasePlugin)

    assert plugin_manager.enable_plugin("test.plugin") is True
    record = plugin_manager.get_plugin_record("test.plugin")
    assert record is not None
    assert record.state == PluginState.ENABLED
    assert getattr(plugin_manager.get_plugin("test.plugin"), "enabled") is True

    assert plugin_manager.disable_plugin("test.plugin") is True
    disabled_record = plugin_manager.get_plugin_record("test.plugin")
    assert disabled_record is not None
    assert disabled_record.state == PluginState.DISABLED
    assert "test.plugin" in config_manager.get("plugins.disabled")

    logger_manager.shutdown()


def test_load_failure_is_recorded_without_crashing(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins" / "broken_plugin"
    write_text(
        plugin_dir / "plugin.toml",
        """
[plugin]
id = "broken.plugin"
name = "Broken Plugin"
version = "0.1.0"
author = "Tests"
description = "Broken plugin."
supported_application_version = "0.1.x"
categories = []
entry_point = "missing:create_plugin"
""",
    )
    _, logger_manager, plugin_manager = build_managers(tmp_path)
    plugin_manager.discover_plugins()

    assert plugin_manager.load_plugin("broken.plugin") is False
    record = plugin_manager.get_plugin_record("broken.plugin")
    assert record is not None
    assert record.state == PluginState.FAILED
    assert record.error is not None

    logger_manager.shutdown()


def test_invalid_manifest_is_skipped(tmp_path: Path) -> None:
    write_text(
        tmp_path / "plugins" / "invalid_plugin" / "plugin.toml",
        """
[plugin]
id = "invalid.plugin"
name = "Invalid"
""",
    )
    _, logger_manager, plugin_manager = build_managers(tmp_path)

    assert plugin_manager.discover_plugins() == ()

    logger_manager.shutdown()
