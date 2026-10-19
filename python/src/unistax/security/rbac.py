"""Role-Based Access Control.

SECURITY NOTE: This module provides RBAC enforcement. Ensure authentication
middleware sets the current user context using set_current_user() before
requests are processed.
"""

from dataclasses import dataclass, field
from typing import Any

from ..errors.base import AuthenticationError, AuthorizationError, ErrorCode
from .context import get_current_user_role, is_authenticated


@dataclass
class Permission:
    """Permission definition."""

    name: str
    resource: str
    action: str

    def __str__(self) -> str:
        """Return string representation."""
        return f"{self.resource}:{self.action}"


@dataclass
class Role:
    """Role with permissions."""

    name: str
    permissions: set[str] = field(default_factory=set)

    def has_permission(self, permission: str) -> bool:
        """Check if role has permission."""
        return permission in self.permissions or "*" in self.permissions


class RBAC:
    """Role-Based Access Control system.

    Examples:
        >>> rbac = RBAC()
        >>> rbac.define_role("admin", ["users:read", "users:write"])
        >>> rbac.define_role("user", ["users:read"])
        >>>
        >>> @rbac.requires("users:write")
        ... async def update_user():
        ...     pass
    """

    def __init__(self) -> None:
        """Initialize RBAC."""
        self._roles: dict[str, Role] = {}

    def define_role(self, role_name: str, permissions: list[str]) -> None:
        """Define a role with permissions.

        Args:
            role_name: Role name
            permissions: List of permission strings
        """
        self._roles[role_name] = Role(role_name, set(permissions))

    def has_permission(self, role_name: str, permission: str) -> bool:
        """Check if role has permission.

        Args:
            role_name: Role name
            permission: Permission string

        Returns:
            True if role has permission
        """
        role = self._roles.get(role_name)
        return role.has_permission(permission) if role else False

    def requires(self, permission: str, allow_unauthenticated: bool = False) -> Any:
        """Decorator to require permission.

        Args:
            permission: Required permission (e.g., "users:write")
            allow_unauthenticated: If True, allows unauthenticated requests
                                  (useful for optional auth). Default: False

        Returns:
            Decorator function

        Raises:
            AuthenticationError: If user is not authenticated
            AuthorizationError: If user lacks required permission

        Example:
            >>> rbac = RBAC()
            >>> rbac.define_role("admin", ["users:read", "users:write"])
            >>> rbac.define_role("user", ["users:read"])
            >>>
            >>> @rbac.requires("users:write")
            ... async def update_user(user_id: int):
            ...     # Only users with "users:write" permission can access
            ...     pass
            >>>
            >>> @rbac.requires("posts:read", allow_unauthenticated=True)
            ... async def list_posts():
            ...     # Anyone can access, but permission checked if authenticated
            ...     pass

        Integration with Authentication:
            This decorator relies on the security context being set by your
            authentication middleware. Example middleware:

            >>> from unistax.security.context import set_current_user, clear_current_user
            >>>
            >>> @app.middleware("http")
            ... async def auth_middleware(request, call_next):
            ...     try:
            ...         # Extract and validate token from request
            ...         token = request.headers.get("Authorization")
            ...         user_data = validate_token(token)  # Your auth logic
            ...
            ...         # Set current user context
            ...         set_current_user({
            ...             "id": user_data["id"],
            ...             "username": user_data["username"],
            ...             "role": user_data["role"],
            ...         })
            ...
            ...         response = await call_next(request)
            ...         return response
            ...     finally:
            ...         # Always clear context after request
            ...         clear_current_user()
        """

        def decorator(func: Any) -> Any:
            from functools import wraps

            @wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                # Check if user is authenticated
                if not is_authenticated():
                    if allow_unauthenticated:
                        # Skip permission check for unauthenticated users
                        return await func(*args, **kwargs)
                    raise AuthenticationError(
                        "Authentication required",
                        code=ErrorCode.AUTH_REQUIRED,
                        details={"required_permission": permission},
                    )

                # Get user role from context
                user_role = get_current_user_role()
                if not user_role:
                    raise AuthenticationError(
                        "User role not found in context",
                        code=ErrorCode.AUTH_REQUIRED,
                        details={"required_permission": permission},
                    )

                # Check permission
                if not self.has_permission(user_role, permission):
                    raise AuthorizationError(
                        f"Insufficient permissions. Required: {permission}",
                        code=ErrorCode.AUTHZ_INSUFFICIENT_PERMISSIONS,
                        details={
                            "required_permission": permission,
                            "user_role": user_role,
                        },
                    )

                return await func(*args, **kwargs)

            return wrapper

        return decorator
