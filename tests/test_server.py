from __future__ import annotations

import http.client
import json
import threading

import pytest

from szsdlc_ui_win95.registry import Registry
from szsdlc_ui_win95.server import make_server


@pytest.fixture
def served(project, code_root):
    registry = Registry()
    registry.add(project, code_root)
    server = make_server(registry, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def call(server, method, path, body=None, headers=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    hdrs = {"Host": host or f"localhost:{server.server_port}", **(headers or {})}
    data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
    if data is not None:
        hdrs.setdefault("Content-Type", "application/json")
    conn.request(method, path, body=data, headers=hdrs)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    ctype = resp.getheader("Content-Type") or ""
    return resp.status, resp, (json.loads(raw) if "json" in ctype else raw)


def token(server):
    return server.RequestHandlerClass.token


def test_meta_projects_and_project_routes(served):
    meta = call(served, "GET", "/api/meta")[2]
    assert meta["viewer"] == "szsdlc-ui-win95" and meta["defaults"] == {"scheme": "system"}
    projects = call(served, "GET", "/api/projects")[2]
    assert [p["id"] for p in projects] == ["proj"]
    assert call(served, "GET", "/api/p/proj/project")[2]["entity_count"] == 5
    assert call(served, "GET", "/api/p/proj/schema")[2]["source"] == "szsdlc"
    assert len(call(served, "GET", "/api/p/proj/entities")[2]) == 5
    assert call(served, "GET", "/api/p/proj/entities/wi-1")[2]["id"] == "WI-0001"
    assert call(served, "GET", "/api/p/proj/roadmaps")[2][0]["horizons"][0]["items"] == ["WI-0001"]
    assert call(served, "GET", "/api/p/proj/docs")[2][0]["generated"]
    assert call(served, "GET", "/api/p/proj/doc?root=code&path=docs/guide.md")[2]["exists"]


def test_not_found_routes_are_problems(served):
    for path in ("/api/p/nope/schema", "/api/p/proj/entities/WI-9999", "/api/p/proj/bogus", "/api/bogus"):
        status, resp, body = call(served, "GET", path)
        assert status == 404 and resp.getheader("Content-Type") == "application/problem+json", path


def test_foreign_host_is_refused(served):
    assert call(served, "GET", "/api/projects", host="evil.example")[0] == 403
    assert call(served, "POST", "/api/projects", {"store": "x"}, host="evil.example")[0] == 403


def test_index_carries_the_launch_token_and_strict_headers(served):
    status, resp, body = call(served, "GET", "/")
    assert status == 200 and f'content="{token(served)}"'.encode() in body
    assert "script-src 'self'" in resp.getheader("Content-Security-Policy")
    assert resp.getheader("X-Content-Type-Options") == "nosniff" and resp.getheader("Cache-Control") == "no-store"
    assert call(served, "GET", "/app.js")[0] == 200
    assert call(served, "GET", "/../pyproject.toml")[0] == 404
    assert call(served, "GET", "/missing.js")[0] == 404


def test_raw_never_serves_active_content_and_stays_contained(served, project):
    (project / "page.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    status, resp, _ = call(served, "GET", "/api/p/proj/raw?root=store&path=page.html")
    assert status == 200 and resp.getheader("Content-Type").startswith("text/plain")
    assert call(served, "GET", "/api/p/proj/raw?root=store&path=../../etc/passwd")[0] == 404
    assert call(served, "GET", "/api/p/proj/raw?root=store&path=nope.png")[0] == 404


def test_opening_a_project_needs_token_and_origin(served, tmp_path):
    from conftest import szsdlc
    other = tmp_path / "other"
    other.mkdir()
    szsdlc(other, "init")
    assert call(served, "POST", "/api/projects", {"store": str(other)})[0] == 403  # no token
    hdr = {"X-Viewer-Token": token(served)}
    assert call(served, "POST", "/api/projects", {"store": str(other)}, {**hdr, "Origin": "http://evil.example"})[0] == 403
    status, _, body = call(served, "POST", "/api/projects", {"store": str(tmp_path / "empty")}, hdr)
    assert status == 400 and "fix" in body
    assert call(served, "POST", "/api/projects", {}, hdr)[0] == 400
    assert call(served, "POST", "/api/projects", b"not json", hdr)[0] == 400
    assert call(served, "POST", "/api/elsewhere", {"store": "x"}, hdr)[0] == 404
    status, _, body = call(served, "POST", "/api/projects", {"store": str(other)}, {**hdr, "Origin": f"http://localhost:{served.server_port}"})
    assert status == 201 and body["id"] == "other"
    assert [p["id"] for p in call(served, "GET", "/api/projects")[2]] == ["proj", "other"]


def test_oversized_bodies_are_refused(served):
    big = json.dumps({"store": "x" * 70000})
    assert call(served, "POST", "/api/projects", big.encode(), {"X-Viewer-Token": token(served)})[0] == 413


def test_no_open_mode_refuses_opening(project):
    registry = Registry()
    registry.add(project)
    server = make_server(registry, "127.0.0.1", 0, allow_open=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status = call(server, "POST", "/api/projects", {"store": "/"}, {"X-Viewer-Token": token(server)})[0]
        assert status == 403
        assert call(server, "GET", "/api/meta")[2]["defaults"] == {"scheme": "system"}
    finally:
        server.shutdown()
        server.server_close()
