"""The layers' import rules (AGENTS.md, "Layers"), checked on the source.

Inside out: the core (`errors`, `documents`, `locations`, `project`,
`registry`), then `services`, then `web`, then the composition root and the
interfaces (`server`, `cli`, `export`). A layer imports only layers inside it,
and only `web` may import a web framework.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import szsdlc_ui_win95

PACKAGE = Path(szsdlc_ui_win95.__file__).parent
CORE = {"errors", "documents", "locations", "project", "registry"}
FRAMEWORKS = {"fastapi", "starlette", "uvicorn", "pydantic"}
OUTER = {"server", "cli", "export", "__main__"}


def layer(path: Path) -> str:
    rel = path.relative_to(PACKAGE)
    if rel.parts[0] in ("services", "web"):
        return rel.parts[0]
    return "core" if path.stem in CORE else "outer" if path.stem in OUTER else "package"


def imports(path: Path) -> set[str]:
    """Every module `path` imports, as absolute dotted names."""
    package = ".".join(("szsdlc_ui_win95", *path.relative_to(PACKAGE).parent.parts))
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = package.split(".")
            if node.level:
                base = base[: len(base) - node.level + 1]
                name = ".".join(base + ([node.module] if node.module else []))
            else:
                name = node.module or ""
            found.add(name)
            found |= {f"{name}.{a.name}" for a in node.names}
    return found


def ours(name: str) -> str | None:
    """The layer a szsdlc_ui_win95 module belongs to, or None for anything else."""
    parts = name.split(".")
    if parts[0] != "szsdlc_ui_win95" or len(parts) == 1:
        return None
    if parts[1] in ("services", "web"):
        return parts[1]
    return "core" if parts[1] in CORE else "outer" if parts[1] in OUTER else None


ALLOWED = {"core": {"core"}, "services": {"core", "services"},
           "web": {"core", "services", "web"}, "outer": {"core", "services", "web", "outer"}}


def test_each_layer_imports_only_layers_inside_it():
    for path in PACKAGE.rglob("*.py"):
        own = layer(path)
        if own == "package":
            continue
        for name in imports(path):
            other = ours(name)
            assert other is None or other in ALLOWED[own], f"{path.relative_to(PACKAGE)} ({own}) imports {name} ({other})"


def test_only_the_web_layer_imports_a_web_framework():
    for path in PACKAGE.rglob("*.py"):
        if layer(path) == "web":
            continue
        leaked = {n for n in imports(path) if n.split(".")[0] in FRAMEWORKS}
        assert not leaked, f"{path.relative_to(PACKAGE)} imports {sorted(leaked)}"


def test_the_checks_see_a_violation(tmp_path, monkeypatch):
    """A services module importing FastAPI, or the web layer, is caught."""
    bad = PACKAGE / "services" / "_layer_probe.py"
    bad.write_text("from fastapi import FastAPI\nfrom ..web import app\n", encoding="utf-8")
    try:
        with pytest.raises(AssertionError, match="web"):
            test_each_layer_imports_only_layers_inside_it()
        with pytest.raises(AssertionError, match="fastapi"):
            test_only_the_web_layer_imports_a_web_framework()
    finally:
        bad.unlink()
