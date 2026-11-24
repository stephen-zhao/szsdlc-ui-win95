"""`szsdlc-ui-win95`: serve one or many szsdlc projects to a browser, or export a snapshot."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

import szsdlc

from . import __version__, export
from .project import ProjectError
from .registry import Registry
from .server import make_server


def parse_project(arg: str) -> tuple[str, Path | None]:
    """`LOCATION` or `LOCATION::CODE_ROOT`. `::` clashes neither with a Windows drive nor with a URL scheme."""
    location, _, code = arg.partition("::")
    return location, (Path(code) if code else None)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="szsdlc-ui-win95",
                                 description="A Windows 95-styled viewer for szsdlc projects. Read-only.")
    ap.add_argument("projects", nargs="*", metavar="LOCATION[::CODE_ROOT]",
                    help="projects to serve: a folder inside one, or where a backend keeps one, "
                         "such as a git URL (default: the current directory)")
    ap.add_argument("--registered", action=argparse.BooleanOptionalAction, default=True,
                    help="open every store szsdlc keeps elsewhere, beside the projects named "
                         "(default: on; --no-registered opens only those named, or the current "
                         "directory). Never applies to --export")
    ap.add_argument("--projects-file", metavar="FILE",
                    help="YAML list of {location, code_root}: read at start, rewritten when a project is opened")
    ap.add_argument("--no-open", action="store_true", help="refuse File > Open project from the browser")
    ap.add_argument("--host", default="127.0.0.1", help="interface to bind (default: loopback only)")
    ap.add_argument("--port", type=int, default=8095, help="port (0 picks a free one; default 8095)")
    ap.add_argument("--open", action="store_true", help="open a browser once serving")
    ap.add_argument("--exclude", action="append", default=[], metavar="DIR", help="directory name to skip (repeatable)")
    ap.add_argument("--export", metavar="OUT.html", help="write a static, self-contained snapshot and exit")
    ap.add_argument("--fragment", action="store_true", help="with --export: omit the HTML document skeleton")
    ap.add_argument("--verbose", action="store_true", help="log every request")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__} (szsdlc {szsdlc.__version__})")
    return ap


def open_projects(args: argparse.Namespace) -> Registry:
    """Every project this launch serves, or exports.

    The projects file first, then every store szsdlc keeps elsewhere (unless
    `--no-registered`, and never for `--export`: a snapshot holds only what the
    command line names), then the projects named, or the current directory.

    The current directory opens beside the others whenever it is inside a
    project. As the implicit default it is skipped quietly when something else
    already opened; a location someone named, or `.` when nothing else opened,
    still says why it was skipped.
    """
    registry = Registry(args.exclude, Path(args.projects_file).expanduser() if args.projects_file else None)
    registry.load()
    if args.registered and not args.export:
        registry.add_registered()
    implicit = not args.projects
    for entry in args.projects or ["."]:
        location, code = parse_project(entry)
        try:
            registry.add(location, code)
        except ProjectError as err:
            if not (implicit and registry.projects):
                print(f"szsdlc-ui-win95: skipped {entry}: {err}", file=sys.stderr)
    return registry


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    registry = open_projects(args)

    if args.export:
        if not registry.projects:
            print("szsdlc-ui-win95: no project to export", file=sys.stderr)
            return 2
        out = export.write(registry, Path(args.export), fragment=args.fragment)
        print(f"wrote {out} ({out.stat().st_size // 1024} KiB, {len(registry.projects)} project(s))")
        return 0

    try:
        server = make_server(registry, args.host, args.port, allow_open=not args.no_open, verbose=args.verbose)
    except OSError as err:
        print(f"szsdlc-ui-win95: cannot listen on {args.host}:{args.port}: {err.strerror or err}. "
              "Try --port 0 for any free port.", file=sys.stderr)
        return 1
    host = "localhost" if args.host in ("127.0.0.1", "::1") else args.host
    url = f"http://{host}:{server.server_port}/"
    print(f"szsdlc-ui-win95 {__version__} (szsdlc {szsdlc.__version__}): {len(registry.projects)} project(s)")
    for pid, p in registry.projects.items():
        print(f"  {pid:<24} {p.store}  ({len(p.store_model)} entities; code root: {p.code_root or 'none'})")
        if p.update_warning:
            print(f"  {'':<24} note: {p.update_warning}")
    print(f"  serving {url}  (read-only; Ctrl-C to stop)")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
