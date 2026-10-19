"""JWT bearer authentication and role-based authorisation for the agent API.

Roles (a higher role includes everything below it):

* ``viewer``   - read-only access (GET endpoints, WebSocket event stream)
* ``operator`` - submit/cancel tasks, run workflows, write to the knowledge graph
* ``admin``    - create/update/delete agents and teams

Tokens are issued by your identity provider. They must be signed with the
configured key, carry an ``exp`` claim, and a ``role`` (string) or ``roles``
(list) claim containing one of the roles above. For service accounts and local
use, generate a token with::

    python -m unistax.agents.api.auth --subject ci-bot --role operator
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from unistax.agents.api.settings import AgentAPISettings
from unistax.logging import get_logger
from unistax.security import JWT, JWTError, User, set_current_user

logger = get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)


class Role(IntEnum):
    """API roles, ordered by privilege."""

    VIEWER = 1
    OPERATOR = 2
    ADMIN = 3


@dataclass(frozen=True)
class Principal:
    """The authenticated caller."""

    subject: str
    role: Role
    claims: dict[str, Any] = field(default_factory=dict, compare=False)


ANONYMOUS = Principal(subject="anonymous", role=Role.ADMIN)


class AuthError(Exception):
    """Raised when a token cannot be accepted."""

    def __init__(self, message: str, status_code: int = status.HTTP_401_UNAUTHORIZED):
        super().__init__(message)
        self.status_code = status_code


class Authenticator:
    """Validates bearer tokens against the configured key."""

    def __init__(self, settings: AgentAPISettings) -> None:
        self._settings = settings
        key = settings.jwt_public_key or settings.jwt_secret or ""
        self._jwt = JWT(
            secret=key,
            public_key=settings.jwt_public_key,
            algorithm=settings.jwt_algorithm,
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            leeway=10,
        )

    def authenticate(self, token: str) -> Principal:
        try:
            claims = self._jwt.decode(token)
        except JWTError as exc:
            raise AuthError("Invalid or expired token") from exc

        if "exp" not in claims:
            raise AuthError("Token has no expiry")

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise AuthError("Token has no subject")

        role = _highest_role(claims)
        if role is None:
            raise AuthError("Token carries no recognised role", status.HTTP_403_FORBIDDEN)

        return Principal(subject=subject, role=role, claims=claims)


def _highest_role(claims: dict[str, Any]) -> Role | None:
    raw: list[Any] = []
    if "role" in claims:
        raw.append(claims["role"])
    if isinstance(claims.get("roles"), list):
        raw.extend(claims["roles"])

    roles = []
    for value in raw:
        if isinstance(value, str) and value.upper() in Role.__members__:
            roles.append(Role[value.upper()])
    return max(roles) if roles else None


def create_access_token(
    settings: AgentAPISettings,
    subject: str,
    role: Role | str = Role.VIEWER,
    expires_in: int = 3600,
) -> str:
    """Issue a signed token (needs the signing secret/private key)."""
    if not settings.jwt_secret:
        raise ValueError("A signing secret is required to issue tokens")
    role_name = (role.name if isinstance(role, Role) else str(role)).lower()
    signer = JWT(
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )
    return signer.encode({"sub": subject, "role": role_name}, exp=expires_in)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    """Resolve the caller from the ``Authorization: Bearer`` header."""
    runtime = request.app.state.runtime

    if not runtime.settings.auth_enabled:
        principal = ANONYMOUS
    else:
        if credentials is None:
            raise _unauthorized("Missing bearer token")
        try:
            principal = runtime.authenticator.authenticate(credentials.credentials)
        except AuthError as exc:
            if exc.status_code == status.HTTP_403_FORBIDDEN:
                raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
            raise _unauthorized(str(exc)) from exc

    request.state.principal = principal
    set_current_user(
        User(id=principal.subject, username=principal.subject, role=principal.role.name.lower())
    )
    return principal


def require_role(minimum: Role) -> Callable[..., Coroutine[Any, Any, Principal]]:
    """Dependency factory: the caller must hold at least ``minimum``."""

    async def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role < minimum:
            logger.warning(
                "Forbidden: %s (role=%s) needs %s",
                principal.subject,
                principal.role.name,
                minimum.name,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role '{minimum.name.lower()}'",
            )
        return principal

    return dependency


require_viewer = require_role(Role.VIEWER)
require_operator = require_role(Role.OPERATOR)
require_admin = require_role(Role.ADMIN)


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue an agent API access token")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--role", choices=[r.name.lower() for r in Role], default="viewer")
    parser.add_argument("--expires-in", type=int, default=3600, help="lifetime in seconds")
    args = parser.parse_args()

    settings = AgentAPISettings.from_env()
    settings.validate()
    print(create_access_token(settings, args.subject, args.role, args.expires_in))


if __name__ == "__main__":
    main()
