"""Audit decorators."""

from collections.abc import Callable
from functools import wraps
from typing import Any

from unistax.audit.logger import AuditAction, AuditLogger

_audit_logger: AuditLogger | None = None


def set_audit_logger(logger: AuditLogger) -> None:
    """Set global audit logger."""
    global _audit_logger
    _audit_logger = logger


def audit(action: AuditAction, resource: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to audit function calls."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                result = func(*args, **kwargs)
                if _audit_logger:
                    _audit_logger.log(action=action, resource=resource, success=True)
                return result
            except Exception as e:
                if _audit_logger:
                    _audit_logger.log(action=action, resource=resource, success=False, error=str(e))
                raise

        return wrapper

    return decorator
