"""Tests for canopy.actions.switch — Wave 2.9 canonical-slot model.

Replaces the older 3-case context-activator behavior. New surface:
``switch(Y, release_current=False, no_evict=False, evict=None)``.

Coverage:
  - active rotation (default): X canonical → X warm worktree, Y warm → Y canonical
  - wind-down mode: X goes cold (with feature-tagged stash if dirty)
  - cap-reached blocker (active rotation past warm slot cap)
  - LRU eviction with auto-stash when cap fires + auto-pick
  - explicit ``evict=<feature>`` overrides LRU pick
  - no-op when main is already on the target branch
  - missing branch: created from default
  - lazy 2.9 migration on first switch
  - reverse evacuation: Y was warm, must be removed before main can adopt it
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from canopy.actions.active_feature import is_active, read_active
from canopy.actions.errors import BlockerError
from canopy.actions.evacuate import warm_features, warm_worktree_path
from canopy.actions.switch import switch
from canopy.git import repo as git
from canopy.workspace.config import RepoConfig, WorkspaceConfig
from canopy.workspace.workspace import Workspace


def _ws(workspace_dir, repos=("api", "ui"), max_worktrees=0) -> Workspace:
    return Workspace(WorkspaceConfig(
        name="t",
        repos=[RepoConfig(name=r, path=f"./{r}", role="x", lang="x") for r in repos],
        root=workspace_dir,
        max_worktrees=max_worktrees,
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


def _make_feature_branches(workspace_dir, name, repos=("api", "ui")):
    """Create branch ``name`` (with one commit) in each repo."""
    for r in repos:
        _git(["checkout", "-q", "-b", name], cwd=workspace_dir / r)
        _git(["commit", "--allow-empty", "-qm", f"feat:{name}"], cwd=workspace_dir / r)
        _git(["checkout", "-q", "main"], cwd=workspace_dir / r)


# ── active rotation: the default flow ───────────────────────────────────

class TestActiveRotation:
    def test_first_switch_makes_feature_canonical(self, workspace_with_feature):
        """auth-flow branch exists; switch promotes it to canonical."""
        ws = _ws(workspace_with_feature)
        result = switch(ws, "auth-flow")

        assert result["feature"] == "auth-flow"
        assert result["mode"] == "active_rotation"
        # Both repos now on auth-flow
        for repo in ("api", "ui"):
            assert git.current_branch(workspace_with_feature / repo) == "auth-flow"
        # Active state recorded
        active = read_active(ws)
        assert active is not None
        assert active.feature == "auth-flow"
        assert active.last_touched.get("auth-flow")

    def test_switch_evacuates_previous_canonical_to_warm(self, workspace_with_feature):
        """X canonical → X warm worktree when Y becomes canonical."""
        # Create a second feature so we can rotate
        _make_feature_branches(workspace_with_feature, "feat-b")
        ws = _ws(workspace_with_feature)

        # First switch to auth-flow (becomes canonical)
        switch(ws, "auth-flow")
        # Then switch to feat-b — auth-flow should evacuate to warm
        result = switch(ws, "feat-b")

        assert result["mode"] == "active_rotation"
        assert result["previously_canonical"] == "auth-flow"

        # auth-flow now lives in a warm worktree
        for repo in ("api", "ui"):
            assert git.current_branch(workspace_with_feature / repo) == "feat-b"
            wt = warm_worktree_path(ws, "auth-flow", repo)
            assert wt.exists()
            assert (wt / ".git").exists()
        # Reflected in features.json by inspecting filesystem
        assert "auth-flow" in warm_features(ws)

    def test_evacuated_warm_preserves_dirty_via_stash(self, workspace_with_feature):
        """If main has dirty work for X, evacuation stashes + pops in worktree."""
        _make_feature_branches(workspace_with_feature, "feat-b")
        ws = _ws(workspace_with_feature)

        # Make X canonical, dirty it
        switch(ws, "auth-flow")
        scratch = workspace_with_feature / "api" / "scratch.txt"
        scratch.write_text("uncommitted scribbles\n")

        # Evacuate via switch
        switch(ws, "feat-b")

        # File should follow auth-flow into its warm worktree
        wt_api = warm_worktree_path(ws, "auth-flow", "api")
        moved = wt_api / "scratch.txt"
        assert moved.exists() and "uncommitted scribbles" in moved.read_text()
        # Main api repo should not have it anymore
        assert not scratch.exists()


# ── wind-down mode ──────────────────────────────────────────────────────

class TestWindDownMode:
    def test_wind_down_does_not_create_warm_worktree(self, workspace_with_feature):
        _make_feature_branches(workspace_with_feature, "feat-b")
        ws = _ws(workspace_with_feature)

        switch(ws, "auth-flow")
        result = switch(ws, "feat-b", release_current=True)

        assert result["mode"] == "wind_down"
        assert result["previously_canonical"] == "auth-flow"
        # auth-flow should NOT have a warm worktree
        assert "auth-flow" not in warm_features(ws)

    def test_wind_down_stashes_dirty_with_feature_tag(self, workspace_with_feature):
        _make_feature_branches(workspace_with_feature, "feat-b")
        ws = _ws(workspace_with_feature)

        switch(ws, "auth-flow")
        # Dirty main (api side, which is on auth-flow)
        (workspace_with_feature / "api" / "more.txt").write_text("untracked\n")

        switch(ws, "feat-b", release_current=True)

        # Inspect api stashes — should have a [canopy auth-flow ...] entry
        stash_list_output = subprocess.run(
            ["git", "stash", "list"], cwd=workspace_with_feature / "api",
            capture_output=True, text=True, check=True,
        ).stdout
        assert "canopy auth-flow" in stash_list_output
        assert "released to cold" in stash_list_output


# ── cap-reached + LRU eviction ──────────────────────────────────────────

class TestCapReached:
    def test_cap_reached_blocks_with_fix_actions(self, workspace_with_feature):
        """cap=1 → after 2 features, switching to a 3rd hits the cap."""
        _make_feature_branches(workspace_with_feature, "feat-b")
        _make_feature_branches(workspace_with_feature, "feat-c")
        ws = _ws(workspace_with_feature, max_worktrees=1)

        switch(ws, "auth-flow")               # canonical
        switch(ws, "feat-b")                   # auth-flow → warm (1 warm)
        # feat-b becomes canonical, auth-flow is warm. Now switch to feat-c
        # would evacuate feat-b → 2 warm, exceeding cap=1.
        with pytest.raises(BlockerError) as exc:
            switch(ws, "feat-c", no_evict=True)

        assert exc.value.code == "worktree_cap_reached"
        # Fix actions: wind-down mode, evict, raise cap
        actions = [fa.action for fa in exc.value.fix_actions]
        assert "switch" in actions  # both wind-down and evict use switch
        assert "workspace_config" in actions

    def test_cap_reached_auto_evicts_lru_by_default(self, workspace_with_feature):
        """Without --no-evict, switch picks the LRU warm and evicts."""
        _make_feature_branches(workspace_with_feature, "feat-b")
        _make_feature_branches(workspace_with_feature, "feat-c")
        ws = _ws(workspace_with_feature, max_worktrees=1)

        switch(ws, "auth-flow")
        switch(ws, "feat-b")    # auth-flow → warm
        # Now switch to feat-c — cap would exceed; auth-flow (LRU) should
        # evict to cold, feat-b → warm, feat-c → canonical.
        result = switch(ws, "feat-c")

        assert result.get("eviction") is not None
        assert result["eviction"]["feature"] == "auth-flow"
        # auth-flow no longer warm
        assert "auth-flow" not in warm_features(ws)
        # feat-b is warm; feat-c canonical
        assert "feat-b" in warm_features(ws)
        for repo in ("api", "ui"):
            assert git.current_branch(workspace_with_feature / repo) == "feat-c"

    def test_eviction_stashes_dirty_warm_worktree(self, workspace_with_feature):
        """LRU eviction must stash dirty work before removing the worktree."""
        _make_feature_branches(workspace_with_feature, "feat-b")
        _make_feature_branches(workspace_with_feature, "feat-c")
        ws = _ws(workspace_with_feature, max_worktrees=1)

        switch(ws, "auth-flow")
        switch(ws, "feat-b")
        # Dirty the auth-flow warm worktree
        wt_api = warm_worktree_path(ws, "auth-flow", "api")
        (wt_api / "evicted_work.txt").write_text("about to be evicted\n")

        result = switch(ws, "feat-c")

        # Eviction recorded that auto-stash happened
        ev = result["eviction"]
        api_repo_result = next(r for r in ev["repos"] if r["repo"] == "api")
        assert api_repo_result["stashed"] is True
        assert api_repo_result["stash_ref"] == "stash@{0}"

        # The auth-flow branch in api should have a tagged stash recoverable
        stashes = subprocess.run(
            ["git", "stash", "list"], cwd=workspace_with_feature / "api",
            capture_output=True, text=True, check=True,
        ).stdout
        assert "canopy auth-flow" in stashes
        assert "auto-evicted" in stashes


# ── reverse evacuation: Y was warm before the switch ────────────────────

def test_switching_to_warm_feature_removes_its_worktree(workspace_with_feature):
    """If Y is currently warm, the warm worktree must be removed before
    main can check out Y (git's one-checkout-per-branch rule)."""
    _make_feature_branches(workspace_with_feature, "feat-b")
    ws = _ws(workspace_with_feature)

    switch(ws, "auth-flow")
    switch(ws, "feat-b")    # auth-flow → warm

    # auth-flow IS warm. Switch back to it.
    result = switch(ws, "auth-flow")

    # auth-flow is canonical again
    for repo in ("api", "ui"):
        assert git.current_branch(workspace_with_feature / repo) == "auth-flow"
    # Its warm worktree should be gone
    assert "auth-flow" not in warm_features(ws)
    # And feat-b should now be the warm one
    assert "feat-b" in warm_features(ws)


# ── no-op when already canonical ────────────────────────────────────────

def test_switch_to_already_canonical_is_noop_per_repo(workspace_with_feature):
    """Each repo already on the target branch → noop status, no churn."""
    ws = _ws(workspace_with_feature)
    switch(ws, "auth-flow")
    result = switch(ws, "auth-flow")

    for entry in result["per_repo"]:
        assert entry["status"] == "noop"


# ── lazy migration ──────────────────────────────────────────────────────

class TestLazyMigration:
    def test_migration_runs_on_first_switch_in_pre_2_9_workspace(
        self, workspace_with_feature,
    ):
        """No active_feature.json AND auth-flow checked out in main → migrate
        seeds canonical=auth-flow + last_touched."""
        _features_file(workspace_with_feature, {
            "auth-flow": {"repos": ["api", "ui"], "status": "active"},
        })
        # Make main repos check out auth-flow first (fixture leaves them on it)
        ws = _ws(workspace_with_feature)
        result = switch(ws, "auth-flow")

        assert "migration" in result
        assert result["migration"]["ran"] is True

    def test_migration_does_not_run_twice(self, workspace_with_feature):
        """Once last_touched is populated, subsequent switches don't re-migrate."""
        ws = _ws(workspace_with_feature)
        switch(ws, "auth-flow")    # this runs migration
        result = switch(ws, "auth-flow")
        assert "migration" not in result


# ── branch creation from default ────────────────────────────────────────

def test_switch_creates_missing_branch_from_default(workspace_dir):
    """Switching to a feature whose branch doesn't exist creates it from default."""
    ws = _ws(workspace_dir)
    result = switch(ws, "brand-new-feat")

    assert result.get("branches_created") is not None
    assert {b["repo"] for b in result["branches_created"]} == {"api", "ui"}
    for repo in ("api", "ui"):
        assert git.current_branch(workspace_dir / repo) == "brand-new-feat"


# ── basic state recording ───────────────────────────────────────────────

def test_switch_writes_active_feature(workspace_with_feature):
    ws = _ws(workspace_with_feature)
    switch(ws, "auth-flow")
    assert is_active(ws, "auth-flow")


# ── PR3 step 1: structured mid-op failure surface ───────────────────────

def test_mid_op_failure_raises_switch_mid_op_failed(workspace_with_feature, monkeypatch):
    """If a per-repo step blows up mid-loop, the user gets a structured
    BlockerError(code='switch_mid_op_failed') with completed_repos +
    recovery_hints — not a raw GitError. Without this they're stuck
    debugging a half-flipped workspace from a generic exception."""
    _make_feature_branches(workspace_with_feature, "feat-b")
    ws = _ws(workspace_with_feature)
    switch(ws, "auth-flow")    # auth-flow canonical (no patching yet)

    # Now arm the boom: every checkout call from this point on raises.
    from canopy.git import repo as git_mod
    real_checkout = git_mod.checkout
    def boom(repo_path, branch):
        raise RuntimeError("simulated mid-op disk full")
    monkeypatch.setattr("canopy.actions.switch.git.checkout", boom)
    monkeypatch.setattr("canopy.actions.evacuate.git.checkout", boom)

    with pytest.raises(BlockerError) as exc_info:
        switch(ws, "feat-b")

    err = exc_info.value
    assert err.code == "switch_mid_op_failed"
    assert "simulated mid-op disk full" in err.actual["underlying_error"]
    assert err.actual["underlying_error_type"] == "RuntimeError"
    assert "feat-b" in err.what
    # Recovery hints + fix actions present
    assert err.details.get("recovery_hints") is not None
    assert any(fa.action == "switch" for fa in err.fix_actions)
