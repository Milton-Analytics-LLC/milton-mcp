from __future__ import annotations

import importlib
import importlib.metadata
import re
import subprocess
import sys
from pathlib import Path

import milton_mcp

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def pyproject_version() -> str:
    match = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(), re.MULTILINE)
    assert match, "no version in pyproject.toml"
    return match.group(1)


def test_version_matches_pyproject():
    assert milton_mcp.__version__ == pyproject_version()


def test_cli_reports_the_package_version():
    out = subprocess.run(
        [sys.executable, "-m", "milton_mcp", "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert out == f"milton-mcp {pyproject_version()}"


def test_version_comes_from_the_installed_metadata(monkeypatch):
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "9.9.9" if name == "milton-mcp" else "")
    try:
        assert importlib.reload(milton_mcp).__version__ == "9.9.9"
    finally:
        monkeypatch.undo()
        importlib.reload(milton_mcp)


def test_version_without_installed_metadata(monkeypatch):
    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)
    try:
        assert importlib.reload(milton_mcp).__version__ == "0+unknown"
    finally:
        monkeypatch.undo()
        importlib.reload(milton_mcp)
