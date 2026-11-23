"""Session configuration (WI-0041): read once, read-only, never written; malformed refuses to start."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

import pytest

from szsdlc_ui_win95 import cli, config


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_no_file_means_defaults():
    s = config.load()
    assert s == config.Settings() and s.source is None


def test_every_key_is_read(isolated_config):
    write(isolated_config, 'host = "0.0.0.0"\nport = 9001\nopen_project = false\nexclude = ["vendor"]\n'
                           '[ui]\nscheme = "dark"\n')
    s = config.load()
    assert (s.host, s.port, s.open_project, s.exclude, s.scheme) == ("0.0.0.0", 9001, False, ("vendor",), "dark")
    assert s.source == isolated_config


def test_an_explicit_path_wins_and_must_exist(tmp_path):
    other = write(tmp_path / "elsewhere.toml", "port = 9100\n")
    assert config.load(other).port == 9100
    with pytest.raises(config.ConfigError, match=r"missing\.toml: no such file\.\nFix: create it"):
        config.load(tmp_path / "missing.toml")


@pytest.mark.parametrize("text, key, fix", [
    ('port = "80"\n', "port", "port = 8095"),
    ("port = true\n", "port", "port = 8095"),
    ("port = 70000\n", "port", "port = 8095"),
    ('host = ""\n', "host", 'host = "127.0.0.1"'),
    ("open_project = 1\n", "open_project", "open_project = false"),
    ('exclude = "vendor"\n', "exclude", "exclude = ["),
    ('[ui]\nscheme = "blue"\n', "ui.scheme", 'ui.scheme = "dark"'),
    ('ui = "dark"\n', "ui", "[ui] section"),
    ("colour = 1\n", "colour", "the settings are host, port"),
    ('[ui]\nfont = "x"\n', "ui.font", "the settings are"),
])
def test_a_malformed_value_names_the_file_the_key_and_the_fix(isolated_config, text, key, fix):
    write(isolated_config, text)
    with pytest.raises(config.ConfigError) as err:
        config.load()
    message = str(err.value)
    assert message.startswith(f"{isolated_config}: {key}: ") and "\nFix: " in message and fix in message


def test_invalid_toml_names_the_file_and_line(isolated_config):
    write(isolated_config, "port = 8095\nhost = \n")
    with pytest.raises(config.ConfigError, match=r"is not valid TOML \(.*line 2.*\)\.\nFix: "):
        config.load()


@pytest.mark.parametrize("platform, env, expected", [
    ("linux", {"XDG_CONFIG_HOME": "/x/cfg"}, "/x/cfg/szsdlc-ui-win95"),
    ("linux", {}, "/home/u/.config/szsdlc-ui-win95"),
    ("darwin", {"XDG_CONFIG_HOME": "/ignored"}, "/home/u/Library/Application Support/szsdlc-ui-win95"),
    ("win32", {"APPDATA": "/x/Roaming"}, "/x/Roaming/szsdlc-ui-win95"),
    ("win32", {}, "/home/u/AppData/Roaming/szsdlc-ui-win95"),
])
def test_the_per_user_directory_follows_the_platform(platform, env, expected):
    assert config.default_dir(env, platform, Path("/home/u")) == Path(expected)


class FakeServer:
    server_port = 4242

    def serve_forever(self):
        raise KeyboardInterrupt

    def server_close(self):
        pass


@pytest.fixture
def started(monkeypatch):
    """Run `cli.main` up to serving, recording what the server was given."""
    seen = {}

    def fake(registry, host, port, **kw):
        seen.update(registry=registry, host=host, port=port, **kw)
        return FakeServer()

    monkeypatch.setattr(cli, "make_server", fake)
    return seen


def test_the_file_configures_the_server(project, isolated_config, started, capsys):
    write(isolated_config, 'host = "0.0.0.0"\nport = 9001\nopen_project = false\nexclude = ["vendor"]\n'
                           '[ui]\nscheme = "dark"\n')
    assert cli.main([str(project)]) == 0
    assert (started["host"], started["port"], started["allow_open"], started["scheme"]) == ("0.0.0.0", 9001, False, "dark")
    assert started["registry"].excludes == ("vendor",)
    assert f"config: {isolated_config}" in capsys.readouterr().out


def test_flags_beat_the_file(project, isolated_config, started):
    write(isolated_config, 'host = "0.0.0.0"\nport = 9001\nexclude = ["vendor"]\n')
    assert cli.main([str(project), "--host", "127.0.0.1", "--port", "0", "--exclude", "build", "--no-open"]) == 0
    assert (started["host"], started["port"], started["allow_open"]) == ("127.0.0.1", 0, False)
    assert started["registry"].excludes == ("build",)


def test_without_a_file_the_defaults_apply(project, started, capsys):
    assert cli.main([str(project)]) == 0
    assert (started["host"], started["port"], started["allow_open"], started["scheme"]) == ("127.0.0.1", 8095, True, "system")
    assert "config: none found, using defaults" in capsys.readouterr().out


def test_a_bad_file_refuses_to_start(project, isolated_config, started, capsys):
    write(isolated_config, "port = 70000\n")
    assert cli.main([str(project)]) == 2
    err = capsys.readouterr().err
    assert "cannot start" in err and f"{isolated_config}: port:" in err and "Fix:" in err
    assert not started  # nothing was served
    assert cli.main([str(project), "--config", str(isolated_config.with_name("nope.toml"))]) == 2


def test_the_file_is_opened_read_only_and_never_written(project, isolated_config, started, monkeypatch, tmp_path):
    write(isolated_config, 'port = 9001\n[ui]\nscheme = "light"\n')
    before = hashlib.sha256(isolated_config.read_bytes()).hexdigest()
    mtime = isolated_config.stat().st_mtime_ns
    os.chmod(isolated_config, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    modes = []
    real_open = open

    def watching_open(file, mode="r", *a, **kw):
        if Path(os.fsdecode(file)) == isolated_config:
            modes.append(mode)
        return real_open(file, mode, *a, **kw)

    monkeypatch.setattr("builtins.open", watching_open)
    try:
        assert cli.main([str(project)]) == 0
        assert cli.main([str(project), "--export", str(tmp_path / "snap.html")]) == 0
    finally:
        monkeypatch.undo()
        os.chmod(isolated_config, stat.S_IRUSR | stat.S_IWUSR)
    assert modes == ["rb", "rb"]  # once per run, and only for reading
    assert hashlib.sha256(isolated_config.read_bytes()).hexdigest() == before
    assert isolated_config.stat().st_mtime_ns == mtime


def test_the_scheme_reaches_the_snapshot(project, isolated_config, tmp_path):
    write(isolated_config, '[ui]\nscheme = "dark"\n')
    out = tmp_path / "snap.html"
    assert cli.main([str(project), "--export", str(out)]) == 0
    html = out.read_text(encoding="utf-8")
    snap = json.loads(re.search(r"window\.SZ_SNAPSHOT=(\{.*?\});</script>", html, re.S).group(1).replace("<\\/", "</"))
    assert snap["meta"]["defaults"] == {"scheme": "dark"}
