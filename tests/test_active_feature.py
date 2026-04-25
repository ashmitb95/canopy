"""Tests for canopy.actions.active_feature — read/write/clear/staleness."""
import json
from pathlib import Path

import pytest

from canopy.actions.active_feature import (
    ActiveFeature, clear_active, is_active, paths_for_feature,
    read_active, write_active,
)
from canopy.workspace.config import RepoConfig, WorkspaceConfig
from canopy.workspace.workspace import Workspace


def _ws(workspace_dir, repos=("api", "ui")) -> Workspace:
    return Workspace(WorkspaceConfig(
        name="t",
        repos=[RepoConfig(name=r, path=f"./{r}", role="x", lang="x") for r in repos],
        root=workspace_dir,
    ))


# ── read/write/clear ────────────────────────────────────────────────────

def test_read_returns_none_when_file_missing(workspace_dir):
    ws = _ws(workspace_dir)
    assert read_active(ws) is None


def test_write_then_read_roundtrips(workspace_dir):
    ws = _ws(workspace_dir)
    api = workspace_dir / "api"
    ui = workspace_dir / "ui"
    entry = write_active(ws, "doc-1001", {"api": str(api), "ui": str(ui)})
    assert entry.feature == "doc-1001"
    assert entry.activated_at.endswith("Z")
    again = read_active(ws)
    assert again is not None
    assert again.feature == "doc-1001"
    assert set(again.per_repo_paths.keys()) == {"api", "ui"}


def test_clear_removes_file(workspace_dir):
    ws = _ws(workspace_dir)
    write_active(ws, "doc-1001", {"api": str(workspace_dir / "api")})
    assert clear_active(ws) is True
    assert read_active(ws) is None


def test_clear_only_if_feature_matches(workspace_dir):
    ws = _ws(workspace_dir)
    write_active(ws, "doc-1001", {"api": str(workspace_dir / "api")})
    # Wrong feature → no-op
    assert clear_active(ws, only_if_feature="other") is False
    assert read_active(ws) is not None
    # Right feature → clear
    assert clear_active(ws, only_if_feature="doc-1001") is True
    assert read_active(ws) is None


def test_is_active_predicate(workspace_dir):
    ws = _ws(workspace_dir)
    assert is_active(ws, "doc-1001") is False
    write_active(ws, "doc-1001", {"api": str(workspace_dir / "api")})
    assert is_active(ws, "doc-1001") is True
    assert is_active(ws, "other") is False


# ── previous_feature tracking ────────────────────────────────────────────

def test_previous_feature_bumps_on_switch(workspace_dir):
    ws = _ws(workspace_dir)
    api = workspace_dir / "api"
    write_active(ws, "doc-1001", {"api": str(api)})
    write_active(ws, "doc-2002", {"api": str(api)})
    entry = read_active(ws)
    assert entry.feature == "doc-2002"
    assert entry.previous_feature == "doc-1001"


def test_writing_same_feature_keeps_previous(workspace_dir):
    """Re-activating the same feature shouldn't promote it to its own previous."""
    ws = _ws(workspace_dir)
    api = workspace_dir / "api"
    write_active(ws, "doc-1001", {"api": str(api)})
    write_active(ws, "doc-2002", {"api": str(api)})  # previous = doc-1001
    write_active(ws, "doc-2002", {"api": str(api)})  # same feature again
    entry = read_active(ws)
    assert entry.feature == "doc-2002"
    assert entry.previous_feature == "doc-1001"


# ── staleness ───────────────────────────────────────────────────────────

def test_stale_paths_return_none(workspace_dir):
    """If a recorded path no longer exists, treat as not active."""
    ws = _ws(workspace_dir)
    write_active(ws, "doc-1001", {
        "api": str(workspace_dir / "api"),
        "ui":  "/nonexistent/path/that/does/not/exist",
    })
    assert read_active(ws) is None
    assert is_active(ws, "doc-1001") is False


def test_paths_for_feature_returns_paths_when_active(workspace_dir):
    ws = _ws(workspace_dir)
    api = workspace_dir / "api"
    write_active(ws, "doc-1001", {"api": str(api)})
    paths = paths_for_feature(ws, "doc-1001")
    assert paths == {"api": str(api)}


def test_paths_for_feature_returns_none_for_other_feature(workspace_dir):
    ws = _ws(workspace_dir)
    write_active(ws, "doc-1001", {"api": str(workspace_dir / "api")})
    assert paths_for_feature(ws, "other-feature") is None
