"""The local HTTP server: the viewer's static files and a small, read-only JSON API.

Routes (every project route is scoped by project id):

    GET  /api/meta                       viewer and szsdlc versions
    GET  /api/projects                   the projects this viewer serves
    POST /api/projects  {location, code_root?}   open a project: a folder here or a repository
                                         URL; any backend (needs the launch token)
    GET  /api/p/<id>/project             name, backend, counts, load errors
    GET  /api/p/<id>/schema              the schema descriptor
    GET  /api/p/<id>/entities            one row per entity
    GET  /api/p/<id>/entities/<ref>      one entity in full
    GET  /api/p/<id>/roadmaps            placement, per horizon
    GET  /api/p/<id>/docs                generated views and loose documents
    GET  /api/p/<id>/doc?root=&path=     one document (front matter split, raw kept)
    GET  /api/p/<id>/raw?root=&path=     bytes, for images; never active content

Hardening: loopback by default; any Host header the server was not started on is
refused (DNS rebinding); the one write (opening a project) needs a per-launch
token embedded in the page, plus a same-origin Origin; paths are contained to
their root; CSP allows only the server's own scripts.
"""

from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import szsdlc

from . import __version__
from .project import ProjectError
from .registry import Registry

STATIC = Path(str(resources.files("szsdlc_ui_win95") / "static")).resolve()
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
TOKEN_META = b'<meta name="viewer-token" content="">'
MAX_BODY = 65536


def meta() -> dict:
    return {"viewer": "szsdlc-ui-win95", "version": __version__, "szsdlc_version": szsdlc.__version__, "readonly": True}


class Handler(BaseHTTPRequestHandler):
    server_version = f"szsdlc-ui-win95/{__version__}"
    registry: Registry
    allowed_hosts: frozenset[str] = frozenset()
    token: str = ""
    allow_open: bool = True
    verbose: bool = False

    def log_message(self, fmt, *args):
        if self.verbose:
            super().log_message(fmt, *args)

    # -- responses -----------------------------------------------------------
    def _send(self, status, body: bytes, ctype: str, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, status=HTTPStatus.OK):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8",
                   {"Cache-Control": "no-store"})

    def _problem(self, status, title, detail, fix=None):
        body = {"type": "about:blank", "title": title, "status": int(status), "detail": detail, **({"fix": fix} if fix else {})}
        self._send(status, json.dumps(body).encode(), "application/problem+json", {"Cache-Control": "no-store"})

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in self.allowed_hosts:
            self._send(HTTPStatus.FORBIDDEN, b"forbidden host", "text/plain")
            return False
        return True

    # -- methods -------------------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        if not self._host_ok():
            return
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).hostname not in self.allowed_hosts:
            return self._problem(HTTPStatus.FORBIDDEN, "Cross-origin request", "Requests must come from the viewer's own page.")
        if not secrets.compare_digest(self.headers.get("X-Viewer-Token", ""), self.token):
            return self._problem(HTTPStatus.FORBIDDEN, "Missing launch token", "Reload the viewer page to pick up this launch's token.")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._problem(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Body too large", "Bodies are limited to 64 KiB.")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._problem(HTTPStatus.BAD_REQUEST, "Not JSON", "Send a JSON object.")
        if urlparse(self.path).path != "/api/projects":
            return self._problem(HTTPStatus.NOT_FOUND, "Unknown route", self.path)
        if not self.allow_open:
            return self._problem(HTTPStatus.FORBIDDEN, "Opening projects is disabled",
                                 "This viewer was started with --no-open; restart it with the project as an argument.")
        # `store` is the 0.1 field name; a location may be a folder here or a repository URL.
        where = str(body.get("location") or body.get("store") or "").strip() if isinstance(body, dict) else ""
        if not where:
            return self._problem(HTTPStatus.BAD_REQUEST, "No location given",
                                 "Name a folder on this computer, or a repository URL.")
        try:
            code = body.get("code_root")
            pid = self.registry.add(where, Path(code) if code else None, persist=True)
        except ProjectError as err:
            return self._problem(HTTPStatus.BAD_REQUEST, "Cannot open that project", str(err),
                                 fix="Give a folder on this computer that holds a szsdlc project, or where one "
                                     "is kept, such as https://host/org/repo.git.")
        return self._json(self.registry.summary(pid, self.registry.get(pid)), HTTPStatus.CREATED)

    def do_GET(self):
        if not self._host_ok():
            return
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/api/meta":
            return self._json(meta())
        if url.path == "/api/projects":
            return self._json(self.registry.listing())
        if url.path.startswith("/api/p/"):
            pid, _, route = url.path[len("/api/p/"):].partition("/")
            project = self.registry.get(pid)
            if project is None:
                return self._problem(HTTPStatus.NOT_FOUND, "No such project", f"This viewer has no project `{pid}`.")
            return self._project_route(project, route, q)
        if url.path.startswith("/api/"):
            return self._problem(HTTPStatus.NOT_FOUND, "Unknown route", url.path)
        return self._static(url.path)

    def _project_route(self, project, route: str, q: dict):
        project.refresh()
        if route == "project":
            return self._json(project.info())
        if route == "schema":
            return self._json(project.schema)
        if route == "entities":
            return self._json(project.rows())
        if route.startswith("entities/"):
            ref = route.split("/", 1)[1]
            found = project.entity(ref)
            return self._json(found) if found else self._problem(HTTPStatus.NOT_FOUND, "No such entity", ref)
        if route == "roadmaps":
            return self._json(project.roadmaps)
        if route == "docs":
            return self._json(project.store_docs)
        if route == "doc":
            return self._json(project.doc(q.get("root", "store"), q.get("path", ""), q.get("fallback") == "1"))
        if route == "raw":
            p = project.roots.safe_path(q.get("root", "store"), posixpath.normpath(q.get("path", "")))
            if not p or not p.is_file():
                return self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            if ctype in ("text/html", "image/svg+xml", "application/xhtml+xml") or ctype.endswith("javascript"):
                ctype = "text/plain; charset=utf-8"  # never serve store content as active content
            return self._send(HTTPStatus.OK, p.read_bytes(), ctype)
        return self._problem(HTTPStatus.NOT_FOUND, "Unknown route", route)

    def _static(self, path: str):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        p = (STATIC / rel).resolve()
        try:
            p.relative_to(STATIC)
        except ValueError:
            return self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
        if not p.is_file():
            return self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        data = p.read_bytes()
        if rel == "index.html":
            data = data.replace(TOKEN_META, f'<meta name="viewer-token" content="{self.token}">'.encode())
            return self._send(HTTPStatus.OK, data, ctype, {"Cache-Control": "no-store"})
        return self._send(HTTPStatus.OK, data, ctype, {"Cache-Control": "no-cache"})


def make_server(registry: Registry, host: str = "127.0.0.1", port: int = 8095, *,
                allow_open: bool = True, verbose: bool = False) -> ThreadingHTTPServer:
    """A configured server, not yet serving. Port 0 picks a free port."""
    handler = type("BoundHandler", (Handler,), {
        "registry": registry,
        "allowed_hosts": frozenset({"127.0.0.1", "localhost", "::1", host}),
        "token": secrets.token_urlsafe(24),
        "allow_open": allow_open,
        "verbose": verbose or bool(os.environ.get("SZUI_LOG")),
    })
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server
