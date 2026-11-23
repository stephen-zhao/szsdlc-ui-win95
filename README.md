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

cd my-project && szsdlc-ui-win95 --open      # the project you are standing in
```

It serves `http://localhost:8095/`, on loopback only, and never writes to a
project. Other ways to run it:

```sh
szsdlc-ui-win95 ~/code/app ~/code/lab                 # several projects in one viewer
szsdlc-ui-win95 https://github.com/org/tracker.git    # a project kept in a git repository
szsdlc-ui-win95 ~/sdlc-store::~/code/app              # resolve out-of-tree docs against ~/code/app
szsdlc-ui-win95 --registered                          # every store szsdlc keeps elsewhere
szsdlc-ui-win95 --projects-file ~/.config/szsdlc/viewer.yml   # remembered projects
szsdlc-ui-win95 ~/code/app --export app.html          # one self-contained HTML snapshot
szsdlc-ui-win95 --port 0                              # any free port
```

A project can be opened from **any location, whatever backend keeps it**: on
the command line, in the projects file, or with File → Open project…:

- **a folder on this computer**: a project, or any folder inside one. For a
  code repository whose settings keep its project elsewhere (a `git` or `dir`
  backend), that store is used, created or cloned if needed, and the repository
  becomes the code root for out-of-tree documents;
- **where a project is kept**, such as a git URL (`https://host/org/repo.git`,
  `git@host:org/repo.git`, optionally `#branch`). It is cloned the first time,
  exactly as szsdlc's git backend clones it.

Opening a project it already has brings a clone up to date, but only when that
clone has nothing unsent; otherwise the clone is shown as it is. Viewing never
writes to a project.

## Configuration

Settings for how the viewer runs live in a TOML file that you edit yourself.
The viewer reads it once at startup, never writes it, and offers no way to
change it, so a change takes effect on the next start.

| Platform | File |
|---|---|
| Linux and others | `$XDG_CONFIG_HOME/szsdlc-ui-win95/config.toml` (else `~/.config/…`) |
| macOS | `~/Library/Application Support/szsdlc-ui-win95/config.toml` |
| Windows | `%APPDATA%\szsdlc-ui-win95\config.toml` |

`--config FILE` reads another file instead. Every key is optional:

```toml
host = "127.0.0.1"      # --host
port = 8095             # --port; 0 picks a free one
open_project = true     # false is --no-open
exclude = ["vendor"]    # --exclude: directory names to skip

[ui]
scheme = "system"       # system, light or dark: what a browser shows until
                        # someone picks a scheme in Display Properties
```

A flag on the command line wins over the file, and the file wins over the
built-in default; `--exclude` replaces the file's list rather than adding to it.
With no file, the defaults apply. A file that cannot be read, or has an
unknown key or a wrong value, stops the viewer from starting, with a message
naming the file, the key and the fix. Startup prints which file it read.

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

## API

The server is a thin, read-only JSON API over szsdlc; see the docstring of
[`server.py`](src/szsdlc_ui_win95/server.py) for the routes. The centrepiece is
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
