"""Decorators for automatic metrics collection.

Provides convenient decorators for instrumenting functions.
"""

from collections.abc import Callable
from functools import wraps
from typing import Any

from .manager import get_metrics


def timer(name: str, labels: dict[str, str] | None = None) -> Callable[..., Any]:  # noqa: E501
    """Decorator to time function execution.

    Args:
        name: Metric name
        labels: Metric labels

    Examples:
        >>> @timer("user.fetch.duration")
        ... def get_user(user_id):
        ...     return db.query(...)
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            metrics = get_metrics()
            with metrics.timer(name, labels):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def counter(
    name: str, value: float = 1.0, labels: dict[str, str] | None = None
) -> Callable[..., Any]:  # noqa: E501
    """Decorator to increment counter on function call.

    Args:
        name: Metric name
        value: Increment value
        labels: Metric labels

    Examples:
        >>> @counter("api.requests.total")
        ... def handle_request():
        ...     pass
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            metrics = get_metrics()
            metrics.counter(name, value, labels)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def gauge(name: str, value_func: Callable[..., Any] | None = None) -> Callable[..., Any]:
    """Decorator to set gauge value based on function result.

    Args:
        name: Metric name
        value_func: Function to extract value from result

    Examples:
        >>> @gauge("queue.size", lambda result: len(result))
        ... def get_queue():
        ...     return queue.get_all()
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = func(*args, **kwargs)
            metrics = get_metrics()

            if value_func:
                value = value_func(result)
            elif isinstance(result, (int, float)):
                value = result
            else:
                value = 1.0

            metrics.gauge(name, value)
            return result

        return wrapper

    return decorator
