"""Tests for the PR-overlay offline cache (prs.json)."""
from __future__ import annotations

import json


def test_write_then_read_roundtrip(canopy_toml):
    from canopy.workspace.workspace import Workspace
    from canopy.workspace.config import load_config
    from canopy.actions import prs_cache
    ws = Workspace(load_config(canopy_toml))
    data = {"DOC-1": {"repos": {"repo-a": {"number": 5, "state": "open"}}}}
    prs_cache.write(ws, data)
    got = prs_cache.read(ws)
    assert got["features"] == data
    assert "fetched_at" in got


def test_read_missing_returns_none(canopy_toml):
    from canopy.workspace.workspace import Workspace
    from canopy.workspace.config import load_config
    from canopy.actions import prs_cache
    ws = Workspace(load_config(canopy_toml))
    assert prs_cache.read(ws) is None


def test_read_corrupt_returns_none(canopy_toml):
    from canopy.workspace.workspace import Workspace
    from canopy.workspace.config import load_config
    from canopy.actions import prs_cache
    ws = Workspace(load_config(canopy_toml))
    (ws.config.root / ".canopy" / "state").mkdir(parents=True, exist_ok=True)
    (ws.config.root / ".canopy" / "state" / "prs.json").write_text("{bad")
    assert prs_cache.read(ws) is None
