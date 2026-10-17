"""Per-caller rate limiting built on ``unistax.ratelimit``.

Counters live in process memory, so the limits apply per worker process.
Run a single worker, or enforce a global limit at your gateway as well.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, Response, status

from unistax.agents.api.auth import Principal, get_principal
from unistax.agents.api.settings import AgentAPISettings
from unistax.ratelimit import RateLimiter


class RateLimits:
    """The limiters used by the API."""

    def __init__(self, settings: AgentAPISettings) -> None:
        self.enabled = settings.rate_limit_enabled
        self.general = RateLimiter(
            limit=settings.rate_limit, window=settings.rate_limit_window, algorithm="sliding_window"
        )
        self.expensive = RateLimiter(
            limit=settings.expensive_rate_limit,
            window=settings.rate_limit_window,
            algorithm="sliding_window",
        )


def _enforce(limiter: RateLimiter, key: str, response: Response) -> None:
    allowed = limiter.is_allowed(key)
    info = limiter.get_limit_info(key)
    headers = {
        "X-RateLimit-Limit": str(info.limit),
        "X-RateLimit-Remaining": str(info.remaining),
        "X-RateLimit-Reset": str(info.reset),
    }
    if not allowed:
        headers["Retry-After"] = str(info.retry_after or limiter.window)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers=headers,
        )
    response.headers.update(headers)


async def rate_limit(
    request: Request, response: Response, principal: Principal = Depends(get_principal)
) -> None:
    """Router-level dependency: general per-caller limit."""
    limits: RateLimits = request.app.state.runtime.limits
    if limits.enabled:
        _enforce(limits.general, f"user:{principal.subject}", response)


async def expensive_rate_limit(
    request: Request, response: Response, principal: Principal = Depends(get_principal)
) -> None:
    """Extra, tighter limit for endpoints that start work (tasks, workflows)."""
    limits: RateLimits = request.app.state.runtime.limits
    if limits.enabled:
        _enforce(limits.expensive, f"expensive:{principal.subject}", response)
