"""The built wheel must carry the frontend: it is package data, and missing it ships a server with no UI."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

import szsdlc_ui_win95

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("static/index.html", "static/app.js", "static/refresh.js", "static/win95.css",
            "static/vendor/marked.umd.js", "static/vendor/LICENSE.marked",
            "static/vendor/purify.min.js", "static/vendor/LICENSE.dompurify")


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
def test_wheel_carries_the_frontend_and_the_version(tmp_path):
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_path), str(ROOT)],
                   check=True, capture_output=True)
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1
    assert f"-{szsdlc_ui_win95.__version__}-" in wheels[0].name
    names = set(zipfile.ZipFile(wheels[0]).namelist())
    missing = [f for f in REQUIRED if f"szsdlc_ui_win95/{f}" not in names]
    assert not missing, f"wheel is missing {missing}"
    assert not any(n.startswith("tests/") for n in names)
