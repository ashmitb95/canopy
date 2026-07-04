"""Tests for canopy start (lazy feature create)."""
from __future__ import annotations

import pytest


def _ws(root):
    from canopy.workspace.workspace import Workspace
    from canopy.workspace.config import load_config
    return Workspace(load_config(root))


def test_start_creates_lazy_feature_zero_repos(canopy_toml_for_workspace):
    from canopy.actions.start import start
    from canopy.features.coordinator import FeatureCoordinator
    ws = _ws(canopy_toml_for_workspace)
    result = start(ws, "brand-new")
    assert result["feature"] == "brand-new"
    feats = FeatureCoordinator(ws)._load_features()
    assert feats["brand-new"]["repos"] == []


def test_start_zero_repos_creates_no_branches(canopy_toml_for_workspace):
    from canopy.actions.start import start
    from canopy.git import repo as git
    root = canopy_toml_for_workspace
    start(_ws(root), "brand-new")
    # lazy: NO branch created in any repo
    assert not git.branch_exists(root / "repo-a", "brand-new")
    assert not git.branch_exists(root / "repo-b", "brand-new")


def test_start_sets_active(canopy_toml_for_workspace):
    from canopy.actions.start import start
    from canopy.actions import active
    ws = _ws(canopy_toml_for_workspace)
    start(ws, "brand-new")
    assert active.get_active(ws) == "brand-new"


def test_start_with_declared_repos(canopy_toml_for_workspace):
    from canopy.actions.start import start
    from canopy.features.coordinator import FeatureCoordinator
    from canopy.git import repo as git
    root = canopy_toml_for_workspace
    ws = _ws(root)
    start(ws, "scoped", repos=["repo-a"])
    feats = FeatureCoordinator(ws)._load_features()
    assert feats["scoped"]["repos"] == ["repo-a"]
    assert git.branch_exists(root / "repo-a", "scoped")
    assert not git.branch_exists(root / "repo-b", "scoped")


def test_start_idempotent_on_existing(canopy_toml_for_workspace):
    from canopy.actions.start import start
    ws = _ws(canopy_toml_for_workspace)
    start(ws, "again")
    r2 = start(ws, "again")     # resume, not error/dup
    assert r2["status"] in ("resumed", "created")


def test_start_returns_context(canopy_toml_for_workspace):
    from canopy.actions.start import start
    ws = _ws(canopy_toml_for_workspace)
    result = start(ws, "ctxcheck")
    assert result["context"]["workspace"]["active_feature"] == "ctxcheck"
