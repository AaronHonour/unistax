"""ASGI middleware: request ids, body size limit and basic response hardening."""

from __future__ import annotations

import re
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from unistax.logging.context import log_context

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")


class _BodyTooLarge(Exception):
    pass


class RequestHardeningMiddleware:
    """ASGI middleware for request ids, body size limits and response hardening.

    Assigns a request id (and puts it in the log context), caps request bodies
    and adds conservative security headers.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope["headers"]}
        supplied = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = supplied if _REQUEST_ID.match(supplied) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        token = log_context.set({"request_id": request_id})

        started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                extra = [
                    (b"x-request-id", request_id.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"cache-control", b"no-store"),
                ]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        received = 0

        async def receive_wrapper() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise _BodyTooLarge()
            return message

        try:
            length = headers.get(b"content-length", b"")
            if length.isdigit() and int(length) > self.max_body_bytes:
                raise _BodyTooLarge()
            await self.app(scope, receive_wrapper, send_wrapper)
        except _BodyTooLarge:
            if not started:
                body = b'{"detail":"Request body too large"}'
                await send_wrapper(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send_wrapper({"type": "http.response.body", "body": body})
        finally:
            log_context.reset(token)
