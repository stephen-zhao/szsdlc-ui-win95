"""Opening a project through any backend, against real git.

A bare repository on disk stands in for a remote: `file://` is one of the
transports szsdlc's git backend allows, so these exercise the same clone,
verify and sync paths a GitHub remote would.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import szsdlc
from szsdlc_ui_win95 import locations
from szsdlc_ui_win95.project import Project, ProjectError
from szsdlc_ui_win95.registry import Registry

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def git(*args, cwd: Path):
    subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.org",
                    "-c", "init.defaultBranch=main", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def remote(project, tmp_path) -> Path:
    """A bare repository holding the fixture project, as a remote would."""
    git("init", "-q", cwd=project)
    git("checkout", "-q", "-B", "main", cwd=project)
    git("add", "-A", cwd=project)
    git("commit", "-q", "-m", "a szsdlc project", cwd=project)
    bare = tmp_path / "remote.git"
    git("clone", "-q", "--bare", str(project), str(bare), cwd=tmp_path)
    return bare


def push_new_epic(bare: Path, tmp_path: Path, title: str) -> None:
    """Someone else adds an entity and pushes it."""
    work = tmp_path / f"work-{title.split()[0].lower()}"
    git("clone", "-q", bare.as_uri(), str(work), cwd=tmp_path)
    szsdlc(work, "new", "epic", "--title", title)
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", f"add {title}", cwd=work)
    git("push", "-q", "origin", "main", cwd=work)


def clones(home: Path) -> list[Path]:
    root = home / "szsdlc" / "git"
    return sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []


def test_open_by_repository_url_clones_through_szsdlc(remote, isolated_szsdlc):
    p = Project(remote.as_uri())
    assert p.remote and p.relocated and p.asset_root is None
    assert p.sdlc_root.parent == isolated_szsdlc / "szsdlc" / "git"  # szsdlc's own clone location
    assert len(p.store_model) == 5
    info = p.info()
    assert info["backend"]["kind"] == "git" and info["location"] == remote.as_uri()
    assert info["name"] == "proj" and info["update_warning"] is None


def test_reopening_reuses_the_clone(remote, isolated_szsdlc):
    first = Project(remote.as_uri())
    again = Project(remote.as_uri())
    assert again.sdlc_root == first.sdlc_root and len(clones(isolated_szsdlc)) == 1


def test_a_clean_clone_is_brought_up_to_date_when_opened(remote, tmp_path):
    Project(remote.as_uri())
    push_new_epic(remote, tmp_path, "Arrived later")
    p = Project(remote.as_uri())
    assert p.update_warning is None
    assert any(e.title == "Arrived later" for e in p.store_model)


def test_a_clone_with_unsent_work_is_left_alone(remote, tmp_path):
    first = Project(remote.as_uri())
    epic = next((first.sdlc_root / "epics").glob("EPIC-0001-*"))
    epic.write_text(epic.read_text().replace("Ship the viewer", "Edited here, not sent"), encoding="utf-8")
    push_new_epic(remote, tmp_path, "Arrived later")
    p = Project(remote.as_uri())
    assert "unsent changes" in p.update_warning
    assert p.entity("EPIC-0001")["title"] == "Edited here, not sent"
    assert not any(e.title == "Arrived later" for e in p.store_model)


def test_an_unreachable_remote_still_opens_the_local_copy(remote):
    Project(remote.as_uri())
    shutil.rmtree(remote)
    p = Project(remote.as_uri())
    assert p.update_warning and p.update_warning.startswith("Could not update")
    assert len(p.store_model) == 5


def test_a_code_folder_whose_settings_select_git(remote, tmp_path, isolated_szsdlc):
    code = tmp_path / "app"
    (code / ".claude").mkdir(parents=True)
    (code / ".claude" / "settings.json").write_text(json.dumps({"env": {
        "SZSDLC_BACKEND": "git", "SZSDLC_BACKEND_GIT_URL": remote.as_uri(), "SZSDLC_BACKEND_GIT_BRANCH": "main"}}))
    p = Project(code)
    assert not p.remote and p.relocated
    assert p.asset_root == code.resolve() and p.sdlc_root.parent == isolated_szsdlc / "szsdlc" / "git"
    assert len(p.store_model) == 5 and p.info()["location"] == str(code.resolve())


def test_branch_after_hash(remote, project, tmp_path):
    git("checkout", "-q", "-b", "other", cwd=project)
    szsdlc(project, "new", "epic", "--title", "Only on other")
    git("add", "-A", cwd=project)
    git("commit", "-q", "-m", "other branch", cwd=project)
    git("push", "-q", str(remote), "other", cwd=project)
    p = Project(f"{remote.as_uri()}#other")
    assert any(e.title == "Only on other" for e in p.store_model)


def test_refusals_name_the_problem(tmp_path, isolated_szsdlc):
    with pytest.raises(ProjectError, match="not a folder on this computer"):
        Project(tmp_path / "nowhere")
    with pytest.raises(ProjectError, match="not a folder on this computer"):
        Project("ext::sh -c touch% /tmp/x")  # a git remote helper is never treated as a remote
    with pytest.raises(ProjectError, match="could not clone"):
        Project((tmp_path / "missing.git").as_uri())
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "README.md").write_text("# not a project\n")
    git("init", "-q", cwd=plain)
    git("add", "-A", cwd=plain)
    git("commit", "-q", "-m", "plain", cwd=plain)
    with pytest.raises(ProjectError, match="holds no szsdlc project"):
        Project(plain.as_uri())
    with pytest.raises(ProjectError, match="No location given"):
        Project("   ")


def test_registry_dedupes_and_persists_remote_projects(remote, tmp_path):
    path = tmp_path / "viewer.yml"
    r = Registry(projects_file=path)
    pid = r.add(remote.as_uri(), persist=True)
    assert r.add(remote.as_uri()) == pid
    assert remote.as_uri() in path.read_text()
    again = Registry(projects_file=path)
    again.load()
    assert list(again.projects) == [pid] and again.get(pid).remote
    summary = again.summary(pid, again.get(pid), public=True)
    assert summary["remote"] and summary["location"] == remote.as_uri()


def test_location_helpers(tmp_path):
    assert locations.is_remote("git@github.com:org/repo.git")
    assert locations.is_remote("https://github.com/org/repo")
    assert locations.is_remote("ssh://git@host/org/repo.git#main")
    assert not locations.is_remote(str(tmp_path)) and not locations.is_remote("C:\\code\\app")
    assert not locations.is_remote("ext::sh -c x") and not locations.is_remote("relative/folder")
    assert locations.display("https://user:token@host/org/repo.git?x=1") == "https://***@host/org/repo.git"
    assert locations.store_name(Path("/x/szsdlc-szsdlc-0123456789")) == "szsdlc-szsdlc"
    assert locations.store_name(Path("/x/plain")) == "plain"


def test_open_project_over_http_takes_a_repository_url(remote):
    import threading
    from test_server import call, token
    from szsdlc_ui_win95.server import make_server
    registry = Registry()
    server = make_server(registry, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, _, body = call(server, "POST", "/api/projects", {"location": remote.as_uri()}, {"X-Viewer-Token": token(server)})
        assert status == 201 and body["remote"] and body["entity_count"] == 5
    finally:
        server.shutdown()
        server.server_close()


# -- Refresh (WI-0048) ------------------------------------------------------


def test_refresh_takes_what_arrived_and_sends_nothing(remote, tmp_path):
    p = Project(remote.as_uri())
    push_new_epic(remote, tmp_path, "Arrived later")
    head = subprocess.run(["git", "--git-dir", str(remote), "rev-parse", "main"],
                          capture_output=True, text=True, check=True).stdout
    result = p.refresh_from_backend()
    assert result == {"arrived": True, "replaced": False, "note": None}
    assert any(e.title == "Arrived later" for e in p.store_model)  # reloaded in place
    assert subprocess.run(["git", "--git-dir", str(remote), "rev-parse", "main"],
                          capture_output=True, text=True, check=True).stdout == head
    assert p.refresh_from_backend()["arrived"] is False


def test_refresh_asks_before_replacing_unsent_changes(remote, tmp_path):
    from szsdlc_ui_win95.errors import UnsentChanges

    p = Project(remote.as_uri())
    epic = next((p.sdlc_root / "epics").glob("EPIC-0001-*"))
    epic.write_text(epic.read_text().replace("Ship the viewer", "Edited here, not sent"), encoding="utf-8")
    push_new_epic(remote, tmp_path, "Arrived later")

    with pytest.raises(UnsentChanges, match="unsent changes"):
        p.refresh_from_backend()
    assert "Edited here, not sent" in epic.read_text()  # untouched

    result = p.refresh_from_backend(replace=True)
    assert result["arrived"] and result["replaced"]
    assert result["note"].startswith("kept at refs/szsdlc/replaced/")
    assert "Edited here, not sent" not in epic.read_text()
    assert any(e.title == "Arrived later" for e in p.store_model)


def test_refresh_from_an_unreachable_remote_replaces_nothing(remote):
    p = Project(remote.as_uri())
    shutil.rmtree(remote)
    with pytest.raises(ProjectError, match="Could not refresh"):
        p.refresh_from_backend(replace=True)
    assert len(p.store_model) == 5


def test_refresh_over_http_asks_then_replaces(remote, tmp_path):
    import threading
    from test_server import call, token
    from szsdlc_ui_win95.server import make_server
    registry = Registry()
    pid = registry.add(remote.as_uri())
    server = make_server(registry, "127.0.0.1", 0, allow_open=False)  # refreshing opens nothing
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        store = registry.get(pid).sdlc_root
        (store / "scratch.md").write_text("unsent", encoding="utf-8")
        auth = {"X-Viewer-Token": token(server)}
        status, _, body = call(server, "POST", f"/api/p/{pid}/refresh", {}, auth)
        assert status == 409 and "unsent changes" in body["detail"]
        status, _, body = call(server, "POST", f"/api/p/{pid}/refresh", {"replace": True}, auth)
        assert status == 200 and body["replaced"] and body["project"]["id"] == pid
        assert not (store / "scratch.md").exists()
    finally:
        server.shutdown()
        server.server_close()
