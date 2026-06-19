"""Filesystem path helpers for VoxAI Studio."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_DIRECTORY_NAME = "VoxAI Studio"


@dataclass(frozen=True)
class AppPaths:
    """Resolved paths used by application infrastructure."""

    project_root: Path
    default_config_file: Path
    user_config_file: Path
    user_data_dir: Path
    user_config_dir: Path


def find_project_root(start: Path | None = None) -> Path:
    """Return the project root by walking upward from *start*.

    The function looks for the repository-level ``config`` and ``src``
    directories. If they cannot be found, it falls back to the current working
    directory so packaged builds can still provide explicit paths.
    """

    current = (start or Path(__file__)).resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if (candidate / "config").is_dir() and (candidate / "src").is_dir():
            return candidate

    return Path.cwd().resolve()


def get_user_config_dir(app_name: str = APP_DIRECTORY_NAME) -> Path:
    """Return the platform-appropriate user configuration directory."""

    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / app_name

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name

    return Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config") / app_name


def get_user_data_dir(app_name: str = APP_DIRECTORY_NAME) -> Path:
    """Return the platform-appropriate user data directory."""

    if sys.platform == "win32":
        base = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / app_name

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name

    return Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share") / app_name


def build_app_paths(project_root: Path | None = None) -> AppPaths:
    """Build the default path bundle for VoxAI Studio."""

    root = (project_root or find_project_root()).resolve()
    user_config_dir = get_user_config_dir()
    user_data_dir = get_user_data_dir()

    return AppPaths(
        project_root=root,
        default_config_file=root / "config" / "default.toml",
        user_config_file=user_config_dir / "config.toml",
        user_data_dir=user_data_dir,
        user_config_dir=user_config_dir,
    )
