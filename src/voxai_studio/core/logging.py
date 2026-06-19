"""Centralized logging infrastructure for VoxAI Studio."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import RLock

from voxai_studio.core.config import ConfigManager
from voxai_studio.core.errors import ConfigError
from voxai_studio.core.paths import AppPaths, build_app_paths

LOGGER_NAMESPACE = "voxai_studio"
FALLBACK_LOG_FORMAT = "%(levelname)s:%(name)s:%(message)s"
FALLBACK_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
SUPPORTED_LOG_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


@dataclass(frozen=True)
class LoggingSettings:
    """Validated logging settings consumed by :class:`LoggerManager`."""

    level_name: str
    log_directory: Path
    file_name: str
    message_format: str
    date_format: str
    console_enabled: bool
    file_enabled: bool
    max_bytes: int
    backup_count: int

    @property
    def level(self) -> int:
        """Return the numeric Python logging level."""

        return SUPPORTED_LOG_LEVELS[self.level_name]

    @property
    def log_file_path(self) -> Path:
        """Return the full path to the active log file."""

        return self.log_directory / self.file_name


class LoggerManager:
    """Create and manage application loggers for VoxAI Studio.

    The manager owns handler setup for the application logging namespace.
    Future modules should request loggers from this class instead of calling
    ``logging.getLogger`` directly.
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        *,
        paths: AppPaths | None = None,
        namespace: str = LOGGER_NAMESPACE,
    ) -> None:
        """Create a logger manager.

        Args:
            config_manager: Loaded configuration manager used for logging
                settings.
            paths: Optional application path bundle. Relative log directories
                are resolved inside ``paths.user_data_dir``.
            namespace: Root logging namespace managed by this instance.
        """

        self._config_manager = config_manager
        self._paths = paths or build_app_paths()
        self._namespace = namespace
        self._lock = RLock()
        self._configured = False

    def configure(self) -> None:
        """Configure console and rotating-file logging handlers.

        This method is safe to call multiple times. Existing handlers managed
        by this logger are removed before new settings are applied.
        """

        with self._lock:
            settings = self._load_settings()
            app_logger = logging.getLogger(self._namespace)
            app_logger.setLevel(settings.level)
            app_logger.propagate = False
            self._remove_managed_handlers(app_logger)

            formatter = self._build_formatter(settings)

            if settings.console_enabled:
                console_handler = logging.StreamHandler()
                self._prepare_handler(console_handler, settings, formatter)
                app_logger.addHandler(console_handler)

            if settings.file_enabled:
                try:
                    settings.log_directory.mkdir(parents=True, exist_ok=True)
                    file_handler = RotatingFileHandler(
                        filename=settings.log_file_path,
                        maxBytes=settings.max_bytes,
                        backupCount=settings.backup_count,
                        encoding="utf-8",
                    )
                    self._prepare_handler(file_handler, settings, formatter)
                    app_logger.addHandler(file_handler)
                except OSError as exc:
                    app_logger.warning(
                        "File logging could not be initialized at %s: %s",
                        settings.log_file_path,
                        exc,
                    )

            if not app_logger.handlers:
                fallback_handler = logging.NullHandler()
                self._prepare_handler(fallback_handler, settings, formatter)
                app_logger.addHandler(fallback_handler)

            self._configured = True
            app_logger.debug("Logging configured.")

    def get_logger(self, name: str | None = None) -> logging.Logger:
        """Return an application logger.

        Args:
            name: Optional module or component name. Passing ``__name__`` from a
                VoxAI Studio module is supported.
        """

        with self._lock:
            if not self._configured:
                self.configure()

            logger_name = self._normalize_logger_name(name)
            logger = logging.getLogger(logger_name)
            if logger_name != self._namespace:
                logger.setLevel(logging.NOTSET)
                logger.propagate = True
            return logger

    def reconfigure(self) -> None:
        """Reload logging handlers from the current configuration values."""

        with self._lock:
            self._configured = False
            self.configure()

    def shutdown(self) -> None:
        """Close handlers managed by this logger manager."""

        with self._lock:
            app_logger = logging.getLogger(self._namespace)
            self._remove_managed_handlers(app_logger)
            self._configured = False

    def _load_settings(self) -> LoggingSettings:
        level_name = self._get_string("logging.level").upper()
        if level_name not in SUPPORTED_LOG_LEVELS:
            raise ConfigError(f"Unsupported logging level: {level_name}.")

        directory = self._resolve_log_directory(self._get_string("logging.directory"))

        return LoggingSettings(
            level_name=level_name,
            log_directory=directory,
            file_name=self._get_string("logging.file_name"),
            message_format=self._get_string("logging.format"),
            date_format=self._get_string("logging.date_format"),
            console_enabled=self._get_bool("logging.console_enabled"),
            file_enabled=self._get_bool("logging.file_enabled"),
            max_bytes=self._get_int("logging.max_bytes"),
            backup_count=self._get_int("logging.backup_count"),
        )

    def _resolve_log_directory(self, configured_directory: str) -> Path:
        expanded = Path(os.path.expandvars(configured_directory)).expanduser()
        if expanded.is_absolute():
            return expanded
        return self._paths.user_data_dir / expanded

    def _normalize_logger_name(self, name: str | None) -> str:
        if not name:
            return self._namespace

        clean_name = name.strip()
        if not clean_name:
            return self._namespace

        if clean_name == self._namespace or clean_name.startswith(f"{self._namespace}."):
            return clean_name

        return f"{self._namespace}.{clean_name}"

    def _prepare_handler(
        self,
        handler: logging.Handler,
        settings: LoggingSettings,
        formatter: logging.Formatter,
    ) -> None:
        handler.setLevel(settings.level)
        handler.setFormatter(formatter)
        setattr(handler, "_voxai_managed", True)

    def _remove_managed_handlers(self, logger: logging.Logger) -> None:
        for handler in list(logger.handlers):
            if getattr(handler, "_voxai_managed", False):
                logger.removeHandler(handler)
                handler.close()

    def _build_formatter(self, settings: LoggingSettings) -> logging.Formatter:
        try:
            return logging.Formatter(
                fmt=settings.message_format,
                datefmt=settings.date_format,
            )
        except ValueError as exc:
            fallback_logger = logging.getLogger(self._namespace)
            fallback_logger.warning(
                "Invalid logging format configured; using fallback format: %s",
                exc,
            )
            return logging.Formatter(
                fmt=FALLBACK_LOG_FORMAT,
                datefmt=FALLBACK_DATE_FORMAT,
            )

    def _get_string(self, path: str) -> str:
        value = self._config_manager.get(path, expected_type=str)
        if not isinstance(value, str):
            raise ConfigError(f"Missing string configuration value: {path}.")
        return value

    def _get_bool(self, path: str) -> bool:
        value = self._config_manager.get(path, expected_type=bool)
        if not isinstance(value, bool):
            raise ConfigError(f"Missing boolean configuration value: {path}.")
        return value

    def _get_int(self, path: str) -> int:
        value = self._config_manager.get(path, expected_type=int)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(f"Missing integer configuration value: {path}.")
        return value
