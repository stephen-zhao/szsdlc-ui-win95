"""The viewer's operations: reading projects, opening one, refreshing one."""

from __future__ import annotations

import mimetypes
import posixpath
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import szsdlc

from .. import __version__
from ..errors import UnsentChanges
from ..project import Project, ProjectError
from ..registry import Registry
from .errors import Conflict, Forbidden, Invalid, NotFound

#: Content types never served from a store as themselves: they would be active content.
ACTIVE = ("text/html", "image/svg+xml", "application/xhtml+xml")


@dataclass(frozen=True)
class Raw:
    """A file's bytes and the content type to serve them as."""
    data: bytes
    content_type: str


class ViewerService:
    """Every operation the viewer offers, over the projects one viewer serves.

    Constructed with what it needs (the registry, and whether opening projects
    is allowed), so any interface can drive it and a test can build one directly.
    """

    def __init__(self, registry: Registry, *, allow_open: bool = True):
        self.registry = registry
        self.allow_open = allow_open

    # -- the viewer ----------------------------------------------------------
    def meta(self) -> dict:
        return {"viewer": "szsdlc-ui-win95", "version": __version__,
                "szsdlc_version": szsdlc.__version__, "readonly": True}

    def projects(self) -> list[dict]:
        return self.registry.listing()

    def ensure_can_open(self) -> None:
        """Refuse when this viewer was started with --no-open; asked first, before anything is read."""
        if not self.allow_open:
            raise Forbidden("Opening projects is disabled",
                            "This viewer was started with --no-open; restart it with the project as an argument.")

    def open_project(self, location: str, code_root: str | None = None) -> dict:
        """Open a project: a folder here, or where a backend keeps one, such as a repository URL."""
        self.ensure_can_open()
        where = location.strip()
        if not where:
            raise Invalid("No location given", "Name a folder on this computer, or a repository URL.")
        try:
            pid = self.registry.add(where, Path(code_root) if code_root else None, persist=True)
        except ProjectError as err:
            raise Invalid("Cannot open that project", str(err),
                          fix="Give a folder on this computer that holds a szsdlc project, or where one "
                              "is kept, such as https://host/org/repo.git.") from None
        return self.registry.summary(pid, self.registry.get(pid))

    def known(self, pid: str) -> Project:
        """The project, or NotFound; nothing is re-read."""
        project = self.registry.get(pid)
        if project is None:
            raise NotFound("No such project", pid)
        return project

    def refresh(self, pid: str, *, replace: bool = False) -> dict:
        """Take the sdlc backend's latest, sending nothing. Opens nothing, so --no-open does not apply."""
        project = self.known(pid)
        try:
            result = project.refresh_from_backend(replace=replace)
        except UnsentChanges as err:
            raise Conflict("Unsent changes would be replaced", str(err),
                           fix="Refresh anyway to replace them, or send them first.") from None
        except ProjectError as err:
            raise Invalid("Cannot refresh", str(err)) from None
        return {**result, "project": self.registry.summary(pid, project)}

    # -- one project's reads --------------------------------------------------
    def project(self, pid: str) -> Project:
        """The project, re-read first if its files changed."""
        project = self.registry.get(pid)
        if project is None:
            raise NotFound("No such project", f"This viewer has no project `{pid}`.")
        project.refresh()
        return project

    def info(self, pid: str) -> dict:
        return self.project(pid).info()

    def schema(self, pid: str) -> dict:
        return self.project(pid).schema

    def entities(self, pid: str) -> list[dict]:
        return self.project(pid).rows()

    def entity(self, pid: str, ref: str) -> dict:
        found = self.project(pid).entity(ref)
        if not found:
            raise NotFound("No such entity", ref)
        return found

    def roadmaps(self, pid: str) -> Any:
        return self.project(pid).roadmaps

    def docs(self, pid: str) -> Any:
        return self.project(pid).store_docs

    def doc(self, pid: str, root: str, path: str, fallback: bool = False) -> dict:
        return self.project(pid).doc(root, path, fallback)

    def raw(self, pid: str, root: str, path: str) -> Raw | None:
        """A file's bytes, contained to its root, never as active content; None when there is none."""
        p = self.project(pid).roots.safe_path(root, posixpath.normpath(path))
        if not p or not p.is_file():
            return None
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if ctype in ACTIVE or ctype.endswith("javascript"):
            ctype = "text/plain; charset=utf-8"
        return Raw(p.read_bytes(), ctype)
