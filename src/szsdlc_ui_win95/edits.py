"""One project's writes, through szsdlc's own operations and nothing else.

The viewer never writes a file. Every change is an operation of szsdlc's
operation layer (`szsdlc.ops`), called in-process, so every gate, invariant and
refusal is exactly the CLI's. This module only adds what a long-running viewer
needs around them:

- **one writer at a time per project:** mutations, sends and refreshes take the
  project's lock, which loads already take, so a request never reads half a
  write;
- **the precondition:** every entity write passes the content hash the page
  was drawn from as `expect`, so a change made since (by an agent, the CLI or
  a refresh) is refused rather than overwritten;
- **a reload after each write,** forced, so the response and the next read
  agree;
- **the edit log:** what this viewer did since its last send, for the list of
  unsent changes. Whether anything is unsent is the sdlc backend's to say
  (`has_unsent_changes`); the log only names what this viewer did.

Framework-free: no HTTP here. A refusal is raised as the `szsdlc.errors` class
szsdlc raised.
"""

from __future__ import annotations

import datetime as _dt
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from szsdlc import ops as sz_ops

from . import locations

if TYPE_CHECKING:  # pragma: no cover
    from .project import Project

#: The record a send makes. A git backend uses it as the commit subject.
SEND_REASON = "szsdlc-ui-win95: send changes"


@dataclass(frozen=True)
class Edit:
    """One change this viewer made: when, to what, and in words."""
    at: str
    ref: str
    op: str
    summary: str

    def to_dict(self) -> dict:
        return {"at": self.at, "ref": self.ref, "op": self.op, "summary": self.summary}


def describe_set(result: Any) -> str:
    """A `set` in words: `status ready → designing`, `due (not set) → 2026-12-01`."""
    parts = []
    for change in result.changes:
        text = f"{change.field} {_plain(change.before)} → {_plain(change.after)}"
        parts.append(text + (" (forced)" if change.forced else ""))
    return "; ".join(parts)


def describe_tags(op: str, tags: list[str]) -> str:
    """A `tag` or `untag` in words: `tag +ui +api`, `untag −ui`."""
    sign = "+" if op == "tag" else "−"
    return " ".join([op, *(sign + t for t in tags)])


def _plain(value: Any) -> str:
    return "(not set)" if value in (None, "") else str(value)


class Edits:
    """The writes for one project, and what they left unsent."""

    def __init__(self, project: Project):
        self.project = project
        self._log: list[Edit] = []
        self._log_lock = threading.Lock()

    # -- writes ---------------------------------------------------------------
    def set(self, ref: str, values: dict[str, str], *, expect: str,
            force: bool = False, reason: str | None = None) -> Any:
        """`szsdlc set`: each `field=value`, in order, through the workflow."""
        params = {"ref": ref, "assignments": [f"{k}={v}" for k, v in values.items()],
                  "expect": expect, "force": force, "reason": reason}
        result = self._mutate("set", params)
        self._record(result.id, "set", describe_set(result))
        return result

    def tag(self, ref: str, tags: list[str], *, expect: str) -> Any:
        return self._tags("tag", ref, tags, expect)

    def untag(self, ref: str, tags: list[str], *, expect: str) -> Any:
        return self._tags("untag", ref, tags, expect)

    def _tags(self, op: str, ref: str, tags: list[str], expect: str) -> Any:
        result = self._mutate(op, {"ref": ref, "tags": list(tags), "expect": expect})
        self._record(result.id, op, describe_tags(op, list(tags)))
        return result

    def _mutate(self, op: str, params: dict) -> Any:
        with self.project.lock:
            try:
                return sz_ops.call(op, params, str(self.project.sdlc_root))
            finally:
                # Reloaded even after a refusal: a refusal writes nothing, but
                # it may have been about a change made behind the page's back.
                self.project.reload()

    def send(self) -> Any:
        """`szsdlc sync`, once: render, then send unsent changes and take in others'.

        One record for everything since the last send (REQ-0014). A refusal
        keeps the changes, and the log, to send next time.
        """
        with self.project.lock:
            try:
                result = sz_ops.call("sync", {}, str(self.project.sdlc_root))
            finally:
                self.project.reload()
        self.clear()
        return result

    # -- what is unsent ---------------------------------------------------------
    def _record(self, ref: str, op: str, summary: str) -> None:
        stamp = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
        with self._log_lock:
            self._log.append(Edit(stamp, ref, op, summary))

    def clear(self) -> None:
        """Forget the log: everything in it was sent, or replaced by a refresh."""
        with self._log_lock:
            self._log.clear()

    def log(self) -> list[Edit]:
        with self._log_lock:
            return list(self._log)

    def changes(self) -> dict:
        """`{unsent, edits, outside}`: the backend's word on unsent state, and what this viewer did.

        `outside` is set when the backend has unsent changes this viewer's log
        does not hold: made by the CLI, an agent or an earlier viewer run.
        """
        try:
            unsent = bool(locations.has_unsent_changes(self.project.backend))
        except Exception:  # noqa: BLE001 - an unreadable state is shown as nothing unsent, never a failed request
            unsent = False
        edits = self.log() if unsent else []
        return {"unsent": unsent, "edits": [e.to_dict() for e in edits], "outside": unsent and not edits}

    # -- findings ---------------------------------------------------------------
    def findings(self, limit: int = 0) -> dict:
        """`szsdlc validate`, as data: counts, and the findings most severe first (all of them for 0)."""
        with self.project.lock:
            result = sz_ops.call("validate", {"limit": limit}, str(self.project.sdlc_root))
        return {"errors": result.errors, "warnings": result.warnings, "total": result.total,
                "rows": [row.to_dict() for row in result.rows]}
