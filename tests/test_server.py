from __future__ import annotations

import http.client
import json
import threading

import pytest

from conftest import szsdlc
from szsdlc_ui_win95.registry import Registry
from szsdlc_ui_win95 import __version__
from szsdlc_ui_win95.server import CSP, make_server


@pytest.fixture
def served(project, asset_root):
    registry = Registry()
    registry.add(project, asset_root)
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
    return server.token


def test_meta_projects_and_project_routes(served):
    assert call(served, "GET", "/api/meta")[2]["viewer"] == "szsdlc-ui-win95"
    projects = call(served, "GET", "/api/projects")[2]
    assert [p["id"] for p in projects] == ["proj"]
    assert call(served, "GET", "/api/p/proj/project")[2]["entity_count"] == 5
    assert call(served, "GET", "/api/p/proj/schema")[2]["source"] == "szsdlc"
    assert len(call(served, "GET", "/api/p/proj/entities")[2]) == 5
    assert call(served, "GET", "/api/p/proj/entities/wi-1")[2]["id"] == "WI-0001"
    assert call(served, "GET", "/api/p/proj/roadmaps")[2][0]["horizons"][0]["items"] == ["WI-0001"]
    assert call(served, "GET", "/api/p/proj/docs")[2][0]["generated"]
    assert call(served, "GET", "/api/p/proj/doc?root=assets&path=docs/guide.md")[2]["exists"]


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
    status, resp, _ = call(served, "GET", "/api/p/proj/raw?root=sdlc&path=page.html")
    assert status == 200 and resp.getheader("Content-Type").startswith("text/plain")
    assert call(served, "GET", "/api/p/proj/raw?root=sdlc&path=../../etc/passwd")[0] == 404
    assert call(served, "GET", "/api/p/proj/raw?root=sdlc&path=nope.png")[0] == 404


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
    finally:
        server.shutdown()
        server.server_close()


def test_refresh_rereads_a_project_kept_here(served):
    """A project kept in a folder here has nothing to take: Refresh re-reads it."""
    auth = {"X-Viewer-Token": token(served)}
    status, _, body = call(served, "POST", "/api/p/proj/refresh", {}, auth)
    assert status == 200
    assert body["arrived"] is False and body["replaced"] is False and body["project"]["entity_count"] == 5


def test_refresh_is_guarded_like_opening(served):
    assert call(served, "POST", "/api/p/proj/refresh", {})[0] == 403  # no launch token
    assert call(served, "POST", "/api/p/proj/refresh", {},
                {"X-Viewer-Token": token(served), "Origin": "http://evil.example"})[0] == 403
    assert call(served, "POST", "/api/p/nope/refresh", {}, {"X-Viewer-Token": token(served)})[0] == 404


def test_a_refresh_that_changes_nothing_does_not_reload(project):
    """Background refreshes run every minute, so a no-op must not re-read the store (WI-0056)."""
    registry = Registry()
    pid = registry.add(project)
    p = registry.get(pid)
    model = p.store_model
    assert p.refresh_from_backend()["arrived"] is False
    assert p.store_model is model
    szsdlc(project, "new", "epic", "--title", "Edited on disk")  # a file changed: that is reloaded
    p.refresh_from_backend()
    assert p.store_model is not model and any(e.title == "Edited on disk" for e in p.store_model)


# ---------------------------------------------------------------- FastAPI (WI-0070)

def test_head_answers_with_headers_and_no_body(served):
    for path in ("/", "/api/meta", "/api/p/proj/project"):
        conn = http.client.HTTPConnection("127.0.0.1", served.server_port, timeout=10)
        conn.request("HEAD", path, headers={"Host": f"localhost:{served.server_port}"})
        resp = conn.getresponse()
        assert resp.status == 200 and resp.read() == b"", path
        assert int(resp.getheader("Content-Length")) > 0, path  # the GET's length, without its body
        assert resp.getheader("Content-Security-Policy") == CSP
        conn.close()


def test_every_response_is_hardened_and_names_the_viewer(served):
    for method, path, host in (("GET", "/api/meta", None), ("GET", "/api/bogus", None),
                               ("GET", "/missing.js", None), ("GET", "/api/meta", "evil.example"),
                               ("POST", "/api/projects", None)):
        _, resp, _ = call(served, method, path, {} if method == "POST" else None, host=host)
        assert resp.getheader("Server") == f"szsdlc-ui-win95/{__version__}", (method, path)
        assert resp.getheader("X-Content-Type-Options") == "nosniff"
        assert resp.getheader("Referrer-Policy") == "no-referrer"
        assert resp.getheader("Content-Security-Policy") == CSP
        assert "uvicorn" not in (resp.getheader("Server") or "")


def test_errors_are_problems_never_framework_shapes(served):
    auth = {"X-Viewer-Token": token(served)}
    status, resp, body = call(served, "POST", "/api/p/proj/refresh", {"replace": "yes"}, auth)
    assert status == 400 and resp.getheader("Content-Type") == "application/problem+json"
    assert body["title"] == "Not a valid request"
    status, resp, body = call(served, "POST", "/api/projects", {"location": 5}, auth)
    assert status == 400 and body["title"] == "Not a valid request"
    status, resp, _ = call(served, "GET", "/api/projects/")  # no trailing-slash redirect
    assert status == 404 and resp.getheader("Content-Type") == "application/problem+json"


def test_the_api_describes_itself(served):
    status, _, body = call(served, "GET", "/api/openapi.json")
    assert status == 200
    assert {"/api/meta", "/api/projects", "/api/p/{pid}/refresh"} <= set(body["paths"])
    opened = body["paths"]["/api/projects"]["post"]
    assert "location" in opened["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert opened["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith("OpenProjectResponse")
    assert call(served, "GET", "/docs")[0] == 404  # no Swagger page: it would load scripts from a CDN


def test_a_busy_port_is_refused_before_serving(served, project):
    with pytest.raises(OSError):
        make_server(Registry(), "127.0.0.1", served.server_port)


def test_http_server_is_no_longer_used():
    import ast
    from pathlib import Path

    import szsdlc_ui_win95

    for path in Path(szsdlc_ui_win95.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(n == "http.server" for n in names), path



def test_old_spellings_are_accepted_on_input(served, project, tmp_path):
    """WI-0069: `?root=store`/`?root=code` and an Open project body's `code_root` still work."""
    assert call(served, "GET", "/api/p/proj/doc?root=code&path=docs/guide.md")[2]["root"] == "assets"
    (project / "page.html").write_text("x", encoding="utf-8")
    assert call(served, "GET", "/api/p/proj/raw?root=store&path=page.html")[0] == 200
    other = tmp_path / "other"
    other.mkdir()
    szsdlc(other, "init")
    assets = tmp_path / "other-assets"
    assets.mkdir()
    status, _, body = call(served, "POST", "/api/projects", {"location": str(other), "code_root": str(assets)},
                           {"X-Viewer-Token": token(served)})
    assert status == 201 and body["asset_root"] == str(assets.resolve()) and "code_root" not in body
