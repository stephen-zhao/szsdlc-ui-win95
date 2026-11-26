"""Supporting documents: finding the ones an item mentions, and reading them safely.

Two roots exist, named as szsdlc's glossary names them. The **project sdlc root**
(root id `sdlc`) holds the project's `.szsdlc/` and its records. A **project
asset root** (root id `assets`) holds the code and other assets the project
describes: the same directory for a `workdir` project, and the directory the
viewer was pointed at when the records are kept elsewhere. Every path is
contained to its root, `.git` is never read, and nothing is ever served as
active content.
"""

from __future__ import annotations

import datetime as _dt
import posixpath
import re
from pathlib import Path

import yaml

MD_LINK_RE = re.compile(r"(?<!!)\[([^\]\n]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
CODE_PATH_RE = re.compile(r"`([A-Za-z0-9_.][\w.\-/]*\.(?:md|markdown|txt|ya?ml|json|toml|py|ts|js|sh|cfg|ini))`")
URL_RE = re.compile(r"(?<![(\[<\"'])\bhttps?://[^\s)<>\]\"']+")
MAX_TEXT_BYTES = 2_000_000


def jsonify(value):
    """YAML scalars to JSON ones: dates become ISO strings, tuples lists."""
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonify(v) for v in value]
    return value


def split_frontmatter(text: str) -> tuple[dict | None, str]:
    """(frontmatter, body). A file without a valid leading block is all body."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            try:
                data = yaml.safe_load("".join(lines[1:i])) or {}
            except yaml.YAMLError:
                return None, text
            if not isinstance(data, dict):
                return None, text
            return data, "".join(lines[i + 1:]).lstrip("\n")
    return None, text


def references(text: str) -> list[str]:
    """Document references in Markdown, in order of first mention.

    Markdown links, URLs, and backticked paths. A backticked path counts only
    when it has a directory or is prose (`.md`, `.txt`): a bare `git.py` in a
    design note names code, not a document to read.
    """
    found = []
    for m in MD_LINK_RE.finditer(text):
        target = m.group(2).split("#")[0]
        if target and not target.startswith(("mailto:", "#")):
            found.append(target)
    found += [m.group(1) for m in CODE_PATH_RE.finditer(text)
              if "/" in m.group(1) or m.group(1).lower().endswith((".md", ".markdown", ".txt"))]
    found += [m.group(0).rstrip(".,;:") for m in URL_RE.finditer(text)]
    return list(dict.fromkeys(found))


#: The root ids before WI-0069, still accepted on input (`?root=`, copied links).
LEGACY_ROOTS = {"store": "sdlc", "code": "assets", "code?": "assets?"}


def normalize_root(root: str) -> str:
    """A root id in today's words: `sdlc` or `assets`, whatever spelling arrived."""
    return LEGACY_ROOTS.get(root, root)


class Roots:
    """The two places a document can live, and safe access to both."""

    def __init__(self, sdlc_root: Path, asset_root: Path | None):
        self.sdlc_root = sdlc_root
        self.asset_root = asset_root

    def base(self, root: str) -> Path | None:
        return {"sdlc": self.sdlc_root, "assets": self.asset_root}.get(normalize_root(root))

    def safe_path(self, root: str, rel: str) -> Path | None:
        """The file `rel` names under `root`, or None if it escapes, is in .git, or the root is unset."""
        base = self.base(root)
        if base is None or not rel or rel.startswith("..") or "\x00" in rel:
            return None
        p = (base / rel).resolve()
        try:
            inside = p.relative_to(base)
        except ValueError:
            return None
        if ".git" in inside.parts:
            return None
        return p

    def resolve(self, ref: str, mentioned_in: str | None) -> dict:
        """Where a reference lands: next to its mention, then the sdlc root, then the asset root."""
        # A link relative to its file means the same path under either root:
        # for a workdir project the two are one directory, and when the records
        # are kept elsewhere the asset root mirrors the paths documents were
        # written against.
        paths = []
        if mentioned_in and not ref.startswith("/"):
            paths.append(posixpath.normpath(posixpath.join(posixpath.dirname(mentioned_in), ref)))
        paths.append(posixpath.normpath(ref.lstrip("/")))
        paths = list(dict.fromkeys(paths))
        roots = ["sdlc"] + (["assets"] if self.asset_root else [])
        for root in roots:
            for path in paths:
                p = self.safe_path(root, path)
                if p and p.is_file():
                    return {"root": root, "path": path, "exists": True, "size": p.stat().st_size}
        return {"root": "assets" if self.asset_root else "assets?", "path": paths[0], "exists": False}

    def read(self, root: str, rel: str, fallback: bool = False) -> dict:
        """One document as the API returns it. Front matter is split out; `raw` is the whole file."""
        root = normalize_root(root)
        rel = posixpath.normpath(str(rel).lstrip("/"))
        p = self.safe_path(root, rel)
        if (p is None or not p.is_file()) and fallback and root == "sdlc" and self.asset_root:
            root, p = "assets", self.safe_path("assets", rel)
        if p is None or not p.is_file():
            return {"root": root, "path": rel, "exists": False, "asset_root": bool(self.asset_root)}
        raw = p.read_bytes()
        if b"\x00" in raw[:4096] or len(raw) > MAX_TEXT_BYTES:
            return {"root": root, "path": rel, "exists": True, "kind": "binary", "size": len(raw)}
        text = raw.decode("utf-8", errors="replace")
        markdown = p.suffix.lower() in (".md", ".markdown")
        front, body = split_frontmatter(text) if markdown else (None, text)
        return jsonify({"root": root, "path": rel, "exists": True, "kind": "markdown" if markdown else "text",
                        "size": len(raw), "frontmatter": front, "text": body, "raw": text})
