"""The composition root: the viewer's service, its web app and the server, wired together.

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

Layers, inside out (AGENTS.md, "Layers"): the core (`registry`, `project`,
`locations`, `documents`), then `services` (the viewer's operations, framework-free),
then `web` (FastAPI on uvicorn). This module is the only one that knows all three.

Hardening: loopback by default; any Host header the server was not started on is
refused (DNS rebinding); the two writes (opening a project, refreshing one) need a
per-launch token embedded in the page, plus a same-origin Origin; paths are
contained to their root; CSP allows only the server's own scripts.
"""

from __future__ import annotations

import os
import secrets

from .registry import Registry
from .services import ViewerService
from .web.app import CSP, STATIC, create_app
from .web.server import Server

__all__ = ["CSP", "STATIC", "Server", "make_server", "meta"]


def meta() -> dict:
    """The viewer's and szsdlc's versions, as /api/meta reports them."""
    return ViewerService(Registry()).meta()


def make_server(registry: Registry, host: str = "127.0.0.1", port: int = 8095, *,
                allow_open: bool = True, verbose: bool = False) -> Server:
    """A configured server, not yet serving. Port 0 picks a free port."""
    token = secrets.token_urlsafe(24)
    service = ViewerService(registry, allow_open=allow_open)
    app = create_app(service, allowed_hosts=frozenset({"127.0.0.1", "localhost", "::1", host}), token=token)
    return Server(app, host, port, token=token, verbose=verbose or bool(os.environ.get("SZUI_LOG")))
