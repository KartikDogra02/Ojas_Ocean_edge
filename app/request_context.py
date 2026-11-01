"""Per-request information shared between the logging middleware, the auth dependency and the audit log."""

import logging
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

logger = logging.getLogger("app.requests")


@dataclass
class RequestInfo:
    request_id: str
    username: str | None = None


_current: ContextVar[RequestInfo | None] = ContextVar("request_info", default=None)


def current_request() -> RequestInfo | None:
    return _current.get()


def set_username(username: str) -> None:
    if info := _current.get():
        info.username = username


class RequestLoggingMiddleware:
    """Gives each request an id (X-Request-ID, reused if the client sends one) and logs one line per request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode()[:64]
        info = RequestInfo(request_id=incoming or uuid.uuid4().hex)
        token = _current.set(info)
        started = time.perf_counter()
        status_code = 500

        async def send_with_id(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", info.request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            logger.info(
                "%s %s %s %.0fms user=%s id=%s",
                scope["method"],
                scope["path"],
                status_code,
                (time.perf_counter() - started) * 1000,
                info.username or "-",
                info.request_id,
            )
            _current.reset(token)
