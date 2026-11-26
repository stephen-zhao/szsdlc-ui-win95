"""Mapping in: HTTP requests to what the service takes.

The write guard (same origin, the launch token, a small JSON body), validation
against the wire model, query parameters, and wire-model requests turned into
service arguments. The mirror of `map_responses`; a refusal here is raised as
`Refused` with its problem.
"""

from __future__ import annotations

import json
import secrets
from http import HTTPStatus
from typing import Any, Callable
from urllib.parse import urlparse

from fastapi import Request
from pydantic import BaseModel, ValidationError

from .map_responses import Refused, problem
from .wire_model import OpenProjectRequest, RefreshRequest

MAX_BODY = 65536


def write_guard(allowed_hosts: frozenset[str], token: str) -> Callable[[Request], Any]:
    """The dependency every write takes: same origin, this launch's token, a small JSON body. In that order."""
    async def write_body(request: Request) -> dict:
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
    return write_body


def validated(model: type[BaseModel], body: dict) -> Any:
    """`body` as `model`, or the viewer's 400 (never FastAPI's 422)."""
    try:
        return model.model_validate(body)
    except ValidationError as err:
        raise Refused(problem(HTTPStatus.BAD_REQUEST, "Not a valid request", str(err).splitlines()[0])) from None


def body_schema(model: type[BaseModel]) -> dict:
    """Describe a request body the write guard reads raw, so it still appears in /api/openapi.json."""
    return {"requestBody": {"required": False, "content": {"application/json": {"schema": model.model_json_schema()}}}}


def query(request: Request, key: str, default: str = "") -> str:
    """A query parameter's first value, as the viewer has always read them."""
    values = request.query_params.getlist(key)
    return values[0] if values else default


def open_project_args(body: dict) -> tuple[str, str | None]:
    """An Open project body as `(location, code_root)`; `store` is the 0.1 name for `location`."""
    asked = validated(OpenProjectRequest, body)
    return asked.location or asked.store or "", asked.code_root


def refresh_args(body: dict) -> bool:
    """A Refresh body as `replace`."""
    return validated(RefreshRequest, body).replace
