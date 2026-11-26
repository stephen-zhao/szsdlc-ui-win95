"""The services layer, driven directly: no HTTP, no framework."""

from __future__ import annotations

import pytest

from szsdlc_ui_win95.registry import Registry
from szsdlc_ui_win95.services import Conflict, Forbidden, Invalid, NotFound, ViewerService


@pytest.fixture
def service(project, asset_root):
    registry = Registry()
    registry.add(project, asset_root)
    return ViewerService(registry)


def test_reads(service):
    assert service.meta()["viewer"] == "szsdlc-ui-win95"
    assert [p["id"] for p in service.projects()] == ["proj"]
    assert service.info("proj")["entity_count"] == 5
    assert service.entity("proj", "wi-1")["id"] == "WI-0001"
    assert service.doc("proj", "assets", "docs/guide.md")["exists"]


def test_refusals_are_typed_not_status_codes(service, tmp_path):
    with pytest.raises(NotFound, match="no project `nope`"):
        service.info("nope")
    with pytest.raises(NotFound):
        service.entity("proj", "WI-9999")
    with pytest.raises(NotFound):
        service.refresh("nope")
    with pytest.raises(Invalid) as err:
        service.open_project("  ")
    assert err.value.title == "No location given"
    with pytest.raises(Invalid) as err:
        service.open_project(str(tmp_path / "empty"))
    assert err.value.fix


def test_no_open_is_refused_before_anything_is_read(project):
    service = ViewerService(Registry(), allow_open=False)
    with pytest.raises(Forbidden, match="--no-open"):
        service.ensure_can_open()
    with pytest.raises(Forbidden):
        service.open_project(str(project))


def test_raw_is_contained_and_never_active(service, project):
    (project / "page.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    assert service.raw("proj", "sdlc", "page.html").content_type.startswith("text/plain")
    assert service.raw("proj", "sdlc", "../../etc/passwd") is None


def test_refresh_reports_a_conflict_as_such(service, monkeypatch):
    from szsdlc_ui_win95.errors import UnsentChanges

    def refuse(**kwargs):
        raise UnsentChanges("2 unsent changes")

    monkeypatch.setattr(service.registry.get("proj"), "refresh_from_backend", refuse)
    with pytest.raises(Conflict, match="unsent"):
        service.refresh("proj")
