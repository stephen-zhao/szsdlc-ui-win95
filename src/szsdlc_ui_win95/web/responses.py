"""Rendering: exact Content-Types, JSON, and application/problem+json."""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any

from starlette.responses import Response

from ..services import Conflict, Forbidden, Invalid, NotFound, ServiceError

#: How each service refusal is answered over HTTP.
STATUS = {NotFound: HTTPStatus.NOT_FOUND, Forbidden: HTTPStatus.FORBIDDEN,
          Invalid: HTTPStatus.BAD_REQUEST, Conflict: HTTPStatus.CONFLICT}


def send(status: int, body: bytes, ctype: str, extra: dict | None = None) -> Response:
    """A response with exactly this Content-Type (no charset added for us)."""
    return Response(content=body, status_code=int(status), headers={"Content-Type": ctype, **(extra or {})})


def send_json(obj: Any, status: int = HTTPStatus.OK) -> Response:
    return send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8",
                {"Cache-Control": "no-store"})


def problem(status: int, title: str, detail: str, fix: str | None = None) -> Response:
    body = {"type": "about:blank", "title": title, "status": int(status), "detail": detail, **({"fix": fix} if fix else {})}
    return send(status, json.dumps(body).encode(), "application/problem+json", {"Cache-Control": "no-store"})


def refusal(err: ServiceError) -> Response:
    status = next((s for cls, s in STATUS.items() if isinstance(err, cls)), HTTPStatus.BAD_REQUEST)
    return problem(status, err.title, err.detail, err.fix)
