"""Editing through szsdlc's own operations: the core, the service and every write route.

The viewer writes no file: each edit is one szsdlc operation, so these check
that its refusals arrive as data (stale, gate, bad input, unknown reference),
that the precondition really is passed, and that every route keeps the guards.
"""

from __future__ import annotations

import shutil
import threading

import pytest

from conftest import szsdlc
from szsdlc_ui_win95.project import Project
from szsdlc_ui_win95.registry import Registry
from szsdlc_ui_win95.server import make_server
from szsdlc_ui_win95.services import Forbidden, Invalid, NotFound, Rejected, Stale, ViewerService
from test_locations import git, remote  # noqa: F401  (remote is a fixture)
from test_server import call, token


def service_for(project, **kwargs) -> ViewerService:
    registry = Registry()
    registry.add(project)
    return ViewerService(registry, **kwargs)


def expect(service, ref: str) -> str:
    return service.entity("proj", ref)["hash"]


# -- the core and the service ----------------------------------------------------
def test_an_entity_carries_the_hash_a_write_passes(project):
    detail = Project(project).entity("WI-0002")
    assert len(detail["hash"]) >= 16


def test_set_moves_the_status_through_the_workflow(project):
    svc = service_for(project)
    out = svc.set("proj", "WI-0002", {"status": "groomed"}, expect=expect(svc, "WI-0002"))
    assert out["result"]["changes"][0] == {"field": "status", "before": "idea", "after": "groomed",
                                            "forced": None, "notes": []}
    assert out["entity"]["status"] == "groomed" and out["entity"]["hash"] != expect(svc, "WI-0001")
    assert svc.entity("proj", "WI-0002")["status"] == "groomed"  # the next read agrees
    assert set(out["findings"]) == {"errors", "warnings"}
    assert out["changes"] == {"unsent": False, "edits": [], "outside": False}  # kept in this folder: nothing to send


def test_a_scalar_field_is_set(project):
    svc = service_for(project)
    out = svc.set("proj", "WI-0002", {"opened": "2026-01-02"}, expect=expect(svc, "WI-0002"))
    assert out["entity"]["fields"]["opened"] == "2026-01-02"


def test_a_write_made_since_the_page_was_drawn_is_refused(project):
    svc = service_for(project)
    seen = expect(svc, "WI-0002")
    szsdlc(project, "set", "WI-0002", "status=groomed")  # an agent, behind the page's back
    with pytest.raises(Stale) as refused:
        svc.set("proj", "WI-0002", {"status": "dropped"}, expect=seen)
    assert refused.value.refusal["class"] == "stale_precondition"
    assert svc.entity("proj", "WI-0002")["status"] == "groomed"  # nothing overwritten


def test_a_gate_refuses_with_its_remedy(project):
    svc = service_for(project)
    for status in ("groomed", "ready", "planning"):
        svc.set("proj", "WI-0002", {"status": status}, expect=expect(svc, "WI-0002"))
    with pytest.raises(Rejected) as refused:  # planned needs plan.md, which WI-0002 lacks
        svc.set("proj", "WI-0002", {"status": "planned"}, expect=expect(svc, "WI-0002"))
    assert refused.value.refusal["class"] == "refused" and "plan.md" in refused.value.detail
    assert refused.value.fix


def test_a_forced_move_needs_a_reason_and_is_recorded(project):
    svc = service_for(project)
    with pytest.raises(Invalid):
        svc.set("proj", "WI-0002", {"status": "ready"}, expect=expect(svc, "WI-0002"), force=True)
    out = svc.set("proj", "WI-0002", {"status": "ready"}, expect=expect(svc, "WI-0002"), force=True,
                  reason="groomed elsewhere")  # idea → ready skips groomed
    assert out["result"]["changes"][0]["forced"] == "groomed elsewhere"
    assert out["entity"]["status"] == "ready"


def test_bad_fields_values_and_refs_are_refused(project):
    svc = service_for(project)
    h = expect(svc, "WI-0002")
    with pytest.raises(Invalid):
        svc.set("proj", "WI-0002", {"bogus": "x"}, expect=h)
    with pytest.raises(Invalid):
        svc.set("proj", "WI-0002", {"opened": "not a date"}, expect=h)
    with pytest.raises(Invalid):
        svc.set("proj", "WI-0002", {}, expect=h)
    with pytest.raises(Invalid):  # tags have their own operation (C3)
        svc.set("proj", "WI-0002", {"tags": "x"}, expect=h)
    with pytest.raises(NotFound):
        svc.set("proj", "WI-9999", {"status": "groomed"}, expect=h)
    with pytest.raises(NotFound):
        svc.set("nope", "WI-0002", {"status": "groomed"}, expect=h)


def test_tags_are_added_and_removed(project):
    svc = service_for(project)
    out = svc.tag("proj", "WI-0002", ["api", " graph "], expect=expect(svc, "WI-0002"))
    assert out["result"]["tags"] == ["api", "graph"]
    out = svc.tag("proj", "WI-0002", ["api"], expect=out["entity"]["hash"], add=False)
    assert out["entity"]["tags"] == ["graph"]
    with pytest.raises(Invalid):
        svc.tag("proj", "WI-0002", [" "], expect=out["entity"]["hash"])


def test_read_only_refuses_every_edit(project):
    svc = service_for(project, read_only=True)
    assert svc.meta()["readonly"] and svc.info("proj")["readonly"]
    with pytest.raises(Forbidden):
        svc.set("proj", "WI-0002", {"status": "groomed"}, expect=expect(svc, "WI-0002"))
    with pytest.raises(Forbidden):
        svc.tag("proj", "WI-0002", ["x"], expect="h")
    with pytest.raises(Forbidden):
        svc.send("proj")
    assert service_for(project).meta()["readonly"] is False


def test_findings_are_validate_as_data(project):
    svc = service_for(project)
    found = svc.findings("proj")
    assert set(found) == {"errors", "warnings", "total", "rows"} and found["total"] == len(found["rows"])
    szsdlc(project, "tag", "WI-0002", "lonely")
    assert any(r["ref"] for r in svc.findings("proj")["rows"])


def test_send_in_a_folder_project_only_renders(project):
    svc = service_for(project)
    svc.set("proj", "WI-0002", {"status": "groomed"}, expect=expect(svc, "WI-0002"))
    out = svc.send("proj")
    assert out["sent"] is False and out["arrived"] is False
    assert out["changes"] == {"unsent": False, "edits": [], "outside": False}


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_edits_to_a_clone_are_unsent_until_sent(remote, tmp_path):  # noqa: F811
    registry = Registry()
    pid = registry.add(remote.as_uri())
    svc = ViewerService(registry)
    assert svc.changes(pid) == {"unsent": False, "edits": [], "outside": False}
    h = svc.entity(pid, "WI-0002")["hash"]
    out = svc.set(pid, "WI-0002", {"status": "groomed"}, expect=h)
    assert out["changes"]["unsent"] is True
    assert [e["summary"] for e in out["changes"]["edits"]] == ["status idea → groomed"]
    out = svc.tag(pid, "WI-0002", ["api"], expect=out["entity"]["hash"])
    assert [e["summary"] for e in out["changes"]["edits"]][-1] == "tag +api"
    # Refresh asks before replacing them, as for any unsent change.
    with pytest.raises(Exception, match="unsent"):
        registry.get(pid).refresh_from_backend()
    sent = svc.send(pid)
    assert sent["sent"] is True and sent["changes"] == {"unsent": False, "edits": [], "outside": False}
    # It arrived where the project is kept: a fresh clone sees it.
    check = tmp_path / "check"
    git("clone", "-q", remote.as_uri(), str(check), cwd=tmp_path)
    assert "status: groomed" in next((check / "work-items").glob("WI-0002-*/entity.md")).read_text()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_unsent_changes_made_outside_the_viewer_are_named(remote, monkeypatch):  # noqa: F811
    registry = Registry()
    pid = registry.add(remote.as_uri())
    project = registry.get(pid)
    # An agent in a Claude Code turn: szsdlc commits, and sending waits for the turn's end.
    monkeypatch.setenv("CLAUDECODE", "1")
    szsdlc(project.sdlc_root, "tag", "WI-0002", "cli")
    assert ViewerService(registry).changes(pid) == {"unsent": True, "edits": [], "outside": True}


# -- over HTTP --------------------------------------------------------------------
@pytest.fixture
def served(project):
    registry = Registry()
    registry.add(project)
    server = make_server(registry, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def hash_of(server, ref="WI-0002") -> str:
    return call(server, "GET", f"/api/p/proj/entities/{ref}")[2]["hash"]


def test_every_write_route_keeps_the_guards(served):
    auth = {"X-Viewer-Token": token(served)}
    routes = [("/api/p/proj/entities/WI-0002/set", {"expect": "h", "values": {"status": "groomed"}}),
              ("/api/p/proj/entities/WI-0002/tag", {"expect": "h", "tags": ["x"]}),
              ("/api/p/proj/entities/WI-0002/untag", {"expect": "h", "tags": ["x"]}),
              ("/api/p/proj/send", {})]
    for path, body in routes:
        assert call(served, "POST", path, body)[0] == 403, path  # no launch token
        assert call(served, "POST", path, body, {**auth, "Origin": "http://evil.example"})[0] == 403, path
        assert call(served, "POST", path, b"x" * 70000, auth)[0] == 413, path
        assert call(served, "POST", path.replace("/proj/", "/nope/"), body, auth)[0] == 404, path
        if body:
            assert call(served, "POST", path, b"not json", auth)[0] == 400, path
            assert call(served, "POST", path, {k: v for k, v in body.items() if k != "expect"}, auth)[0] == 400, path
    assert call(served, "GET", "/api/p/proj/entities/WI-0002", host="evil.example")[0] == 403


def test_an_edit_answers_with_its_post_state(served):
    auth = {"X-Viewer-Token": token(served)}
    status, resp, body = call(served, "POST", "/api/p/proj/entities/WI-0002/set",
                              {"expect": hash_of(served), "values": {"status": "groomed"}}, auth)
    assert status == 200 and resp.getheader("Content-Type").startswith("application/json")
    assert body["entity"]["status"] == "groomed" and body["result"]["id"] == "WI-0002"
    assert body["entity"]["hash"] == hash_of(served)
    status, _, body = call(served, "POST", "/api/p/proj/entities/WI-0002/tag",
                           {"expect": hash_of(served), "tags": ["api"]}, auth)
    assert status == 200 and "api" in body["entity"]["tags"]
    status, _, body = call(served, "POST", "/api/p/proj/entities/WI-0002/untag",
                           {"expect": hash_of(served), "tags": ["api"]}, auth)
    assert status == 200 and "api" not in body["entity"]["tags"]
    status, _, body = call(served, "POST", "/api/p/proj/send", {}, auth)
    assert status == 200 and body["sent"] is False
    assert call(served, "GET", "/api/p/proj/changes")[2] == {"unsent": False, "edits": [], "outside": False}
    found = call(served, "GET", "/api/p/proj/findings")[2]
    assert {"errors", "warnings", "total", "rows"} <= set(found)


def test_a_bool_or_number_is_sent_as_szsdlc_reads_it():
    from szsdlc_ui_win95.web.map_requests import set_args
    args = set_args({"expect": "h", "values": {"a": True, "b": False, "c": 3, "d": "x"}})
    assert args["values"] == {"a": "true", "b": "false", "c": "3", "d": "x"}
    assert args["force"] is False and args["reason"] is None


def test_refusals_are_problems_with_the_refusal_as_data(served, project):
    auth = {"X-Viewer-Token": token(served)}
    seen = hash_of(served)
    szsdlc(project, "set", "WI-0002", "status=groomed")  # behind the page's back
    status, resp, body = call(served, "POST", "/api/p/proj/entities/WI-0002/set",
                              {"expect": seen, "values": {"status": "dropped"}}, auth)
    assert status == 409 and resp.getheader("Content-Type") == "application/problem+json"
    assert body["title"] == "Changed on disk" and body["refusal"]["class"] == "stale_precondition"
    assert body["refusal"]["fix"] == {"op": "show", "params": {"ref": "WI-0002"}} or body["refusal"]["fix"]["op"] == "show"
    status, _, body = call(served, "POST", "/api/p/proj/entities/WI-0002/set",
                           {"expect": hash_of(served), "values": {"status": "planned"}}, auth)
    assert status == 422 and body["refusal"]["class"] == "refused" and body["fix"]
    status, _, body = call(served, "POST", "/api/p/proj/entities/WI-0002/set",
                           {"expect": hash_of(served), "values": {"bogus": "x"}}, auth)
    assert status == 400 and body["refusal"]["class"] == "bad_input"
    status, _, body = call(served, "POST", "/api/p/proj/entities/WI-9999/tag",
                           {"expect": "h", "tags": ["x"]}, auth)
    assert status == 404 and body["refusal"]["class"] == "unknown_reference"
    # A problem the viewer raises itself carries no refusal.
    assert "refusal" not in call(served, "POST", "/api/p/proj/entities/WI-0002/tag",
                                 {"expect": "h", "tags": []}, auth)[2]


def test_read_only_answers_403_to_every_edit(project):
    registry = Registry()
    registry.add(project)
    server = make_server(registry, "127.0.0.1", 0, read_only=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        auth = {"X-Viewer-Token": token(server)}
        assert call(server, "GET", "/api/meta")[2]["readonly"] is True
        for path in ("/api/p/proj/entities/WI-0002/set", "/api/p/proj/entities/WI-0002/tag", "/api/p/proj/send"):
            assert call(server, "POST", path, {}, auth)[0] == 403, path
        assert call(server, "POST", "/api/p/proj/refresh", {}, auth)[0] == 200  # changes no record
    finally:
        server.shutdown()
        server.server_close()


def test_the_api_description_names_the_edit_routes(served):
    paths = call(served, "GET", "/api/openapi.json")[2]["paths"]
    for path in ("/api/p/{pid}/entities/{ref}/set", "/api/p/{pid}/entities/{ref}/tag",
                 "/api/p/{pid}/entities/{ref}/untag", "/api/p/{pid}/send", "/api/p/{pid}/changes",
                 "/api/p/{pid}/findings"):
        assert path in paths, path


# -- capture (WI-0075) ------------------------------------------------------------
def test_capture_makes_an_idea_and_logs_it(project):
    svc = service_for(project)
    out = svc.capture("proj", "Dark mode for the board\nWith a toggle in the toolbar.")
    new = out["result"]["id"]
    assert out["entity"]["id"] == new and svc.entity("proj", new)["body"].startswith("Dark mode")
    assert out["changes"] == {"unsent": False, "edits": [], "outside": False}  # a folder project sends nothing
    log = registry_project(svc).edits.log()
    assert [(e.op, e.summary) for e in log] == [("capture", "captured: Dark mode for the board")]


def registry_project(svc):
    return svc.registry.get("proj")


def test_an_empty_capture_is_szsdlcs_refusal(project):
    svc = service_for(project)
    with pytest.raises(Invalid) as refused:
        svc.capture("proj", "   \n  ")
    assert refused.value.refusal["class"] == "bad_input" and "nothing to capture" in refused.value.detail


def test_two_intake_types_need_a_type(project):
    config = project / ".szsdlc" / "config.yml"
    config.write_text(config.read_text(encoding="utf-8") + "entity_types: {spike: {intake: true}}\n",
                      encoding="utf-8")
    svc = service_for(project)
    with pytest.raises(Invalid) as refused:
        svc.capture("proj", "which one?")
    assert "--type is required" in refused.value.detail
    out = svc.capture("proj", "a spike thought", type_name="spike")
    assert out["entity"]["type"] == "SPK"


def test_capture_is_refused_read_only(project):
    with pytest.raises(Forbidden):
        service_for(project, read_only=True).capture("proj", "nope")


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_capture_to_a_clone_is_unsent_until_sent(remote):  # noqa: F811
    registry = Registry()
    pid = registry.add(remote.as_uri())
    svc = ViewerService(registry)
    out = svc.capture(pid, "Captured in the viewer")
    assert out["changes"]["unsent"] and out["changes"]["edits"][0]["summary"] == "captured: Captured in the viewer"
    assert svc.send(pid)["sent"] is True


def test_the_capture_route_keeps_the_guards_and_maps_refusals(served):
    auth = {"X-Viewer-Token": token(served)}
    path = "/api/p/proj/capture"
    assert call(served, "POST", path, {"text": "x"})[0] == 403  # no launch token
    assert call(served, "POST", path, {"text": "x"}, {**auth, "Origin": "http://evil.example"})[0] == 403
    assert call(served, "POST", path, b"x" * 70000, auth)[0] == 413
    assert call(served, "POST", "/api/p/nope/capture", {"text": "x"}, auth)[0] == 404
    assert call(served, "POST", path, b"not json", auth)[0] == 400
    assert call(served, "POST", path, {}, auth)[0] == 400  # text is required
    status, _, body = call(served, "POST", path, {"text": "  "}, auth)
    assert status == 400 and body["refusal"]["class"] == "bad_input"
    status, _, body = call(served, "POST", path, {"text": "Served idea"}, auth)
    assert status == 200 and body["entity"]["id"] == body["result"]["id"]
    assert "/api/p/{pid}/capture" in call(served, "GET", "/api/openapi.json")[2]["paths"]
