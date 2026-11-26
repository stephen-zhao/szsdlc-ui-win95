"""The local HTTP server: the viewer's static files and a small, read-only JSON API.

Routes (every project route is scoped by project id):

    GET  /api/meta                       viewer and szsdlc versions
    GET  /api/projects                   the projects this viewer serves
    POST /api/projects  {location, code_root?}   open a project: a folder here or a repository
                                         URL; any backend (needs the launch token)
    POST /api/p/<id>/refresh  {replace?} take the sdlc backend's latest, sending nothing;
                                         409 when unsent changes would be replaced
    GET  /api/p/<id>/project             name, backend, counts, load errors
    GET  /api/p/<id>/schema              the schema descriptor
    GET  /api/p/<id>/entities            one row per entity
    GET  /api/p/<id>/entities/<ref>      one entity in full
    GET  /api/p/<id>/roadmaps            placement, per horizon
    GET  /api/p/<id>/docs                generated views and loose documents
    GET  /api/p/<id>/doc?root=&path=     one document (front matter split, raw kept)
    GET  /api/p/<id>/raw?root=&path=     bytes, for images; never active content
    GET  /api/openapi.json               the API, described

Served by FastAPI on uvicorn. Hardening: loopback by default; any Host header the
server was not started on is refused (DNS rebinding); the two writes (opening a
project, refreshing one) need a per-launch token embedded in the page, plus a
same-origin Origin; paths are contained to their root; CSP allows only the
server's own scripts. Every error is application/problem+json, never
FastAPI's own shapes.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import posixpath
import secrets
import socket
import threading
from http import HTTPStatus
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import szsdlc
import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from . import __version__
from .errors import UnsentChanges
from .project import ProjectError
from .registry import Registry

STATIC = Path(str(resources.files("szsdlc_ui_win95") / "static")).resolve()
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
TOKEN_META = b'<meta name="viewer-token" content="">'
MAX_BODY = 65536
SERVER_HEADER = f"szsdlc-ui-win95/{__version__}"


def meta() -> dict:
    return {"viewer": "szsdlc-ui-win95", "version": __version__, "szsdlc_version": szsdlc.__version__, "readonly": True}


# ---------------------------------------------------------------- models
# Describe the shaped payloads. Handlers build their responses themselves (so
# the bytes are exactly the viewer's), and validate requests themselves (so a
# body that does not fit is the viewer's 400, never FastAPI's 422).

class OpenProject(BaseModel):
    """Open a project: a folder on this computer, or where a backend keeps one."""
    model_config = ConfigDict(extra="ignore")
    location: str | None = None
    #: The 0.1 name for `location`, still accepted.
    store: str | None = None
    code_root: str | None = None


class Refresh(BaseModel):
    model_config = ConfigDict(extra="ignore")
    #: Replace unsent changes rather than refuse (409).
    replace: StrictBool = False


class Meta(BaseModel):
    viewer: str
    version: str
    szsdlc_version: str
    readonly: bool


class ProjectSummary(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    entity_count: int


class RefreshResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    arrived: bool
    replaced: bool
    note: str | None = None
    project: ProjectSummary


# ------------------------------------------------------------- responses

def send(status: int, body: bytes, ctype: str, extra: dict | None = None) -> Response:
    """A response with exactly this Content-Type (no charset added for us)."""
    return Response(content=body, status_code=int(status), headers={"Content-Type": ctype, **(extra or {})})


def send_json(obj: Any, status: int = HTTPStatus.OK) -> Response:
    return send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8",
                {"Cache-Control": "no-store"})


def problem(status: int, title: str, detail: str, fix: str | None = None) -> Response:
    body = {"type": "about:blank", "title": title, "status": int(status), "detail": detail, **({"fix": fix} if fix else {})}
    return send(status, json.dumps(body).encode(), "application/problem+json", {"Cache-Control": "no-store"})


class Refusal(Exception):
    """Raised by the write guard; answered with its problem response."""

    def __init__(self, response: Response):
        self.response = response


# ------------------------------------------------------------------- app

def create_app(registry: Registry, *, allowed_hosts: frozenset[str], token: str,
               allow_open: bool = True) -> FastAPI:
    """The viewer's API and static files, as an ASGI app."""
    app = FastAPI(title="szsdlc-ui-win95", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url="/api/openapi.json", redirect_slashes=False)

    @app.middleware("http")
    async def harden(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in allowed_hosts:
            response = send(HTTPStatus.FORBIDDEN, b"forbidden host", "text/plain")
        else:
            response = await call_next(request)
        response.headers["Server"] = SERVER_HEADER
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = CSP
        return response

    @app.exception_handler(Refusal)
    async def refused(request: Request, exc: Refusal):
        return exc.response

    def read(path: str, **kwargs):
        """A GET route, answering HEAD too: FastAPI routes GET alone. HEAD stays out of the schema."""
        def register(fn):
            app.get(path, **kwargs)(fn)
            app.add_api_route(path, fn, methods=["HEAD"], include_in_schema=False)
            return fn
        return register

    async def write_body(request: Request) -> dict:
        """Every write: same origin, this launch's token, a small JSON body. In that order."""
        origin = request.headers.get("origin")
        if origin and urlparse(origin).hostname not in allowed_hosts:
            raise Refusal(problem(HTTPStatus.FORBIDDEN, "Cross-origin request",
                                  "Requests must come from the viewer's own page."))
        if not secrets.compare_digest(request.headers.get("x-viewer-token", ""), token):
            raise Refusal(problem(HTTPStatus.FORBIDDEN, "Missing launch token",
                                  "Reload the viewer page to pick up this launch's token."))
        too_large = problem(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Body too large", "Bodies are limited to 64 KiB.")
        if int(request.headers.get("content-length") or 0) > MAX_BODY:
            raise Refusal(too_large)
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise Refusal(too_large)
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            raise Refusal(problem(HTTPStatus.BAD_REQUEST, "Not JSON", "Send a JSON object.")) from None
        return body if isinstance(body, dict) else {}

    # -- reads ---------------------------------------------------------------
    @read("/api/meta", response_model=Meta)
    def get_meta():
        return send_json(meta())

    @read("/api/projects", response_model=list[ProjectSummary])
    def get_projects():
        return send_json(registry.listing())

    @read("/api/p/{pid}/{route:path}")
    def get_project_route(pid: str, route: str, request: Request):
        project = registry.get(pid)
        if project is None:
            return problem(HTTPStatus.NOT_FOUND, "No such project", f"This viewer has no project `{pid}`.")
        return project_route(project, route, request)

    @read("/api/{rest:path}")
    def get_unknown(rest: str):
        return problem(HTTPStatus.NOT_FOUND, "Unknown route", f"/api/{rest}")

    # -- writes --------------------------------------------------------------
    @app.post("/api/projects", status_code=HTTPStatus.CREATED, response_model=ProjectSummary)
    def open_project(body: dict = Depends(write_body)):
        if not allow_open:
            return problem(HTTPStatus.FORBIDDEN, "Opening projects is disabled",
                           "This viewer was started with --no-open; restart it with the project as an argument.")
        try:
            asked = OpenProject.model_validate(body)
        except ValidationError as err:
            return problem(HTTPStatus.BAD_REQUEST, "Not a valid request", str(err).splitlines()[0])
        # A location may be a folder here or a repository URL.
        where = (asked.location or asked.store or "").strip()
        if not where:
            return problem(HTTPStatus.BAD_REQUEST, "No location given",
                           "Name a folder on this computer, or a repository URL.")
        try:
            pid = registry.add(where, Path(asked.code_root) if asked.code_root else None, persist=True)
        except ProjectError as err:
            return problem(HTTPStatus.BAD_REQUEST, "Cannot open that project", str(err),
                           fix="Give a folder on this computer that holds a szsdlc project, or where one "
                               "is kept, such as https://host/org/repo.git.")
        return send_json(registry.summary(pid, registry.get(pid)), HTTPStatus.CREATED)

    @app.post("/api/p/{pid}/refresh", response_model=RefreshResult)
    def refresh(pid: str, body: dict = Depends(write_body)):
        """Guarded like opening (token, origin) but not by --no-open: it opens nothing."""
        project = registry.get(pid)
        if project is None:
            return problem(HTTPStatus.NOT_FOUND, "No such project", pid)
        try:
            asked = Refresh.model_validate(body)
        except ValidationError as err:
            return problem(HTTPStatus.BAD_REQUEST, "Not a valid request", str(err).splitlines()[0])
        try:
            result = project.refresh_from_backend(replace=asked.replace)
        except UnsentChanges as err:
            return problem(HTTPStatus.CONFLICT, "Unsent changes would be replaced", str(err),
                           fix="Refresh anyway to replace them, or send them first.")
        except ProjectError as err:
            return problem(HTTPStatus.BAD_REQUEST, "Cannot refresh", str(err))
        return send_json({**result, "project": registry.summary(pid, project)})

    @app.post("/{path:path}", include_in_schema=False)
    def post_unknown(request: Request, body: dict = Depends(write_body)):
        where = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return problem(HTTPStatus.NOT_FOUND, "Unknown route", where)

    # -- static files --------------------------------------------------------
    @read("/{path:path}", include_in_schema=False)
    def static(path: str):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        p = (STATIC / rel).resolve()
        try:
            p.relative_to(STATIC)
        except ValueError:
            return send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
        if not p.is_file():
            return send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        data = p.read_bytes()
        if rel == "index.html":
            data = data.replace(TOKEN_META, f'<meta name="viewer-token" content="{token}">'.encode())
            return send(HTTPStatus.OK, data, ctype, {"Cache-Control": "no-store"})
        return send(HTTPStatus.OK, data, ctype, {"Cache-Control": "no-cache"})

    return app


def project_route(project, route: str, request: Request) -> Response:
    """One project's read routes. Re-reads the project first if its files changed."""
    def q(key: str, default: str = "") -> str:
        values = request.query_params.getlist(key)
        return values[0] if values else default

    project.refresh()
    if route == "project":
        return send_json(project.info())
    if route == "schema":
        return send_json(project.schema)
    if route == "entities":
        return send_json(project.rows())
    if route.startswith("entities/"):
        ref = route.split("/", 1)[1]
        found = project.entity(ref)
        return send_json(found) if found else problem(HTTPStatus.NOT_FOUND, "No such entity", ref)
    if route == "roadmaps":
        return send_json(project.roadmaps)
    if route == "docs":
        return send_json(project.store_docs)
    if route == "doc":
        return send_json(project.doc(q("root", "store"), q("path"), q("fallback") == "1"))
    if route == "raw":
        p = project.roots.safe_path(q("root", "store"), posixpath.normpath(q("path")))
        if not p or not p.is_file():
            return send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if ctype in ("text/html", "image/svg+xml", "application/xhtml+xml") or ctype.endswith("javascript"):
            ctype = "text/plain; charset=utf-8"  # never serve store content as active content
        return send(HTTPStatus.OK, p.read_bytes(), ctype)
    return problem(HTTPStatus.NOT_FOUND, "Unknown route", route)


# ---------------------------------------------------------------- server

class Server:
    """uvicorn serving the app on a socket bound up front.

    Bound in the constructor, as `http.server` did: a busy port raises OSError
    before anything is printed, and port 0's choice is known at once.
    """

    def __init__(self, app: FastAPI, host: str, port: int, *, token: str, verbose: bool = False):
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        self.socket = socket.socket(family, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.socket.bind((host, port))
            self.socket.listen(128)
        except OSError:
            self.socket.close()
            raise
        self.server_port = self.socket.getsockname()[1]
        self.token = token
        self.app = app
        config = uvicorn.Config(app, log_level=logging.INFO if verbose else logging.WARNING,
                                access_log=verbose, server_header=False, lifespan="off",
                                timeout_graceful_shutdown=2)
        self._server = uvicorn.Server(config)
        self._running = threading.Event()
        self._stopped = threading.Event()

    def serve_forever(self) -> None:
        """Serve until shutdown() (or Ctrl-C on the main thread, which uvicorn handles)."""
        self._running.set()
        try:
            self._server.run(sockets=[self.socket])
        finally:
            self._stopped.set()

    def shutdown(self) -> None:
        """Stop serving, and wait until it has."""
        self._server.should_exit = True
        if self._running.is_set():
            self._stopped.wait(10)

    def server_close(self) -> None:
        self.socket.close()


def make_server(registry: Registry, host: str = "127.0.0.1", port: int = 8095, *,
                allow_open: bool = True, verbose: bool = False) -> Server:
    """A configured server, not yet serving. Port 0 picks a free port."""
    token = secrets.token_urlsafe(24)
    app = create_app(registry, allowed_hosts=frozenset({"127.0.0.1", "localhost", "::1", host}),
                     token=token, allow_open=allow_open)
    return Server(app, host, port, token=token, verbose=verbose or bool(os.environ.get("SZUI_LOG")))
