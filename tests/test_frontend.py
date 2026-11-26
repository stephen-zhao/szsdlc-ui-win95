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


def test_the_terminal_status_toggle_says_closed():
    """It hides every terminal status, not only done (WI-0050); the saved key is kept."""
    assert "'Hide closed'" in APP and "done hidden" not in APP and "not done.'" not in APP
    assert "store.get('hideDone')" in APP


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


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_refresh_scheduler_with_a_fake_clock():
    """Pause, skip, queue and backoff (WI-0056), in node with a fake clock."""
    script = Path(__file__).with_name("refresh.test.js")
    result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_scheduler_names_no_entity_type():
    script = (STATIC / "refresh.js").read_text(encoding="utf-8")
    literals = re.findall(r"""['"`]([A-Za-z_]+)['"`]""", script)
    assert not sorted(set(literals) & set(DEFAULT_TYPES))


def _playwright_available() -> bool:
    if shutil.which("node") is None:
        return False
    return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode == 0


def test_smoke_in_a_real_browser(project, asset_root):
    if not _playwright_available():
        # CI's browser job sets this, so a broken install fails instead of passing as a skip.
        if os.environ.get("SZUI_REQUIRE_BROWSER"):
            pytest.fail("SZUI_REQUIRE_BROWSER is set but node cannot require('playwright')")
        pytest.skip("node playwright is not installed")
    registry = Registry()
    registry.add(project, asset_root)
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


SNAPSHOT_CHECK = r"""
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1366, height: 860 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.addInitScript(() => { try { localStorage.setItem('szv:welcome', '0'); } catch (e) { /* ignore */ } });
  await page.goto(process.argv[2]);
  await page.waitForSelector('.window.active .toolbar');
  const buttons = await page.$$('.toolbar button[title="Refresh (F5)"]');
  await browser.close();
  if (errors.length) { console.error(errors.join(' | ')); process.exit(1); }
  if (buttons.length) { console.error('a snapshot shows a Refresh button'); process.exit(1); }
  console.log('snapshot ok');
})().catch((e) => { console.error(e.message); process.exit(1); });
"""


def test_a_snapshot_has_no_refresh_button(project, asset_root, tmp_path):
    """A snapshot has nothing to refresh from (WI-0055)."""
    if not _playwright_available():
        if os.environ.get("SZUI_REQUIRE_BROWSER"):
            pytest.fail("SZUI_REQUIRE_BROWSER is set but node cannot require('playwright')")
        pytest.skip("node playwright is not installed")
    from szsdlc_ui_win95 import export

    registry = Registry()
    registry.add(project, asset_root)
    out = export.write(registry, tmp_path / "snap.html")
    script = tmp_path / "check.js"
    script.write_text(SNAPSHOT_CHECK, encoding="utf-8")
    result = subprocess.run(["node", str(script), out.as_uri()], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_visible_text_speaks_the_glossary():
    """WI-0069: no user-visible string says "code root", "in tree" or "where the project is kept"."""
    retired = re.compile(r"code root|in tree|out of tree|where (?:the project|it) is kept", re.IGNORECASE)
    for name in ("app.js", "index.html"):
        text = (STATIC / name).read_text(encoding="utf-8")
        strings = re.findall(r"'[^'\n]*'|\"[^\"\n]*\"|`[^`\n]*`", text)
        hits = [s for s in strings if retired.search(s)]
        assert not hits, f"{name}: {hits[:3]}"
