"""The frontend has no build step, so these checks stand in for one."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from szsdlc_ui_win95.registry import Registry
from szsdlc_ui_win95.server import STATIC, make_server

APP = (STATIC / "app.js").read_text(encoding="utf-8")
DEFAULT_TYPES = ("idea", "epic", "requirement", "spike", "work_item", "decision", "IDEA", "EPIC", "REQ", "SPK", "WI", "ADR")


def test_app_names_no_entity_type():
    """Rule 1 of AGENTS.md: behaviour follows the descriptor, never a type name."""
    literals = re.findall(r"""['"`]([A-Za-z_]+)['"`]""", APP)
    assert not sorted(set(literals) & set(DEFAULT_TYPES))


def test_index_has_a_token_slot_and_loads_only_local_scripts():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<meta name="viewer-token" content="">' in index
    assert not re.search(r"<script[^>]+src=\"https?:", index)


def test_vendored_code_ships_with_its_licences():
    vendor = STATIC / "vendor"
    for lib, licence in (("marked.umd.js", "LICENSE.marked"), ("purify.min.js", "LICENSE.dompurify")):
        assert (vendor / lib).is_file() and (vendor / licence).is_file()


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_app_parses():
    subprocess.run(["node", "--check", str(STATIC / "app.js")], check=True)


def _playwright_available() -> bool:
    if shutil.which("node") is None:
        return False
    return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode == 0


def test_smoke_in_a_real_browser(project, code_root):
    if not _playwright_available():
        # CI's browser job sets this, so a broken install fails instead of passing as a skip.
        if os.environ.get("SZUI_REQUIRE_BROWSER"):
            pytest.fail("SZUI_REQUIRE_BROWSER is set but node cannot require('playwright')")
        pytest.skip("node playwright is not installed")
    registry = Registry()
    registry.add(project, code_root)
    server = make_server(registry, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        script = Path(__file__).with_name("smoke.js")
        result = subprocess.run(["node", str(script), f"http://localhost:{server.server_port}/"],
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        server.server_close()
