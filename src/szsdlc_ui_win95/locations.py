"""Any location to a project, through szsdlc's own sdlc backends.

A **location** is whatever identifies a project: a folder on this computer, or a
place a szsdlc backend can keep one, such as a git URL. People type one into
Open project, or name one on the command line. Which backend serves it is not
the viewer's to know: szsdlc's backends interpret locations themselves
(`szsdlc.backend.from_location`, WI-0071), so this module parses no URL and
names no backend type.

Everything goes through szsdlc's own backend machinery, so cloning, the git
protocol allowlist, credential redaction and the store registry behave exactly
as they do for the CLI:

- a **folder** resolves as the CLI resolves it (the project sdlc store it is
  inside, or the backend its settings select), then `ensure` materializes the
  project sdlc store dir if it is not the folder itself;
- **anywhere else** is offered to szsdlc's backends; the one that claims it
  builds itself from its own settings, and `ensure` materializes it.

The viewer creates a project sdlc store dir only here, only when a person
opens a project, and only through the backend's own `ensure`. Viewing never
writes to a project.

The words are szsdlc's glossary (WI-0066). The `_sdlc_*` helpers below read its
new names when the installed szsdlc has them and the old ones before, so the
viewer runs on either without deprecation warnings.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from szsdlc import backend as sz_backend
from szsdlc import config as sz_config
from szsdlc import errors as sz_errors

from .errors import ProjectError


@dataclass(frozen=True)
class Resolved:
    backend: object
    root: Path
    #: The folder it was opened from, when the location is a local one.
    start: Path | None
    #: The location as given.
    location: str


def is_remote(text: str) -> bool:
    """True when `text` names a place a backend keeps a project, not a folder here.

    A location szsdlc refuses (a git remote helper such as `ext::`) is not one.
    """
    text = str(text).strip()
    if sz_backend.is_folder(text):
        return False
    try:
        return sz_backend.from_location(text) is not None
    except sz_errors.SzsdlcError:
        return False


def display(location: str) -> str:
    """A location fit to show, with credentials and query strings masked, as szsdlc shows it."""
    return sz_backend.redact(str(location))


def store_name(store: Path) -> str:
    """A readable name for a project sdlc store dir szsdlc made, without its hash."""
    return sz_backend.project_sdlc_store_dir_name(Path(store))


def resolve(location) -> Resolved:
    """The backend and project root a location names, with the store materialized."""
    text = str(location).strip()
    if not text:
        raise ProjectError("No location given. Name a folder on this computer, or a repository URL.")
    if sz_backend.is_folder(text):
        return _folder(text)
    try:
        backend = sz_backend.from_location(text)
    except sz_errors.SzsdlcError as err:
        raise ProjectError(f"{display(text)} is not a folder on this computer, nor a location szsdlc "
                           f"can open: {err.problem}") from None
    if backend is None:
        return _folder(text)  # neither: the folder path says so
    return _kept_elsewhere(text, backend)


def _folder(text: str) -> Resolved:
    start = Path(text).expanduser().resolve()
    if not start.is_dir():
        raise ProjectError(f"{text} is not a folder on this computer, nor a repository location "
                           "such as https://host/org/repo.git.")
    try:
        backend = store_for(start) or sz_backend.resolve(start)
        sz_backend.ensure(backend)  # creates or clones the project sdlc store dir; nothing for workdir
    except sz_errors.SzsdlcError as err:
        raise ProjectError(str(err)) from None
    root = sdlc_root(backend) or _find_sdlc_root(start)
    if root is None or not sz_config.config_path_for(Path(root)).is_file():
        raise ProjectError(f"{start} is not a szsdlc project: no .szsdlc/config.yml in it or above it, "
                           "and its settings name no backend that keeps one elsewhere.")
    return Resolved(backend, Path(root).resolve(), start, text)


def _kept_elsewhere(text: str, backend) -> Resolved:
    try:
        sz_backend.ensure(backend)
    except sz_errors.SzsdlcError as err:
        raise ProjectError(str(err)) from None
    root = Path(sdlc_root(backend))
    if not sz_config.config_path_for(root).is_file():
        raise ProjectError(f"{display(text)} holds no szsdlc project: there is no .szsdlc/config.yml in it "
                           f"(its local copy is {sdlc_store_dir(backend)}).")
    return Resolved(backend, root.resolve(), None, text)


def bring_up_to_date(backend) -> str | None:
    """Update a copy from its sdlc backend, when that is safe. Returns a warning, or None.

    `materialize` on an existing clone only verifies it, so without this a
    project opened from a remote would show whatever was last fetched. A sync is
    run only when there are no unsent changes: it can then only fetch and
    fast-forward. With unsent changes the copy is left exactly as it is,
    because syncing would publish them.
    """
    if not sz_backend.relocates(backend):
        return None
    try:
        if has_unsent_changes(backend):
            return "This copy has unsent changes, so it was not updated; it is shown as it is."
        report = backend.sync("szsdlc-ui-win95: project opened")
    except Exception as err:  # noqa: BLE001 - a failed update must not stop the project opening
        return f"Could not update from its sdlc backend ({err}); showing the local copy."
    problem = sz_backend.describe_problem(report)
    return f"Could not update from its sdlc backend ({problem}); showing the local copy." if problem else None


def refresh(backend):
    """Replace local state with the sdlc backend's latest, through szsdlc.

    szsdlc's own operation: nothing is sent and nothing is merged. It replaces
    local state that differs without asking, so asking is the caller's job.
    Returns szsdlc's report.
    """
    return sz_backend.refresh(backend)


# -- szsdlc's names, before and after its glossary (WI-0066) --------------------

def sdlc_root(backend) -> Path | None:
    """The backend's project sdlc root: where `.szsdlc/` is."""
    return backend.project_sdlc_root if hasattr(backend, "project_sdlc_root") else getattr(backend, "root", None)


def sdlc_store_dir(backend) -> Path:
    """The local directory the backend reads and writes; the sdlc root is inside it."""
    return backend.project_sdlc_store_dir if hasattr(backend, "project_sdlc_store_dir") else backend.store


def has_unsent_changes(backend) -> bool:
    """Whether the backend holds local changes it has not sent yet."""
    return backend.has_unsent_changes() if hasattr(backend, "has_unsent_changes") else backend.has_local_changes()


def store_for(path: Path):
    """The recorded project sdlc store whose store dir contains `path`, as its backend, or None."""
    lookup = getattr(sz_backend, "project_sdlc_store_for", None) or sz_backend.managed
    return lookup(path)


def asset_root_of(start: Path) -> Path:
    """The project asset root `start` belongs to."""
    lookup = getattr(sz_backend, "project_asset_root", None) or sz_backend.project_directory
    return lookup(start)


def _find_sdlc_root(start: Path) -> Path | None:
    lookup = getattr(sz_config, "find_project_sdlc_root", None) or sz_config.find_project_root
    return lookup(start)
