"""Tests for canopy.actions.switch — three-case context activator."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from canopy.actions.active_feature import is_active, read_active
from canopy.actions.errors import BlockerError
from canopy.actions.switch import switch
from canopy.workspace.config import RepoConfig, WorkspaceConfig
from canopy.workspace.workspace import Workspace


def _ws(workspace_dir, repos=("api", "ui")) -> Workspace:
    return Workspace(WorkspaceConfig(
        name="t",
        repos=[RepoConfig(name=r, path=f"./{r}", role="x", lang="x") for r in repos],
        root=workspace_dir,
    ))


def _features_file(workspace_dir, payload):
    canopy_dir = workspace_dir / ".canopy"
    canopy_dir.mkdir(exist_ok=True)
    (canopy_dir / "features.json").write_text(json.dumps(payload))


def _git(args, cwd):
    subprocess.run(
        ["git"] + args, cwd=cwd, check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )


# ── Case 1: feature has worktrees → mark active, no realign ─────────────

def test_switch_with_existing_worktrees(workspace_dir):
    """workspace_dir has api/ and ui/ on main; create a feature with worktrees,
    then switch to it. Expect mode=worktree, no realign call needed."""
    from canopy.features.coordinator import FeatureCoordinator
    ws = _ws(workspace_dir)
    coord = FeatureCoordinator(ws)
    coord.create("wt-feat", repos=["api", "ui"], use_worktrees=True)

    result = switch(ws, "wt-feat")
    assert result["feature"] == "wt-feat"
    assert result["mode"] == "worktree"
    assert "realign" not in result
    # Worktree paths should be the .canopy/worktrees/wt-feat/<repo> dirs
    for repo in ("api", "ui"):
        assert ".canopy/worktrees/wt-feat" in result["per_repo_paths"][repo]
    assert is_active(ws, "wt-feat")


# ── Case 2: feature is main-tree only → realign + mark active ───────────

def test_switch_main_tree_calls_realign(workspace_with_feature):
    """workspace_with_feature has 'auth-flow' as a main-tree branch in both repos."""
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _ws(workspace_with_feature)
    # Move ui to main so realign has work to do
    _git(["checkout", "main"], cwd=workspace_with_feature / "ui")

    result = switch(ws, "auth-flow")
    assert result["feature"] == "auth-flow"
    assert result["mode"] == "main_tree"
    assert "realign" in result
    assert result["realign"]["aligned"] is True
    # Per-repo paths point at main repo dirs (not under .canopy/worktrees/)
    for repo, path in result["per_repo_paths"].items():
        assert ".canopy/worktrees" not in path
    assert is_active(ws, "auth-flow")


def test_switch_main_tree_no_op_when_already_aligned(workspace_with_feature):
    """If already on the right branch, realign reports already_aligned."""
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _ws(workspace_with_feature)
    result = switch(ws, "auth-flow")
    assert result["mode"] == "main_tree"
    for r in result["realign"]["repos"].values():
        assert r["status"] == "already_aligned"


# ── Case 3a: no worktrees + missing branches + --create-worktrees ──────

def test_switch_creates_worktrees_when_flagged(workspace_dir):
    """No prior worktrees, no main branch — but with create_worktrees=True,
    canopy creates them and activates."""
    _features_file(workspace_dir, {
        "fresh-feat": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _ws(workspace_dir)
    result = switch(ws, "fresh-feat", create_worktrees=True)
    assert result["mode"] == "worktree"
    assert result.get("worktrees_created") is True
    for repo in ("api", "ui"):
        assert ".canopy/worktrees/fresh-feat" in result["per_repo_paths"][repo]


def test_switch_creates_worktrees_for_fresh_unregistered_name(workspace_dir):
    """--create-worktrees should accept a brand-new feature name that has
    no features.json entry and doesn't exist as a branch anywhere."""
    ws = _ws(workspace_dir)
    result = switch(ws, "brand-new-feat", create_worktrees=True)
    assert result["feature"] == "brand-new-feat"
    assert result["mode"] == "worktree"
    assert result.get("worktrees_created") is True
    for repo in ("api", "ui"):
        assert ".canopy/worktrees/brand-new-feat" in result["per_repo_paths"][repo]


# ── Case 3b: no worktrees + missing branches + no flag → BlockerError ──

def test_switch_blocks_when_nothing_exists_without_flag(workspace_dir):
    _features_file(workspace_dir, {
        "ghost-feat": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _ws(workspace_dir)
    with pytest.raises(BlockerError) as exc_info:
        switch(ws, "ghost-feat")
    err = exc_info.value
    assert err.code == "no_active_state"
    assert "ghost-feat" in err.what
    # Suggested fix: --create-worktrees
    actions = [(fa.action, fa.args) for fa in err.fix_actions]
    assert any(a == "switch" and args.get("create_worktrees") for a, args in actions)


# ── Activation persists through reads ──────────────────────────────────

def test_switch_writes_active_feature_file(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _ws(workspace_with_feature)
    switch(ws, "auth-flow")
    state_file = workspace_with_feature / ".canopy" / "state" / "active_feature.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert data["feature"] == "auth-flow"
    assert "per_repo_paths" in data


def test_switch_swaps_previous_feature(workspace_with_feature):
    """Two switches → second has previous_feature = first."""
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
        "second-feat": {"repos": ["api"], "status": "active"},
    })
    ws = _ws(workspace_with_feature)
    from canopy.git import repo as git
    git.create_branch(workspace_with_feature / "api", "second-feat")

    switch(ws, "auth-flow")
    result2 = switch(ws, "second-feat")
    assert result2["previous_feature"] == "auth-flow"


# ── Unknown feature ────────────────────────────────────────────────────

def test_switch_unknown_feature_raises(workspace_with_feature):
    ws = _ws(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        switch(ws, "no-such-thing")
    assert exc_info.value.code == "unknown_alias"
