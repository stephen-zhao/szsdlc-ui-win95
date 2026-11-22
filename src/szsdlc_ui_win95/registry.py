"""The projects one viewer serves.

A project is one store, plus an optional code root, keyed by a stable, URL-safe
id derived from its name. Selecting a project belongs to the interface: every
operation underneath acts on exactly one project and never learns others exist.
"""

from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path

import yaml
from szsdlc import backend as sz_backend

from .project import Project, ProjectError


def slug(text: str) -> str:
    """Lowercase letters, digits and single hyphens, so `<id>--<ENTITY>` stays unambiguous."""
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "project"


class Registry:
    def __init__(self, excludes=(), projects_file: Path | None = None):
        self.excludes = tuple(excludes)
        self.projects_file = projects_file
        self.projects: dict[str, Project] = {}
        self._lock = threading.Lock()

    def add(self, start, code_root=None, persist: bool = False) -> str:
        """Open a project (or any folder inside one) and return its id. Opening it again returns the same id."""
        start = Path(start).expanduser().resolve()
        if code_root is not None:
            code_root = Path(code_root).expanduser().resolve()
            if not code_root.is_dir():
                raise ProjectError(f"code root {code_root} is not a directory")
        with self._lock:
            for pid, p in self.projects.items():
                if start in (p.start, p.store):
                    return pid
            project = Project(start, code_root, self.excludes)
            for pid, p in self.projects.items():
                if p.store == project.store:
                    return pid
            base = slug(project.info()["name"])
            pid, n = base, 2
            while pid in self.projects:
                pid, n = f"{base}-{n}", n + 1
            self.projects[pid] = project
        if persist:
            self.save()
        return pid

    def get(self, pid: str) -> Project | None:
        return self.projects.get(pid)

    def summary(self, pid: str, project: Project, *, public: bool = False) -> dict:
        info = project.info()
        return {
            "id": pid, "name": info["name"],
            "store": project.store.name if public else info["store"],
            "code_root": (project.code_root.name if project.code_root else None) if public else info["code_root"],
            "backend": info["backend"], "schema_source": info["schema_source"], "szsdlc_version": info["szsdlc_version"],
            "entity_count": info["entity_count"], "type_count": len(project.schema["types"]),
            "unparseable": len(info["unparseable"]), "load_error": info["load_error"],
        }

    def listing(self) -> list[dict]:
        return [self.summary(pid, p) for pid, p in self.projects.items()]

    # -- where projects come from -------------------------------------------
    def add_registered(self) -> None:
        """Every store szsdlc keeps elsewhere, from its own registry."""
        try:  # private in szsdlc today; a public `backend.registered()` is a small, obvious addition
            path = sz_backend._registry_path()
            stores = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError):
            stores = {}
        for store in stores:
            try:
                self.add(Path(store))
            except ProjectError as err:
                print(f"  skipped registered store {store}: {err}", file=sys.stderr)

    def load(self) -> None:
        if not self.projects_file or not self.projects_file.is_file():
            return
        data = yaml.safe_load(self.projects_file.read_text(encoding="utf-8")) or []
        for entry in data if isinstance(data, list) else []:
            entry = entry if isinstance(entry, dict) else {"store": entry}
            try:
                self.add(Path(entry["store"]), Path(entry["code_root"]) if entry.get("code_root") else None)
            except (KeyError, ProjectError) as err:
                print(f"  skipped a project in {self.projects_file}: {err}", file=sys.stderr)

    def save(self) -> None:
        if not self.projects_file:
            return
        rows = [{"store": str(p.start), **({"code_root": str(p.code_root)} if p.code_root else {})}
                for p in self.projects.values()]
        self.projects_file.parent.mkdir(parents=True, exist_ok=True)
        self.projects_file.write_text(yaml.safe_dump(rows, sort_keys=False), encoding="utf-8")
