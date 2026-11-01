"""Marks requests to the old unversioned paths (e.g. /users) as deprecated in favour of /api/v1/...

The old paths keep working until the frontend has switched; watch the `app.deprecated` log to see what still uses them.
"""

import logging

from app.request_context import current_request

API_PREFIX = "/api/v1"
# Served only at the root, so not "old" paths.
ROOT_PATHS = {"/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}

logger = logging.getLogger("app.deprecated")


class LegacyPathMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or path.startswith("/api/") or path in ROOT_PATHS:
            await self.app(scope, receive, send)
            return

        async def send_with_deprecation(message):
            if message["type"] == "http.response.start" and message["status"] != 404:
                message.setdefault("headers", []).extend(
                    [
                        (b"deprecation", b"true"),
                        (b"link", f'<{API_PREFIX}{path}>; rel="successor-version"'.encode()),
                    ]
                )
                info = current_request()
                logger.info(
                    "Old path used: %s %s (use %s%s) user=%s",
                    scope["method"],
                    path,
                    API_PREFIX,
                    path,
                    (info.username if info else None) or "-",
                )
            await send(message)

        await self.app(scope, receive, send_with_deprecation)
