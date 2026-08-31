"""Low-risk response hardening shared by every API route.

This is a pure ASGI middleware rather than ``BaseHTTPMiddleware`` so streaming
responses keep their normal cancellation and back-pressure behaviour.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from typing import Any

from marko.core.config import Settings

ASGIApp = Callable[
    [dict[str, Any], Callable[..., Awaitable[Any]], Callable[..., Awaitable[Any]]],
    Awaitable[None],
]


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self._production = settings.is_production
        self._hsts_max_age = max(0, settings.hsts_max_age_seconds)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = secrets.token_hex(16)

        async def send_hardened(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", ()))
                existing = {name.lower() for name, _ in headers}

                def add(name: str, value: str) -> None:
                    encoded = name.lower().encode("ascii")
                    if encoded not in existing:
                        headers.append((encoded, value.encode("ascii")))
                        existing.add(encoded)

                add("X-Content-Type-Options", "nosniff")
                add("Referrer-Policy", "no-referrer")
                add("X-Frame-Options", "DENY")
                add(
                    "Content-Security-Policy",
                    "default-src 'none'; base-uri 'none'; form-action 'none'; "
                    "frame-ancestors 'none'",
                )
                add(
                    "Permissions-Policy",
                    "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
                )
                add("Cross-Origin-Opener-Policy", "same-origin")
                add("X-Request-ID", request_id)
                add("Cache-Control", "no-store")
                if self._production and self._hsts_max_age:
                    add(
                        "Strict-Transport-Security",
                        f"max-age={self._hsts_max_age}",
                    )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_hardened)


__all__ = ["SecurityHeadersMiddleware"]
