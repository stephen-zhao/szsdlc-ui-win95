"""The viewer's HTTP API and static files, as a FastAPI app over a ViewerService."""

from __future__ import annotations

import mimetypes
from http import HTTPStatus
from importlib import resources
from pathlib import Path

from fastapi import Depends, FastAPI, Request

from .. import __version__
from ..services import ServiceError, ViewerService
from .asgi import Harden
from .map_requests import (body_schema, capture_args, open_project_args, query, refresh_args, set_args, tag_args,
                           write_guard)
from .map_responses import Refused, problem, refusal, send, send_json
from .wire_model import (CaptureRequest, ChangesResponse, EditResponse, FindingsResponse, ListProjectsResponse, MetaResponse,
                         OpenProjectRequest, OpenProjectResponse, RefreshRequest, RefreshResponse, SendResponse,
                         SetRequest, TagRequest)

STATIC = Path(str(resources.files("szsdlc_ui_win95") / "static")).resolve()
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
TOKEN_META = b'<meta name="viewer-token" content="">'
HEADERS = {"Server": f"szsdlc-ui-win95/{__version__}", "X-Content-Type-Options": "nosniff",
           "Referrer-Policy": "no-referrer", "Content-Security-Policy": CSP}


def create_app(service: ViewerService, *, allowed_hosts: frozenset[str], token: str) -> FastAPI:
    """The app. Every error is the viewer's application/problem+json, never FastAPI's own shapes."""
    app = FastAPI(title="szsdlc-ui-win95", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url="/api/openapi.json", redirect_slashes=False)
    app.add_middleware(Harden, allowed_hosts=allowed_hosts, headers=HEADERS)

    @app.exception_handler(Refused)
    async def refused(request: Request, exc: Refused):
        return exc.response

    @app.exception_handler(ServiceError)
    async def service_refused(request: Request, exc: ServiceError):
        return refusal(exc)

    write_body = write_guard(allowed_hosts, token)

    def read(path: str, **kwargs):
        """A GET route, answering HEAD too: FastAPI routes GET alone. HEAD stays out of the schema."""
        def register(fn):
            app.get(path, **kwargs)(fn)
            app.add_api_route(path, fn, methods=["HEAD"], include_in_schema=False)
            return fn
        return register

    # -- reads ---------------------------------------------------------------
    @read("/api/meta", response_model=MetaResponse)
    def meta():
        return send_json(service.meta())

    @read("/api/projects", response_model=ListProjectsResponse)
    def list_projects():
        return send_json(service.projects())

    @read("/api/p/{pid}/changes", response_model=ChangesResponse)
    def changes(pid: str):
        return send_json(service.changes(pid))

    @read("/api/p/{pid}/findings", response_model=FindingsResponse)
    def findings(pid: str):
        return send_json(service.findings(pid))

    @read("/api/p/{pid}/{route:path}")
    def project_route(pid: str, route: str, request: Request):
        def q(key: str, default: str = "") -> str:
            return query(request, key, default)

        if route == "project":
            return send_json(service.info(pid))
        if route == "schema":
            return send_json(service.schema(pid))
        if route == "entities":
            return send_json(service.entities(pid))
        if route.startswith("entities/"):
            return send_json(service.entity(pid, route.split("/", 1)[1]))
        if route == "roadmaps":
            return send_json(service.roadmaps(pid))
        if route == "docs":
            return send_json(service.docs(pid))
        if route == "doc":
            return send_json(service.doc(pid, q("root", "sdlc"), q("path"), q("fallback") == "1"))
        if route == "raw":
            found = service.raw(pid, q("root", "sdlc"), q("path"))
            if found is None:
                return send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
            return send(HTTPStatus.OK, found.data, found.content_type)
        service.project(pid)  # an unknown project is named before an unknown route
        return problem(HTTPStatus.NOT_FOUND, "Unknown route", route)

    @read("/api/{rest:path}")
    def unknown(rest: str):
        return problem(HTTPStatus.NOT_FOUND, "Unknown route", f"/api/{rest}")

    # -- writes --------------------------------------------------------------
    @app.post("/api/projects", status_code=HTTPStatus.CREATED, response_model=OpenProjectResponse,
              openapi_extra=body_schema(OpenProjectRequest))
    def open_project(body: dict = Depends(write_body)):
        service.ensure_can_open()  # --no-open is refused before the body is looked at
        return send_json(service.open_project(*open_project_args(body)), HTTPStatus.CREATED)

    @app.post("/api/p/{pid}/refresh", response_model=RefreshResponse, openapi_extra=body_schema(RefreshRequest))
    def refresh(pid: str, body: dict = Depends(write_body)):
        service.known(pid)  # an unknown project is named before a bad body
        return send_json(service.refresh(pid, replace=refresh_args(body)))

    # Edits: each through one szsdlc operation, never a file write. --read-only
    # is refused first, then an unknown project, then a bad body.
    @app.post("/api/p/{pid}/entities/{ref}/set", response_model=EditResponse, openapi_extra=body_schema(SetRequest))
    def set_fields(pid: str, ref: str, body: dict = Depends(write_body)):
        service.ensure_can_edit()
        service.known(pid)
        return send_json(service.set(pid, ref, **set_args(body)))

    @app.post("/api/p/{pid}/entities/{ref}/tag", response_model=EditResponse, openapi_extra=body_schema(TagRequest))
    def tag(pid: str, ref: str, body: dict = Depends(write_body)):
        service.ensure_can_edit()
        service.known(pid)
        return send_json(service.tag(pid, ref, add=True, **tag_args(body)))

    @app.post("/api/p/{pid}/entities/{ref}/untag", response_model=EditResponse, openapi_extra=body_schema(TagRequest))
    def untag(pid: str, ref: str, body: dict = Depends(write_body)):
        service.ensure_can_edit()
        service.known(pid)
        return send_json(service.tag(pid, ref, add=False, **tag_args(body)))

    @app.post("/api/p/{pid}/capture", response_model=EditResponse, openapi_extra=body_schema(CaptureRequest))
    def capture(pid: str, body: dict = Depends(write_body)):
        service.ensure_can_edit()
        service.known(pid)
        return send_json(service.capture(pid, **capture_args(body)))

    @app.post("/api/p/{pid}/send", response_model=SendResponse)
    def send_changes(pid: str, body: dict = Depends(write_body)):
        service.ensure_can_edit()
        return send_json(service.send(pid))

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
