import logging
from pathlib import Path

from voxai_studio.core.config import ConfigManager
from voxai_studio.core.logging import LoggerManager
from voxai_studio.core.paths import AppPaths


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_test_paths(root: Path) -> AppPaths:
    return AppPaths(
        project_root=root,
        default_config_file=root / "default.toml",
        user_config_file=root / "user.toml",
        user_data_dir=root / "user-data",
        user_config_dir=root / "user-config",
    )


def test_logger_manager_writes_to_rotating_file(tmp_path: Path) -> None:
    paths = build_test_paths(tmp_path)
    write_text(
        paths.default_config_file,
        """
[logging]
level = "DEBUG"
directory = "logs"
file_name = "test.log"
format = "%(levelname)s:%(name)s:%(message)s"
date_format = "%Y-%m-%d"
console_enabled = false
file_enabled = true
max_bytes = 1024
backup_count = 1
""",
    )

    config_manager = ConfigManager(
        default_config_path=paths.default_config_file,
        user_config_path=paths.user_config_file,
    )
    config_manager.load()

    logger_manager = LoggerManager(
        config_manager,
        paths=paths,
        namespace="voxai_studio_test",
    )
    logger = logger_manager.get_logger("example")
    logger.debug("hello")
    logger_manager.shutdown()

    log_file = paths.user_data_dir / "logs" / "test.log"
    assert log_file.exists()
    assert "DEBUG:voxai_studio_test.example:hello" in log_file.read_text(
        encoding="utf-8"
    )


def test_child_loggers_propagate_to_managed_namespace(tmp_path: Path) -> None:
    paths = build_test_paths(tmp_path)
    write_text(
        paths.default_config_file,
        """
[logging]
level = "INFO"
directory = "logs"
file_name = "test.log"
format = "%(levelname)s:%(message)s"
date_format = "%Y-%m-%d"
console_enabled = false
file_enabled = true
max_bytes = 1024
backup_count = 1
""",
    )

    config_manager = ConfigManager(
        default_config_path=paths.default_config_file,
        user_config_path=paths.user_config_file,
    )
    config_manager.load()

    logger_manager = LoggerManager(
        config_manager,
        paths=paths,
        namespace="voxai_studio_test_child",
    )
    child_logger = logger_manager.get_logger("services.tts")

    assert child_logger.name == "voxai_studio_test_child.services.tts"
    assert child_logger.level == logging.NOTSET
    assert child_logger.propagate is True

    logger_manager.shutdown()
