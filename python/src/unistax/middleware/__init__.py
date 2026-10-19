"""Middleware Module.

Provides request/response middleware pipeline with:
- Middleware chain execution
- Request/response context
- Built-in middleware (logging, metrics, auth, security, rate limiting, CSRF, etc.)
"""

from .builtin import (
    CORSMiddleware,
    ErrorHandlerMiddleware,
    LoggingMiddleware,
    MetricsMiddleware,
    SecurityHeadersMiddleware,
)
from .pipeline import Middleware, MiddlewarePipeline, NextHandler, Request, Response

__all__ = [
    "MiddlewarePipeline",
    "Middleware",
    "Request",
    "Response",
    "NextHandler",
    "LoggingMiddleware",
    "MetricsMiddleware",
    "ErrorHandlerMiddleware",
    "CORSMiddleware",
    "SecurityHeadersMiddleware",
]
