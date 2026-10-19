"""Core logging implementation.

Provides Logger class and factory for creating loggers with
enterprise features.
"""

import logging
import sys
from pathlib import Path
from typing import Any

from .context import log_context
from .filters import ContextFilter, SensitiveDataFilter
from .formatters import JSONFormatter, StructuredFormatter
from .handlers import RotatingFileHandlerWithCompression


class Logger:
    """Enterprise logger wrapper with structured logging support.

    Provides additional functionality over standard logging:
    - Structured logging with extra fields
    - Context management
    - Lazy evaluation
    - Integration with error system
    """

    def __init__(self, logger: logging.Logger) -> None:
        """Initialize logger wrapper.

        Args:
            logger: Underlying Python logger
        """
        self._logger = logger

    @property
    def name(self) -> str:
        """Get logger name."""
        return self._logger.name

    @property
    def level(self) -> int:
        """Get logger level."""
        return self._logger.level

    def debug(
        self,
        message: str,
        *args: Any,
        extra: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Log debug message."""
        self._log(logging.DEBUG, message, args, extra, **kwargs)

    def info(
        self,
        message: str,
        *args: Any,
        extra: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Log info message."""
        self._log(logging.INFO, message, args, extra, **kwargs)

    def warning(
        self,
        message: str,
        *args: Any,
        extra: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Log warning message."""
        self._log(logging.WARNING, message, args, extra, **kwargs)

    def error(
        self,
        message: str,
        *args: Any,
        extra: dict[str, Any] | None = None,
        exc_info: bool = False,
        **kwargs: Any,
    ) -> None:
        """Log error message."""
        self._log(logging.ERROR, message, args, extra, exc_info=exc_info, **kwargs)

    def critical(
        self,
        message: str,
        *args: Any,
        extra: dict[str, Any] | None = None,
        exc_info: bool = False,
        **kwargs: Any,
    ) -> None:
        """Log critical message."""
        self._log(logging.CRITICAL, message, args, extra, exc_info=exc_info, **kwargs)

    def exception(
        self,
        message: str,
        *args: Any,
        extra: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Log exception with traceback."""
        self._log(logging.ERROR, message, args, extra, exc_info=True, **kwargs)

    def _log(
        self,
        level: int,
        message: str,
        args: tuple[Any, ...],
        extra: dict[str, Any] | None,
        **kwargs: Any,
    ) -> None:
        """Internal logging method with context support.

        Args:
            level: Log level
            message: Log message
            args: Message arguments
            extra: Extra fields
            **kwargs: Additional arguments
        """
        if not self._logger.isEnabledFor(level):
            return

        # Merge context with extra fields
        context_data = log_context.get() or {}
        extra_data = extra or {}
        merged_extra = {**context_data, **extra_data}  # type: ignore[dict-item]

        self._logger.log(level, message, *args, extra=merged_extra, **kwargs)

    def set_level(self, level: int | str) -> None:
        """Set logger level.

        Args:
            level: Log level (int or string)
        """
        if isinstance(level, str):
            level = getattr(logging, level.upper())
        self._logger.setLevel(level)

    def add_handler(self, handler: logging.Handler) -> None:
        """Add handler to logger."""
        self._logger.addHandler(handler)

    def remove_handler(self, handler: logging.Handler) -> None:
        """Remove handler from logger."""
        self._logger.removeHandler(handler)

    def set_context(self, **kwargs: Any) -> None:
        """Set logging context.

        Context is included in all log messages.

        Args:
            **kwargs: Context key-value pairs
        """
        current = log_context.get()
        updated = {**current, **kwargs}  # type: ignore[dict-item]
        log_context.set(updated)

    def clear_context(self) -> None:
        """Clear logging context."""
        log_context.set({})


class LoggerFactory:
    """Factory for creating configured loggers.

    Supports YAML-based configuration.
    """

    @staticmethod
    def create(
        name: str,
        level: str = "INFO",
        handlers: list[Any] | None = None,
        filters: list[Any] | None = None,
    ) -> Logger:
        """Create configured logger.

        Args:
            name: Logger name
            level: Log level
            handlers: List of handlers
            filters: List of filters

        Returns:
            Configured logger
        """
        logger = logging.getLogger(name)
        logger.setLevel(getattr(logging, level.upper()))
        logger.handlers.clear()  # Clear existing handlers

        # Add handlers
        if handlers:
            for handler in handlers:
                logger.addHandler(handler)
        else:
            # Default: console handler
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(StructuredFormatter())
            logger.addHandler(handler)

        # Add filters
        if filters:
            for filter_obj in filters:
                logger.addFilter(filter_obj)

        return Logger(logger)

    @staticmethod
    def from_yaml(path: str | Path) -> Logger:
        """Create logger from YAML configuration.

        Args:
            path: Path to YAML config file

        Returns:
            Configured logger
        """
        from ..config import ConfigManager

        config = ConfigManager.from_yaml(path)
        return LoggerFactory.from_config(config)

    @staticmethod
    def from_config(config: Any) -> Logger:
        """Create logger from configuration.

        Args:
            config: Configuration object

        Returns:
            Configured logger
        """
        name = config.get("name", "root")
        level = config.get("level", "INFO")

        # Build handlers
        handlers = []
        for handler_config in config.get("handlers", []):
            handler = LoggerFactory._create_handler(handler_config)
            if handler:
                handlers.append(handler)

        # Build filters
        filters = []
        for filter_config in config.get("filters", []):
            filter_obj = LoggerFactory._create_filter(filter_config)
            if filter_obj:
                filters.append(filter_obj)

        return LoggerFactory.create(name, level, handlers, filters)

    @staticmethod
    def _create_handler(config: dict[str, Any]) -> logging.Handler | None:
        """Create handler from configuration."""
        handler_type = config.get("type", "console")
        level = config.get("level", "INFO")
        formatter_type = config.get("formatter", "structured")

        # Create handler
        handler: logging.Handler | None = None

        if handler_type == "console":
            stream = sys.stdout if config.get("stream") == "stdout" else sys.stderr
            handler = logging.StreamHandler(stream)

        elif handler_type == "file":
            filename = config.get("filename", "app.log")
            handler = logging.FileHandler(filename)

        elif handler_type == "rotating_file":
            filename = config.get("filename", "app.log")
            max_bytes = config.get("max_bytes", 10 * 1024 * 1024)  # 10MB
            backup_count = config.get("backup_count", 5)
            compress = config.get("compress", True)

            handler = RotatingFileHandlerWithCompression(
                filename=filename,
                maxBytes=max_bytes,
                backupCount=backup_count,
                compress=compress,
            )

        if handler is None:
            return None

        # Set level
        handler.setLevel(getattr(logging, level.upper()))

        # Set formatter
        if formatter_type == "json":
            formatter = JSONFormatter()
        else:
            formatter = StructuredFormatter()  # type: ignore[assignment]

        handler.setFormatter(formatter)

        return handler

    @staticmethod
    def _create_filter(config: dict[str, Any]) -> logging.Filter | None:
        """Create filter from configuration."""
        filter_type = config.get("type")

        if filter_type == "sensitive_data":
            patterns = config.get("patterns", [])
            return SensitiveDataFilter(patterns)

        elif filter_type == "context":
            return ContextFilter()

        return None


def get_logger(name: str) -> Logger:
    """Get logger by name.

    Convenience function for getting loggers.

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    return Logger(logging.getLogger(name))
