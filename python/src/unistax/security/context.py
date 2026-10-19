"""Security context for managing current user and authentication state.

This module provides thread-safe context management for storing the current
authenticated user and their role during request processing.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

# Thread-safe context variable for current user
_current_user: ContextVar[dict[str, Any] | None] = ContextVar("current_user", default=None)


@dataclass
class User:
    """Represents an authenticated user.

    Attributes:
        id: User identifier
        username: Username
        role: User's role (for RBAC)
        permissions: Optional set of explicit permissions
        metadata: Additional user context
    """

    id: str | int
    username: str
    role: str
    permissions: set[str] | None = None
    metadata: dict[str, Any] | None = None


def set_current_user(user: User | dict[str, Any] | None) -> None:
    """Set the current user in context.

    This should be called by authentication middleware after validating
    the user's credentials.

    Args:
        user: User object or dictionary with user data, or None to clear

    Example:
        >>> from unistax.security.context import set_current_user, User
        >>>
        >>> # In authentication middleware
        >>> user = User(id=123, username="alice", role="admin")
        >>> set_current_user(user)
        >>>
        >>> # Or with a dict
        >>> set_current_user({"id": 123, "username": "alice", "role": "admin"})
        >>>
        >>> # Clear context after request
        >>> set_current_user(None)
    """
    if user is None:
        _current_user.set(None)
    elif isinstance(user, User):
        _current_user.set(
            {
                "id": user.id,
                "username": user.username,
                "role": user.role,
                "permissions": user.permissions or set(),
                "metadata": user.metadata or {},
            }
        )
    elif isinstance(user, dict):
        _current_user.set(user)
    else:
        raise TypeError(f"Expected User or dict, got {type(user)}")


def get_current_user() -> dict[str, Any] | None:
    """Get the current user from context.

    Returns:
        Dictionary with user data, or None if no user is set

    Example:
        >>> user = get_current_user()
        >>> if user:
        ...     print(f"User: {user['username']}, Role: {user['role']}")
    """
    return _current_user.get()


def get_current_user_role() -> str | None:
    """Get the current user's role.

    Returns:
        User's role string, or None if no user is authenticated

    Example:
        >>> role = get_current_user_role()
        >>> if role == "admin":
        ...     # Allow admin access
        ...     pass
    """
    user = _current_user.get()
    return user.get("role") if user else None


def get_current_user_id() -> str | int | None:
    """Get the current user's ID.

    Returns:
        User's ID, or None if no user is authenticated
    """
    user = _current_user.get()
    return user.get("id") if user else None


def has_role(role: str) -> bool:
    """Check if current user has the specified role.

    Args:
        role: Role name to check

    Returns:
        True if user has the role, False otherwise

    Example:
        >>> if has_role("admin"):
        ...     # Allow admin-only action
        ...     pass
    """
    current_role = get_current_user_role()
    return current_role == role if current_role else False


def is_authenticated() -> bool:
    """Check if a user is currently authenticated.

    Returns:
        True if user is authenticated, False otherwise

    Example:
        >>> if not is_authenticated():
        ...     raise AuthenticationError("Login required")
    """
    return _current_user.get() is not None


def clear_current_user() -> None:
    """Clear the current user from context.

    This should be called after request processing is complete to avoid
    context leakage between requests.

    Example:
        >>> # In middleware cleanup
        >>> try:
        ...     process_request()
        ... finally:
        ...     clear_current_user()
    """
    _current_user.set(None)
