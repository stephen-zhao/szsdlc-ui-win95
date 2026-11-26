"""The projects one viewer serves.

A project is one project sdlc root, plus an optional asset root, keyed by a stable, URL-safe
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

from . import locations
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

    def add(self, location, asset_root=None, persist: bool = False) -> str:
        """Open a project from any location and return its id. Opening it again returns the same id.

        A location is a folder on this computer (or any folder inside a
        project), or a place a backend keeps one, such as a git URL. Two
        locations name the same project when their project sdlc roots are equal;
        two projects can share a project sdlc store dir (one clone, two
        subdirectories), so that never decides it.
        """
        text = str(location).strip()
        key = text if locations.is_remote(text) else str(Path(text).expanduser().resolve())
        if asset_root is not None:
            asset_root = Path(asset_root).expanduser().resolve()
            if not asset_root.is_dir():
                raise ProjectError(f"asset root {asset_root} is not a directory")
        with self._lock:
            for pid, p in self.projects.items():
                if key in (p.location, str(p.start), str(p.sdlc_root)):
                    return pid
            project = Project(key, asset_root, self.excludes)
            for pid, p in self.projects.items():
                if p.sdlc_root == project.sdlc_root:
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
            "sdlc_root": project.sdlc_root.name if public else info["sdlc_root"],
            "sdlc_store_dir": project.sdlc_store_dir.name if public else info["sdlc_store_dir"],
            "asset_root": (project.asset_root.name if project.asset_root else None) if public else info["asset_root"],
            "backend": info["backend"], "schema_source": info["schema_source"], "szsdlc_version": info["szsdlc_version"],
            "entity_count": info["entity_count"], "type_count": len(project.schema["types"]),
            "unparseable": len(info["unparseable"]), "load_error": info["load_error"],
            "remote": project.remote, "update_warning": info["update_warning"],
            "location": (info["location"] if project.remote else project.sdlc_root.name) if public else info["location"],
        }

    def listing(self) -> list[dict]:
        return [self.summary(pid, p) for pid, p in self.projects.items()]

    # -- where projects come from -------------------------------------------
    def add_registered(self) -> None:
        """Every project sdlc store szsdlc has recorded (its stores file)."""
        # Private in szsdlc today; WI-0063 makes a public listing of them.
        stores_path = getattr(sz_backend, "_project_sdlc_stores_path", None) or sz_backend._registry_path
        try:
            path = stores_path()
            stores = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError):
            stores = {}
        for store in stores:
            try:
                self.add(store)
            except ProjectError as err:
                print(f"  skipped recorded project sdlc store {store}: {err}", file=sys.stderr)

    def load(self) -> None:
        if not self.projects_file or not self.projects_file.is_file():
            return
        data = yaml.safe_load(self.projects_file.read_text(encoding="utf-8")) or []
        for entry in data if isinstance(data, list) else []:
            entry = entry if isinstance(entry, dict) else {"location": entry}
            try:
                where = entry.get("location") or entry["store"]  # `store` is the 0.1 spelling
                assets = entry.get("asset_root") or entry.get("code_root")  # `code_root` is the 0.1 spelling
                self.add(where, Path(assets) if assets else None)
            except (KeyError, ProjectError) as err:
                print(f"  skipped a project in {self.projects_file}: {err}", file=sys.stderr)

    def save(self) -> None:
        if not self.projects_file:
            return
        # A remote project is saved by its location, so it reopens on a machine that never cloned it.
        rows = [{"location": p.location if p.remote else str(p.start), **({"asset_root": str(p.asset_root)} if p.asset_root else {})}
                for p in self.projects.values()]
        self.projects_file.parent.mkdir(parents=True, exist_ok=True)
        self.projects_file.write_text(yaml.safe_dump(rows, sort_keys=False), encoding="utf-8")
