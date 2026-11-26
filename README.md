# szsdlc-ui-win95

A browser viewer for [szsdlc](https://github.com/stephen-zhao/szsdlc) projects,
styled like a 1995 desktop and built around one rule: **it names no entity
type.** Every window is assembled from what a project's types can *do* (their
capability flags, fields, workflow and relations), so a project that renames or
replaces all of its types still gets a full viewer.

It reads every project through szsdlc itself: backend resolution, the merged
config, the entity store, the relation graph and the derived attributes. There
is no second loader to drift from the real one.

## Install and run

Needs Python 3.12+.

```sh
pip install zhaostephen-szsdlc-ui-win95     # or: uv tool install zhaostephen-szsdlc-ui-win95

cd my-project && szsdlc-ui-win95 --open      # this project, and every project sdlc store szsdlc has recorded
```

It serves `http://localhost:8095/`, on loopback only, and never writes to a
project.

**What opens by default:** every project sdlc store szsdlc has recorded (git
clones and `dir` directories), plus the project you are standing in, if any.
Projects named on the command line open beside them. `--no-registered` opens
only the projects named, or the current directory. A plain folder opened with
File → Open project… is still forgotten on restart unless you use
`--projects-file`. `--export` never adds recorded stores: a snapshot holds only
what the command line names.

Other ways to run it:

```sh
szsdlc-ui-win95 ~/code/app ~/code/lab                 # several projects in one viewer
szsdlc-ui-win95 https://github.com/org/tracker.git    # a project kept in a git repository
szsdlc-ui-win95 ~/sdlc-store::~/code/app              # ~/code/app is the project asset root, for its documents
szsdlc-ui-win95 --no-registered                       # only the current project, not the recorded stores
szsdlc-ui-win95 --projects-file ~/.config/szsdlc/viewer.yml   # remembered projects
szsdlc-ui-win95 ~/code/app --export app.html          # one self-contained HTML snapshot
szsdlc-ui-win95 --port 0                              # any free port
```

A project can be opened from **any location, whatever backend keeps it**: on
the command line, in the projects file, or with File → Open project…:

- **a folder on this computer**: a project, or any folder inside one. When a
  repository's settings select a `git` or `dir` sdlc backend, the project sdlc
  store dir it names is used (created or cloned if needed), and the repository
  becomes the **project asset root**, where documents outside the project sdlc
  root are found;
- **a repository URL** holding the project (`https://host/org/repo.git`,
  `git@host:org/repo.git`, optionally `#branch`). It is cloned the first time,
  exactly as szsdlc's git backend clones it.

A document is labelled by the root it comes from: **SDLC** (the project sdlc
root, with the records) or **Assets** (a project asset root). These are the
words of szsdlc's glossary.

Opening a project it already has brings a clone up to date, but only when that
clone has nothing unsent; otherwise the clone is shown as it is. Viewing never
writes to a project.

**Refresh** (View → Refresh, F5, or the taskbar's project menu) takes the sdlc
backend's latest, through szsdlc's own `refresh`. It sends nothing
and merges nothing, and every open window redraws in place. A project kept in a
folder here is simply read again. If the copy has unsent changes, Refresh asks
before replacing them, and szsdlc keeps what it replaces.

The project on screen also **refreshes itself in the background**, every minute
by default. The ▾ beside the Refresh button sets how often (Off, 30 seconds, 1
minute or 5 minutes, per browser, the same in every window) and shows it, `1m`,
while it is on. It only runs while the tab is visible, and a project
you switch to is refreshed once on arrival. A background refresh never replaces
unsent changes: it skips the project and says so in the status bar. It redraws
only when something arrived, and never in the middle of a drag, an open menu or
typing. It also backs off, up to 15 minutes, while it cannot reach where the
project is kept.

## What it does

- **One viewer, many projects.** A project button on the taskbar switches
  between them. Each project keeps its own windows, and File → Open project…
  adds one at runtime (`--no-open` turns that off).
- **Explorer windows, as many as you like.** Each has a tree, Back, Forward
  and Up, and an address bar that is a breadcrumb or, when clicked, a typed path
  (`szsdlc:\Epics\EPIC-0007`, or just `wi-29`). The tree nests items under the
  configured parent relation and gives each tag a folder; its pane is resizable.
- **Items are pages.** Their tabs follow traits: Children for a parent,
  Overview (the description beside details, derived attributes and
  connections), a checklist view of the progress artifact, one tab per Markdown
  artifact, a node-and-edge relations graph, and documents in tree, out of tree
  and on the web.
- **Every collection has three views,** Details, Board and Graph. The board
  groups by status, type, parent, roadmap horizon, tag or any declared field;
  the roadmap is a board grouped by horizon, with dependency arrows.
- **Hide closed,** everywhere in a window: every item in a status declared
  `terminal` (done, dropped and the like).
- **Markdown, properly.** GitHub-flavoured Markdown, sanitised, with heading
  anchors, ID auto-linking, a Rendered/Source toggle and Copy raw on every
  document.
- **Context menus,** as in Windows 95: right-click, Shift+F10, the Menu key or
  a long press on an item, folder, document, relation, tab, breadcrumb, window
  title or the desktop. Menus offer Open in new window, Copy ID, Copy link and
  Properties, and Alt+Space opens a window's own menu. Text fields and document
  text keep the browser's menu. A copied link opens what it names:
  `#<project>--WI-0029`, `#<project>--type:EPIC`, `#<project>--doc:store:<path>`.

## API

The server is a thin JSON API over szsdlc, served by FastAPI on uvicorn; see
the docstring of [`server.py`](src/szsdlc_ui_win95/server.py) for the routes,
or `/api/openapi.json` on a running viewer for the API described. The centrepiece is
`/api/p/<project>/schema`, the **schema descriptor**: each type's flags, fields,
workflow (states with `terminal`, `abandoned` and gates), artifacts, derived
attributes and relations, as szsdlc resolved them.

## Develop

```sh
uv sync --all-extras --dev
make test            # pytest: API, security, export and frontend checks
make test-coverage
make serve           # run against the project above the current directory
```

The frontend is plain HTML, CSS and JS in
[`src/szsdlc_ui_win95/static/`](src/szsdlc_ui_win95/static/), with no build step;
`marked` and `DOMPurify` are vendored with their licences.

## Releasing

The same scheme as the other stephen-zhao Python repositories:

- Every push to `main` runs **Bump Version**. It bumps the part named by the
  merged pull request's label (`bumpversion=major|minor|patch|none`; no label
  means patch), commits `Bump version: X → Y` and tags `vY`.
- That run triggers **Publish to PyPI**, which builds the one new tag, checks
  that the tag, the tree's `current_version` and every artifact agree, publishes
  through PyPI trusted publishing, and creates a GitHub pre-release.
- To publish an existing tag by hand, run Publish with `workflow_dispatch` and
  name the exact tag.

## Where the work is tracked

This repository's SDLC lives in
[szsdlc-szsdlc](https://github.com/stephen-zhao/szsdlc-szsdlc), alongside
szsdlc's own: [`.claude/settings.json`](.claude/settings.json) points szsdlc's
`git` backend at it. The design and its rationale are **SPK-0005** there.

## Licence

MIT. See [LICENSE](LICENSE).
