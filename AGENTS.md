# Working in szsdlc-ui-win95

## Where the work is tracked

Work is tracked with szsdlc, in
[szsdlc-szsdlc](https://github.com/stephen-zhao/szsdlc-szsdlc), which also holds
szsdlc's own SDLC. `.claude/settings.json` points szsdlc's `git` backend there,
so `szsdlc` commands run in this repository act on that store. The design is
SPK-0005; follow-up work is under EPIC-0011.

**Tracking changes go to szsdlc-szsdlc's `main` directly, never to a branch.**
szsdlc allocates an id by scanning for the highest existing number, so two
branches of the store each claim the next id independently, and merging them
produces two entities with the same id. Rebase onto `main`, run
`szsdlc validate`, and push to `main`.

Follow the rules in szsdlc's own
AGENTS.md: change status through the CLI, author a relation on one side only,
and capture rather than discuss and forget.

## The rules of this codebase

1. **Name no entity type.** Neither the frontend nor the server may compare
   against `work_item`, `epic`, `WI` or any other type name or prefix. Behaviour
   follows the schema descriptor: capability flags, fields, workflow,
   `parent_relation`, `dependency_relation`. A check for this is in the tests.
2. **Never re-implement szsdlc.** Loading, layouts, the graph, inverses,
   derived attributes and backend resolution come from the library. If the
   viewer needs a fact szsdlc does not expose, the fix belongs in szsdlc, not in a
   second parser here.
3. **Read-only; a store is created only when a person opens a project.**
   Opening takes any location (a folder here, or where a backend keeps the
   project, such as a git URL) and goes through `locations.py`, which drives
   szsdlc's own backends: `resolve`/`from_settings`, then `ensure`, which may
   clone. Nothing else may create a store, and viewing never writes to one. A
   clone is updated on open only when it has nothing unsent, and Refresh
   replaces unsent state only after the person confirms, and only through
   szsdlc's own `refresh`. Phase 2 writes must
   go through szsdlc's own operations, never a file write, so every gate still
   applies.
6. **The backend is an implementation detail.** No UI names a backend or asks
   for one. Interpreting a location is the one backend-specific step, and it
   lives only in `locations.INTERPRETERS`.
4. **The look is a skin; the UX decides.** Windows 95 chrome (title bars,
   raised frames) is for windows. Inside a window, use plain dividers and the
   window face.
5. **No build step.** The frontend stays plain HTML, CSS and JS. Third-party
   code is vendored with its licence, never fetched at runtime.

## Layers and naming (standard practice)

These apply to new code now, and existing code moves to them gradually.

**Layers.** The first split is by layer, the second by domain.
- **Onion order, inside out:**
  1. **The core:** the model and services, with no IO-framework dependencies. Today the model is `errors`, `documents`, `locations`, `project` and `registry` (they read projects through szsdlc), and the services are `services/`: what the viewer does, as plain Python.
  2. **The interfaces:** IO-touching code and interface types: `web/` (FastAPI, and its request and response types) and `export.py`.
  3. **The composition root,** which wires the layers together: `server.py` (with `cli.py` as the command on top).
- **A strict DAG between layers:** a layer imports only layers inside it.
- **Inside a layer,** files are split by domain and may import one another.
- **The check:** `tests/test_layers.py` holds both rules, and fails if anything outside `web/` imports FastAPI, Starlette, uvicorn or pydantic.

**Dependency injection is framework-agnostic.**
- **Constructor injection:** dependencies arrive through constructors (for example, `ViewerService(registry, allow_open=…)`), and the composition root builds them.
- **Framework injection stays at the edge:** a framework's own injection may be used only inside that framework's layer. FastAPI's `Depends` lives in `web/` and never reaches the services or the core.

**Middleware.** Avoid Starlette's `BaseHTTPMiddleware`.
- **First choice:** a `Depends` dependency.
- **Otherwise,** where a dependency can't do it or would be awkward, write raw ASGI middleware. For example, `web/asgi.py` hardens every response, which must include 404s and the API description.

**Names.** An interface's request and response types are its **wire model**, kept in a `wire_model` module (`web/wire_model.py`), not "DTOs"; translating between it and the service lives in `map_requests` and `map_responses`, so the routes stay routes. Operation `Foo` takes a `FooRequest` and returns a `FooResponse` (`OpenProjectRequest`, `RefreshResponse`, `ListProjectsResponse`). A type nested inside them is named for what it is (`ProjectSummary`).

## Layout

| Path | Role |
|---|---|
| `src/szsdlc_ui_win95/project.py` | One project through szsdlc; the schema descriptor and every payload |
| `src/szsdlc_ui_win95/locations.py` | Any location to a materialized backend, through szsdlc |
| `src/szsdlc_ui_win95/documents.py` | Document references, root containment, reading |
| `src/szsdlc_ui_win95/registry.py` | The projects one viewer serves |
| `src/szsdlc_ui_win95/services/` | The viewer's operations, framework-free: `ViewerService` and its typed refusals |
| `src/szsdlc_ui_win95/web/` | HTTP: the FastAPI routes (`app.py`), the wire model (`wire_model.py`), the mappers between HTTP and the service (`map_requests.py` in: the write guard, validation, service arguments; `map_responses.py` out: JSON and problems), the hardening middleware (`asgi.py`) and the uvicorn server (`server.py`) |
| `src/szsdlc_ui_win95/server.py` | The composition root: the service, the web app and the server, wired together |
| `src/szsdlc_ui_win95/export.py` | The static snapshot |
| `src/szsdlc_ui_win95/cli.py` | The `szsdlc-ui-win95` command |
| `src/szsdlc_ui_win95/static/` | The frontend |
| `tests/` | Fixture projects are built with szsdlc's own CLI, so they are always valid |
