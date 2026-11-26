"""WI-0065: which projects a launch opens. Every registered store by default,
plus the current project; `--no-registered` restores the old behaviour; never
for `--export`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from szsdlc_ui_win95 import cli

from conftest import szsdlc


@pytest.fixture
def other(tmp_path) -> Path:
    """A second project, kept elsewhere: the one szsdlc's registry knows about."""
    root = tmp_path / "elsewhere"
    root.mkdir()
    szsdlc(root, "init", "--name", "elsewhere")
    szsdlc(root, "new", "epic", "--title", "Kept elsewhere")
    return root


@pytest.fixture
def registered(other, isolated_szsdlc):
    path = isolated_szsdlc / "szsdlc" / "stores.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({str(other): {"type": "workdir", "state": {}}}), encoding="utf-8")
    return other


def opened(*argv: str) -> set[str]:
    registry = cli.open_projects(cli.build_parser().parse_args(list(argv)))
    return {p.sdlc_root.name for p in registry.projects.values()}


def test_a_bare_launch_opens_every_registered_store_and_the_current_project(
        project, registered, monkeypatch):
    monkeypatch.chdir(project)
    assert opened() == {"proj", "elsewhere"}


def test_a_current_directory_outside_any_project_is_skipped_quietly(
        registered, tmp_path, monkeypatch, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    assert opened() == {"elsewhere"}
    assert capsys.readouterr().err == ""


def test_with_nothing_else_open_a_non_project_still_says_why(tmp_path, monkeypatch, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    assert opened() == set()
    assert "skipped ." in capsys.readouterr().err


def test_a_named_location_that_fails_still_warns(registered, tmp_path, capsys):
    assert opened(str(tmp_path / "nothing")) == {"elsewhere"}
    assert "skipped" in capsys.readouterr().err


def test_no_registered_restores_the_old_behaviour(project, registered, monkeypatch):
    monkeypatch.chdir(project)
    assert opened("--no-registered") == {"proj"}


def test_the_old_flag_still_parses(project, registered, monkeypatch):
    monkeypatch.chdir(project)
    assert opened("--registered") == {"proj", "elsewhere"}


def test_named_projects_open_beside_the_registered_ones(project, registered):
    assert opened(str(project)) == {"proj", "elsewhere"}


def test_export_contains_only_what_the_command_line_names(project, registered, tmp_path, capsys):
    out = tmp_path / "snap.html"
    assert opened(str(project), "--export", str(out)) == {"proj"}
    assert cli.main([str(project), "--export", str(out)]) == 0
    assert "1 project(s)" in capsys.readouterr().out
