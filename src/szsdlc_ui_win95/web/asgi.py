"""Raw ASGI middleware: the host check and the headers every response carries.

Raw ASGI rather than Starlette's BaseHTTPMiddleware, which buffers and wraps
every request; a dependency cannot do this, because it must cover every
response, including 404s, refusals and the API description.
"""

from __future__ import annotations

from typing import Iterable


class Harden:
    """Refuse a Host this server was not started on (DNS rebinding); harden every response."""

    def __init__(self, app, *, allowed_hosts: Iterable[str], headers: dict[str, str]):
        self.app = app
        self.allowed_hosts = frozenset(allowed_hosts)
        self.headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]
        self.names = {k for k, _ in self.headers}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def hardened(message):
            if message["type"] == "http.response.start":
                kept = [(k, v) for k, v in message.get("headers", []) if k.lower() not in self.names]
                message = {**message, "headers": kept + self.headers}
            await send(message)

        host = dict(scope.get("headers") or []).get(b"host", b"").decode("latin-1")
        if host.rsplit(":", 1)[0].strip("[]") not in self.allowed_hosts:
            body = b"forbidden host"
            await hardened({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"text/plain"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, hardened)
