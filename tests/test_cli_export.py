from __future__ import annotations

import json
import re

import pytest

from szsdlc_ui_win95 import cli, export
from szsdlc_ui_win95.registry import Registry


def test_export_is_self_contained_and_hides_local_paths(project, code_root, tmp_path):
    registry = Registry()
    registry.add(project, code_root)
    html = export.render(registry)
    assert "window.SZ_SNAPSHOT=" in html and "<!doctype html>" in html.lower()
    assert 'src="vendor/' not in html and 'href="win95.css"' not in html
    assert '<meta name="viewer-token"' not in html  # a snapshot has no server to hold a token for
    assert str(tmp_path) not in html
    snap = json.loads(re.search(r"window\.SZ_SNAPSHOT=(\{.*?\});</script>", html, re.S).group(1).replace("<\\/", "</"))
    assert snap["meta"]["viewer"] == "szsdlc-ui-win95" and snap["projects"][0]["store"] == "proj"
    assert "WI-0001" in snap["data"]["proj"]["details"]
    fragment = export.render(registry, fragment=True)
    head = fragment.lstrip()[:200].lower()  # the vendored libraries mention "<html" as strings; look at the top
    assert head.startswith("<title>") and "<!doctype" not in head and "<html" not in head


def test_cli_export_and_errors(project, tmp_path, capsys):
    out = tmp_path / "snap.html"
    assert cli.main([str(project), "--export", str(out)]) == 0
    assert out.read_text(encoding="utf-8").count("SZ_SNAPSHOT") >= 1
    assert cli.main([str(tmp_path / "nothing"), "--export", str(out)]) == 2
    assert "skipped" in capsys.readouterr().err


def test_cli_version_and_project_syntax(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert "szsdlc" in capsys.readouterr().out
    store, code = cli.parse_project("a/b::c/d")
    assert (str(store), str(code)) == ("a/b", "c/d")
    assert cli.parse_project("a/b")[1] is None


def test_cli_reports_a_port_in_use(project, capsys):
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    try:
        assert cli.main([str(project), "--port", str(sock.getsockname()[1])]) == 1
    finally:
        sock.close()
    assert "cannot listen" in capsys.readouterr().err
