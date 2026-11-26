"""Any location to a project, through szsdlc's own sdlc backends.

A **location** is whatever identifies a project: a folder on this computer, or a
place a szsdlc backend can keep one, such as a git URL. People type one into
Open project, or name one on the command line; which backend serves it is an
implementation detail worked out here.

Everything goes through szsdlc's own backend machinery, so cloning, the git
protocol allowlist, credential redaction and the store registry behave exactly
as they do for the CLI:

- a **folder** resolves as the CLI resolves it (the project sdlc store it is
  inside, or the backend its settings select), then `ensure` materializes the
  project sdlc store dir if it is not the folder itself;
- a **repository location** becomes the settings its backend already reads, and
  goes through `backend_class(type).from_settings` and `ensure`.

The viewer creates a project sdlc store dir only here, only when a person
opens a project, and only through the backend's own `ensure`. Viewing never
writes to a project.

The words are szsdlc's glossary (WI-0066). The `_sdlc_*` helpers below read its
new names when the installed szsdlc has them and the old ones before, so the
viewer runs on either without deprecation warnings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from szsdlc import backend as sz_backend
from szsdlc import config as sz_config
from szsdlc import errors as sz_errors
from szsdlc.settings import Setting

from .errors import ProjectError

SOURCE = "szsdlc-ui-win95 (Open project)"

#: A git remote: a URL in a transport git may use, or scp-like `user@host:path`.
#: `ext::` and other `helper::` forms are deliberately not matched (szsdlc
#: refuses them too).
GIT_REMOTE = re.compile(r"^(?:(?:https?|ssh|git|file)://\S+|[\w.+-]+@[\w.-]+:[^\s:]\S*)$", re.IGNORECASE)
USERINFO = re.compile(r"(://)[^/@\s]+@")
#: szsdlc names a project sdlc store dir it keeps itself `<name>-<10 hex digits>` (readable_name).
STORE_SUFFIX = re.compile(r"-[0-9a-f]{10}$")


def _git(text: str) -> dict[str, str] | None:
    """`URL[#branch]` as git backend settings."""
    url, _, branch = text.partition("#")
    if not GIT_REMOTE.match(url):
        return None
    return {"URL": url, **({"BRANCH": branch} if branch else {})}


#: How each backend reads a location, tried in order. Interpreting a location is
#: the one backend-specific step szsdlc does not offer yet; when its backends
#: can say for themselves, this table goes.
INTERPRETERS = (("git", _git),)


@dataclass(frozen=True)
class Resolved:
    backend: object
    root: Path
    #: The folder it was opened from, when the location is a local one.
    start: Path | None
    #: The location as given.
    location: str


def is_remote(text: str) -> bool:
    """True when `text` names a place a backend keeps a project, not a folder here."""
    text = str(text).strip()
    if Path(text).expanduser().is_dir():
        return False
    return any(interpret(text) is not None for _, interpret in INTERPRETERS)


def display(location: str) -> str:
    """A location fit to show: credentials and query strings removed."""
    return USERINFO.sub(r"\1***@", str(location)).split("?", 1)[0]


def store_name(store: Path) -> str:
    """A readable name for a project sdlc store dir szsdlc made, without its hash."""
    return STORE_SUFFIX.sub("", store.name) or store.name


def resolve(location) -> Resolved:
    """The backend and project root a location names, with the store materialized."""
    text = str(location).strip()
    if not text:
        raise ProjectError("No location given. Name a folder on this computer, or a repository URL.")
    if not is_remote(text):
        return _folder(text)
    for type_name, interpret in INTERPRETERS:
        found = interpret(text)
        if found is not None:
            return _kept_elsewhere(text, type_name, found)
    raise ProjectError(f"No szsdlc backend can open {display(text)}.")  # pragma: no cover - is_remote said one could


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


def _kept_elsewhere(text: str, type_name: str, found: dict[str, str]) -> Resolved:
    prefix = sz_backend.key_prefix(type_name)
    settings = {key: Setting(prefix + key, value, SOURCE, Path.home()) for key, value in found.items()}
    hint = re.sub(r"\.git$", "", found.get("URL", text).rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]) or "project"
    try:
        cls = sz_backend.backend_class(type_name)
        backend = cls.from_settings(settings, sz_backend.Context(hint, sz_backend.home(), None))
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
