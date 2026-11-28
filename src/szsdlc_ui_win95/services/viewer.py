"""The viewer's operations: reading projects, opening and refreshing one, and editing one through szsdlc."""

from __future__ import annotations

import mimetypes
import posixpath
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import szsdlc
from szsdlc import errors as sz_errors
from szsdlc import ops as sz_ops

from .. import __version__
from ..errors import UnsentChanges
from ..project import Project, ProjectError
from ..registry import Registry
from .errors import Conflict, Forbidden, Invalid, NotFound, Rejected, ServiceError, Stale

#: Content types never served from a store as themselves: they would be active content.
ACTIVE = ("text/html", "image/svg+xml", "application/xhtml+xml")


@dataclass(frozen=True)
class Raw:
    """A file's bytes and the content type to serve them as."""
    data: bytes
    content_type: str


class ViewerService:
    """Every operation the viewer offers, over the projects one viewer serves.

    Constructed with what it needs (the registry, whether opening projects is
    allowed, and whether editing is), so any interface can drive it and a test
    can build one directly.
    """

    def __init__(self, registry: Registry, *, allow_open: bool = True, read_only: bool = False):
        self.registry = registry
        self.allow_open = allow_open
        self.read_only = read_only

    # -- the viewer ----------------------------------------------------------
    def meta(self) -> dict:
        return {"viewer": "szsdlc-ui-win95", "version": __version__,
                "szsdlc_version": szsdlc.__version__, "readonly": self.read_only}

    def projects(self) -> list[dict]:
        return self.registry.listing()

    def ensure_can_open(self) -> None:
        """Refuse when this viewer was started with --no-open; asked first, before anything is read."""
        if not self.allow_open:
            raise Forbidden("Opening projects is disabled",
                            "This viewer was started with --no-open; restart it with the project as an argument.")

    def open_project(self, location: str, asset_root: str | None = None) -> dict:
        """Open a project: a folder here, or where a backend keeps one, such as a repository URL."""
        self.ensure_can_open()
        where = location.strip()
        if not where:
            raise Invalid("No location given", "Name a folder on this computer, or a repository URL.")
        try:
            pid = self.registry.add(where, Path(asset_root) if asset_root else None, persist=True)
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
        return {**self.project(pid).info(), "readonly": self.read_only}

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

    # -- one project's edits, through szsdlc's operations ----------------------
    def ensure_can_edit(self) -> None:
        """Refuse when this viewer was started with --read-only; asked first, before anything is read."""
        if self.read_only:
            raise Forbidden("Editing is disabled",
                            "This viewer was started with --read-only; restart it without the flag to edit.")

    def set(self, pid: str, ref: str, values: dict[str, str], *, expect: str,
            force: bool = False, reason: str | None = None) -> dict:
        """Set fields and the status through `szsdlc set`, refused if the item changed since `expect`."""
        project = self._editable(pid)
        if not values:
            raise Invalid("Nothing to set", "Name at least one field and its value.")
        result = _through_szsdlc(lambda: project.edits.set(ref, values, expect=expect, force=force, reason=reason))
        return self._after_edit(project, result)

    def tag(self, pid: str, ref: str, tags: list[str], *, expect: str, add: bool = True) -> dict:
        """Add (`szsdlc tag`) or remove (`szsdlc untag`) tags, refused if the item changed since `expect`."""
        project = self._editable(pid)
        cleaned = [t.strip() for t in tags if t and t.strip()]
        if not cleaned:
            raise Invalid("No tag given", "Name at least one tag.")
        write = project.edits.tag if add else project.edits.untag
        result = _through_szsdlc(lambda: write(ref, cleaned, expect=expect))
        return self._after_edit(project, result)

    def capture(self, pid: str, text: str, *, type_name: str | None = None) -> dict:
        """Capture a thought into an intake type through `szsdlc capture`; szsdlc refuses an empty one."""
        project = self._editable(pid)
        result = _through_szsdlc(lambda: project.edits.capture(text, type_name))
        return self._after_edit(project, result)

    def send(self, pid: str) -> dict:
        """Send unsent changes, once, through `szsdlc sync`: one record for all of them."""
        project = self._editable(pid)
        result = _through_szsdlc(project.edits.send, title="Could not send changes")
        return {"changed": list(result.changed), "arrived": result.incoming, "sent": result.outgoing,
                "changes": project.edits.changes()}

    def changes(self, pid: str) -> dict:
        """Whether the project has unsent changes, and the ones this viewer made."""
        return self.known(pid).edits.changes()

    def findings(self, pid: str) -> dict:
        """`szsdlc validate`, as data."""
        project = self.project(pid)
        return _through_szsdlc(project.edits.findings, title="Cannot validate")

    def _editable(self, pid: str):
        self.ensure_can_edit()
        return self.known(pid)

    def _after_edit(self, project, result) -> dict:
        """The post-state: the operation's result, the item as it is now, what is unsent, the finding counts."""
        found = project.entity(result.id) or {}
        try:
            counts = project.edits.findings(limit=1)  # the counts cover every finding
            findings = {"errors": counts["errors"], "warnings": counts["warnings"]}
        except sz_errors.SzsdlcError:
            findings = None
        return {"result": result.to_dict(), "entity": found, "changes": project.edits.changes(),
                "findings": findings}


#: How each szsdlc refusal class is refused here, with the title a person sees.
REFUSALS: dict[str, tuple[type[ServiceError], str]] = {
    "stale_precondition": (Stale, "Changed on disk"),
    "refused": (Rejected, "Not allowed"),
    "unknown_reference": (NotFound, "No such entity"),
}


def _through_szsdlc(run, *, title: str = "Not a valid change"):
    """Run a szsdlc operation, turning its refusal into the service's, with the refusal kept as data."""
    try:
        return run()
    except sz_errors.SzsdlcError as err:
        data = sz_ops.refusal_to_data(err)
        cls, named = REFUSALS.get(data["class"], (Invalid, title))
        raise cls(named if data["class"] in REFUSALS else title, err.problem, fix=err.fix, refusal=data) from None
