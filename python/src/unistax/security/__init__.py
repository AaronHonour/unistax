"""Security Module.

Provides security utilities:
- JWT encoding/decoding
- Password hashing
- RBAC/permissions
- Security context management
"""

from .context import (
    User,
    clear_current_user,
    get_current_user,
    get_current_user_id,
    get_current_user_role,
    has_role,
    is_authenticated,
    set_current_user,
)
from .jwt import (
    JWT,
    JWTDecodeError,
    JWTError,
    JWTExpiredError,
    JWTInvalidAudienceError,
    JWTInvalidIssuerError,
    JWTInvalidSignatureError,
)
from .password import PasswordHasher
from .rbac import RBAC, Permission, Role

__all__ = [
    "JWT",
    "JWTError",
    "JWTDecodeError",
    "JWTExpiredError",
    "JWTInvalidSignatureError",
    "JWTInvalidAudienceError",
    "JWTInvalidIssuerError",
    "PasswordHasher",
    "RBAC",
    "Permission",
    "Role",
    # Context management
    "User",
    "set_current_user",
    "get_current_user",
    "get_current_user_role",
    "get_current_user_id",
    "has_role",
    "is_authenticated",
    "clear_current_user",
]
