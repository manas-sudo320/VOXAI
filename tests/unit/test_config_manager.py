from pathlib import Path

import pytest

from voxai_studio.core.config import ConfigManager
from voxai_studio.core.errors import ConfigValidationError


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_loads_defaults_when_user_config_is_missing(tmp_path: Path) -> None:
    default_config = tmp_path / "default.toml"
    user_config = tmp_path / "user.toml"
    write_text(
        default_config,
        """
[ui]
theme = "dark"
language = "en"
remember_window_state = true
""",
    )

    manager = ConfigManager(
        default_config_path=default_config,
        user_config_path=user_config,
    )
    manager.load()

    assert manager.get("ui.theme") == "dark"
    assert manager.get("tts.engine") == "piper"


def test_user_config_overrides_defaults(tmp_path: Path) -> None:
    default_config = tmp_path / "default.toml"
    user_config = tmp_path / "user.toml"
    write_text(default_config, '[ui]\ntheme = "light"\n')
    write_text(user_config, '[ui]\ntheme = "dark"\n')

    manager = ConfigManager(
        default_config_path=default_config,
        user_config_path=user_config,
    )
    manager.load()

    assert manager.get("ui.theme") == "dark"


def test_invalid_user_value_falls_back_to_default(tmp_path: Path) -> None:
    default_config = tmp_path / "default.toml"
    user_config = tmp_path / "user.toml"
    write_text(default_config, '[audio]\nvolume = 0.8\n')
    write_text(user_config, '[audio]\nvolume = 3.0\n')

    manager = ConfigManager(
        default_config_path=default_config,
        user_config_path=user_config,
    )
    manager.load()

    assert manager.get("audio.volume") == 0.8
    assert len(manager.validation_issues) == 1


def test_set_validates_and_persists_user_override(tmp_path: Path) -> None:
    default_config = tmp_path / "default.toml"
    user_config = tmp_path / "user.toml"
    write_text(default_config, '[ui]\ntheme = "system"\n')

    manager = ConfigManager(
        default_config_path=default_config,
        user_config_path=user_config,
    )
    manager.load()
    manager.set("ui.theme", "dark")

    assert manager.get("ui.theme") == "dark"
    assert 'theme = "dark"' in user_config.read_text(encoding="utf-8")


def test_set_rejects_invalid_known_value(tmp_path: Path) -> None:
    default_config = tmp_path / "default.toml"
    user_config = tmp_path / "user.toml"
    write_text(default_config, '[ui]\ntheme = "system"\n')

    manager = ConfigManager(
        default_config_path=default_config,
        user_config_path=user_config,
    )
    manager.load()

    with pytest.raises(ConfigValidationError):
        manager.set("ui.theme", "neon")
