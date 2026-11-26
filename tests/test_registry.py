from __future__ import annotations

import json

import pytest

from szsdlc_ui_win95.project import ProjectError
from szsdlc_ui_win95.registry import Registry, slug


def test_add_is_idempotent_and_finds_the_project_from_inside(project):
    r = Registry()
    pid = r.add(project)
    assert pid == "proj"
    assert r.add(project) == pid
    assert r.add(project / "epics") == pid
    assert len(r.projects) == 1


def test_ids_are_unique_and_url_safe(project, tmp_path):
    import shutil
    other = tmp_path / "copy" / "proj"
    shutil.copytree(project, other)
    r = Registry()
    assert r.add(project) == "proj" and r.add(other) == "proj-2"
    assert slug("Research Lab (sample)!") == "research-lab-sample" and slug("***") == "project"


def test_refuses_what_is_not_a_project(tmp_path):
    r = Registry()
    with pytest.raises(ProjectError):
        r.add(tmp_path)
    with pytest.raises(ProjectError, match="not a directory"):
        r.add(tmp_path, asset_root=tmp_path / "missing")


def test_summary_public_form_drops_local_paths(project, asset_root):
    r = Registry()
    pid = r.add(project, asset_root)
    full, public = r.summary(pid, r.get(pid)), r.summary(pid, r.get(pid), public=True)
    assert full["sdlc_root"] == str(project.resolve()) and public["sdlc_root"] == "proj"
    assert public["asset_root"] == "assets" and full["entity_count"] == 5 and full["type_count"] == 6


def test_projects_file_round_trip(project, asset_root, tmp_path):
    path = tmp_path / "viewer.yml"
    r = Registry(projects_file=path)
    r.add(project, asset_root, persist=True)
    again = Registry(projects_file=path)
    again.load()
    assert list(again.projects) == ["proj"] and again.get("proj").asset_root == asset_root.resolve()
    path.write_text("- store: /nowhere/at/all\n- {}\n", encoding="utf-8")
    broken = Registry(projects_file=path)
    broken.load()  # bad entries are skipped, not fatal
    assert broken.projects == {}


def test_registered_stores_come_from_szsdlc_registry(project, isolated_szsdlc, tmp_path):
    registry_file = isolated_szsdlc / "szsdlc" / "stores.json"
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(json.dumps({str(project): {"type": "workdir", "state": {}},
                                         str(tmp_path / "gone"): {"type": "workdir", "state": {}}}), encoding="utf-8")
    r = Registry()
    r.add_registered()
    assert list(r.projects) == ["proj"]



def test_a_projects_file_written_with_code_root_still_loads(project, asset_root, tmp_path):
    """WI-0069: the file is written with `asset_root`; one with the old `code_root` still reads."""
    path = tmp_path / "projects.yml"
    path.write_text(f"- location: {project}\n  code_root: {asset_root}\n", encoding="utf-8")
    r = Registry(projects_file=path)
    r.load()
    assert r.get("proj").asset_root == asset_root.resolve()
    r.save()
    assert "asset_root:" in path.read_text(encoding="utf-8") and "code_root" not in path.read_text(encoding="utf-8")
