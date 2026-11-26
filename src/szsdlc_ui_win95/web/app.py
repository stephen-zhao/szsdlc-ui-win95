"""The viewer's HTTP API and static files, as a FastAPI app over a ViewerService."""

from __future__ import annotations

import json
import mimetypes
import secrets
from http import HTTPStatus
from importlib import resources
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import Response

from .. import __version__
from ..services import ServiceError, ViewerService
from .asgi import Harden
from .dtos import (ListProjectsResponse, MetaResponse, OpenProjectRequest, OpenProjectResponse,
                   RefreshRequest, RefreshResponse)
from .responses import problem, refusal, send, send_json

STATIC = Path(str(resources.files("szsdlc_ui_win95") / "static")).resolve()
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
TOKEN_META = b'<meta name="viewer-token" content="">'
MAX_BODY = 65536
HEADERS = {"Server": f"szsdlc-ui-win95/{__version__}", "X-Content-Type-Options": "nosniff",
           "Referrer-Policy": "no-referrer", "Content-Security-Policy": CSP}


class Refused(Exception):
    """Raised by the write guard; answered with its problem."""

    def __init__(self, response: Response):
        self.response = response


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

    async def write_body(request: Request) -> dict:
        """Every write: same origin, this launch's token, a small JSON body. In that order."""
        origin = request.headers.get("origin")
        if origin and urlparse(origin).hostname not in allowed_hosts:
            raise Refused(problem(HTTPStatus.FORBIDDEN, "Cross-origin request",
                                  "Requests must come from the viewer's own page."))
        if not secrets.compare_digest(request.headers.get("x-viewer-token", ""), token):
            raise Refused(problem(HTTPStatus.FORBIDDEN, "Missing launch token",
                                  "Reload the viewer page to pick up this launch's token."))
        too_large = problem(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Body too large", "Bodies are limited to 64 KiB.")
        if int(request.headers.get("content-length") or 0) > MAX_BODY:
            raise Refused(too_large)
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise Refused(too_large)
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            raise Refused(problem(HTTPStatus.BAD_REQUEST, "Not JSON", "Send a JSON object.")) from None
        return body if isinstance(body, dict) else {}

    def validated(model, body: dict):
        try:
            return model.model_validate(body)
        except ValidationError as err:
            raise Refused(problem(HTTPStatus.BAD_REQUEST, "Not a valid request",
                                  str(err).splitlines()[0])) from None

    def body_schema(model) -> dict:
        """Describe a request body the write guard reads raw, so it still appears in the API description."""
        return {"requestBody": {"required": False, "content": {"application/json": {"schema": model.model_json_schema()}}}}

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

    @read("/api/p/{pid}/{route:path}")
    def project_route(pid: str, route: str, request: Request):
        def q(key: str, default: str = "") -> str:
            values = request.query_params.getlist(key)
            return values[0] if values else default

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
            return send_json(service.doc(pid, q("root", "store"), q("path"), q("fallback") == "1"))
        if route == "raw":
            found = service.raw(pid, q("root", "store"), q("path"))
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
        asked = validated(OpenProjectRequest, body)
        return send_json(service.open_project(asked.location or asked.store or "", asked.code_root),
                         HTTPStatus.CREATED)

    @app.post("/api/p/{pid}/refresh", response_model=RefreshResponse, openapi_extra=body_schema(RefreshRequest))
    def refresh(pid: str, body: dict = Depends(write_body)):
        service.known(pid)  # an unknown project is named before a bad body
        asked = validated(RefreshRequest, body)
        return send_json(service.refresh(pid, replace=asked.replace))

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
