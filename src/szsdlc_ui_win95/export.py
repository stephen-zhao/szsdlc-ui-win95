"""A static, self-contained snapshot: one HTML file, no server, no network.

Every API answer is precomputed and embedded, so the frontend runs unchanged
(it switches to the snapshot when `window.SZ_SNAPSHOT` is set). Local paths are
reduced to folder names. Opening further projects is not offered.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

from .registry import Registry
from .server import STATIC, meta

VENDOR = ("marked.umd.js", "purify.min.js")


def snapshot(registry: Registry, *, scheme: str = "system") -> dict:
    return {
        "generated_at": _dt.date.today().isoformat(),
        "meta": meta(scheme),
        "projects": [registry.summary(pid, p, public=True) for pid, p in registry.projects.items()],
        "data": {pid: p.snapshot() for pid, p in registry.projects.items()},
    }


def render(registry: Registry, *, fragment: bool = False, scheme: str = "system") -> str:
    """The page as one HTML string. `fragment` drops the document skeleton, for hosts that supply their own."""
    data = json.dumps(snapshot(registry, scheme=scheme), ensure_ascii=False).replace("</", "<\\/")
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "win95.css").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    vendor = "\n".join((STATIC / "vendor" / name).read_text(encoding="utf-8") for name in VENDOR)
    html = re.sub(r'<meta name="viewer-token"[^>]*>\s*', "", html)
    if fragment:
        html = re.sub(r"(?is)<!doctype html>|</?html[^>]*>|</?head>|</?body>|<meta [^>]*>\s*", "", html)
    html = html.replace('<link rel="stylesheet" href="win95.css">', f"<style>\n{css}\n</style>")
    html = re.sub(r'<script src="vendor/[^"]+"></script>\s*', "", html)
    return html.replace('<script src="app.js"></script>',
                        f"<script>{vendor}</script>\n<script>window.SZ_SNAPSHOT={data};</script>\n<script>{js}</script>")


def write(registry: Registry, out: Path, *, fragment: bool = False, scheme: str = "system") -> Path:
    out = Path(out)
    out.write_text(render(registry, fragment=fragment, scheme=scheme), encoding="utf-8")
    return out
