"""Fixture projects are built with szsdlc's own CLI, so they are always valid ones.

Every test runs with szsdlc's per-user state (settings and the store registry)
redirected into a temporary directory, so nothing on the machine leaks in.
"""

from __future__ import annotations

import io
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
from szsdlc import cli as sz_cli


@pytest.fixture(autouse=True)
def isolated_szsdlc(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("claude-config")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    for key in list(os.environ):
        if key.startswith("SZSDLC_"):
            monkeypatch.delenv(key)
    return home


def szsdlc(project: Path, *args: str) -> str:
    """Run one szsdlc command in `project`; fail the test if szsdlc refuses."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = sz_cli.main(["-C", str(project), *args])
    assert code == 0, f"szsdlc {' '.join(args)} exited {code}: {err.getvalue()}"
    return out.getvalue()


PLAN = """# Plan

- [x] **Step 1:** Draw the tree
- [x] **Step 2:** Nest by the parent relation
- [ ] **Step 3:** Make the pane resizable
"""

DESIGN = """# Design

Reads [the guide](../../docs/guide.md) and `docs/guide.md`, and the
[relation model](../../requirements/REQ-0001-every-view-follows-traits.md).
See https://example.org/spec for background.
"""


@pytest.fixture
def code_root(tmp_path) -> Path:
    """The repository a project describes, holding an out-of-tree document."""
    root = tmp_path / "code"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "guide.md").write_text("# Guide\n\nOut of tree.\n", encoding="utf-8")
    return root


@pytest.fixture
def project(tmp_path) -> Path:
    """A small, valid project using szsdlc's default types."""
    root = tmp_path / "proj"
    root.mkdir()
    szsdlc(root, "init")
    szsdlc(root, "new", "epic", "--title", "Ship the viewer")
    szsdlc(root, "new", "requirement", "--title", "Every view follows traits")
    szsdlc(root, "new", "work_item", "--title", "Render the tree")
    szsdlc(root, "new", "work_item", "--title", "Draw the graph")
    szsdlc(root, "link", "WI-0001", "parent", "EPIC-0001")
    szsdlc(root, "link", "WI-0002", "parent", "EPIC-0001")
    szsdlc(root, "link", "WI-0001", "implements", "REQ-0001")
    szsdlc(root, "link", "WI-0002", "depends_on", "WI-0001")
    szsdlc(root, "tag", "WI-0001", "ui")
    for status in ("reviewed", "approved"):
        szsdlc(root, "set", "REQ-0001", f"status={status}")
    home = next((root / "work-items").glob("WI-0001-*"))
    (home / "design.md").write_text(DESIGN, encoding="utf-8")
    (home / "plan.md").write_text(PLAN, encoding="utf-8")
    for status in ("groomed", "ready"):
        szsdlc(root, "set", "WI-0001", f"status={status}")
    szsdlc(root, "schedule", "WI-0001", "--horizon", "now")
    szsdlc(root, "schedule", "EPIC-0001", "--horizon", "next")
    szsdlc(root, "capture", "maybe a dark scheme")
    szsdlc(root, "render")
    return root
