"""Session configuration: a file a person edits outside the viewer.

The viewer reads it once, at startup, from a read-only handle, and never writes
it or offers to. A change takes effect on the next start. Application data,
which the viewer does write, is a separate thing and does not live here.

The format is TOML: the stdlib reads it and has no writer, which suits a file
that must never be written.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

APP = "szsdlc-ui-win95"
FILENAME = "config.toml"
SCHEMES = ("system", "light", "dark")


class ConfigError(Exception):
    """A configuration the viewer refuses to start with. The message names the file, the key and the fix."""


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8095
    open_project: bool = True
    exclude: tuple[str, ...] = ()
    scheme: str = "system"
    source: Path | None = field(default=None, compare=False)


def default_dir(env: dict[str, str] | None = None, platform: str | None = None, home: Path | None = None) -> Path:
    """The per-user configuration directory for this viewer."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else home
    if platform.startswith("win"):
        base = Path(env["APPDATA"]) if env.get("APPDATA") else home / "AppData" / "Roaming"
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else home / ".config"
    return base / APP


def default_path() -> Path:
    return default_dir() / FILENAME


def _refuse(path: Path, key: str | None, problem: str, fix: str) -> ConfigError:
    where = f"{path}: {key}" if key else str(path)
    return ConfigError(f"{where}: {problem}.\nFix: {fix}")


def _string(path, key, value) -> str:
    if not isinstance(value, str) or not value:
        raise _refuse(path, key, f"must be a non-empty string, not {value!r}", f'{key} = "127.0.0.1"')
    return value


def _port(path, key, value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 65535:
        raise _refuse(path, key, f"must be a whole number from 0 to 65535, not {value!r}",
                      f"{key} = 8095   (0 picks a free port)")
    return value


def _bool(path, key, value) -> bool:
    if not isinstance(value, bool):
        raise _refuse(path, key, f"must be true or false, not {value!r}", f"{key} = false")
    return value


def _names(path, key, value) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise _refuse(path, key, f"must be a list of directory names, not {value!r}", f'{key} = ["vendor", "build"]')
    return tuple(value)


def _scheme(path, key, value) -> str:
    if value not in SCHEMES:
        raise _refuse(path, key, f"must be one of {', '.join(SCHEMES)}, not {value!r}", f'{key} = "dark"')
    return value


# Dotted key → (Settings field, validator).
KEYS = {
    "host": ("host", _string),
    "port": ("port", _port),
    "open_project": ("open_project", _bool),
    "exclude": ("exclude", _names),
    "ui.scheme": ("scheme", _scheme),
}
TABLES = {"ui"}


def _flatten(path: Path, data: dict) -> dict:
    flat = {}
    for key, value in data.items():
        if key in TABLES:
            if not isinstance(value, dict):
                raise _refuse(path, key, "must be a table", f"write it as a [{key}] section")
            flat.update({f"{key}.{k}": v for k, v in value.items()})
        else:
            flat[key] = value
    return flat


def load(path: Path | None = None) -> Settings:
    """Read the configuration once. `path` is an explicit `--config`; None means the per-user default.

    A missing default file means defaults; a missing explicit one refuses, since
    the person named it. The file is opened read-only and never written.
    """
    explicit = path is not None
    path = Path(path).expanduser() if explicit else default_path()
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        if explicit:
            raise _refuse(path, None, "no such file", "create it, or leave out --config to use "
                          f"{default_path()}") from None
        return Settings()
    except tomllib.TOMLDecodeError as err:
        raise _refuse(path, None, f"is not valid TOML ({err})", "correct the line named, or move the file aside") from None
    except OSError as err:
        raise _refuse(path, None, f"cannot be read ({err.strerror or err})", "make it readable, or move it aside") from None

    values = {}
    for key, value in _flatten(path, data).items():
        if key not in KEYS:
            raise _refuse(path, key, "is not a setting", f"remove it; the settings are {', '.join(KEYS)}")
        name, check = KEYS[key]
        values[name] = check(path, key, value)
    return Settings(**values, source=path)
