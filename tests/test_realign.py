"""Tests for canopy.actions.realign — alignment fix action."""
import json
import os
import subprocess

import pytest

from canopy.actions.errors import BlockerError
from canopy.actions.realign import realign
from canopy.git import repo as git
from canopy.workspace.config import RepoConfig, WorkspaceConfig
from canopy.workspace.workspace import Workspace


def _make_workspace(workspace_dir, repos=("repo-a", "repo-b")) -> Workspace:
    config = WorkspaceConfig(
        name="test",
        repos=[
            RepoConfig(name=name, path=f"./{name}", role="x", lang="x")
            for name in repos
        ],
        root=workspace_dir,
    )
    return Workspace(config)


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


# ── No-op when already aligned ───────────────────────────────────────────

def test_no_op_when_all_repos_already_on_feature_branch(workspace_with_feature):
    """workspace_with_feature checks both repos out on auth-flow."""
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    result = realign(ws, "auth-flow")
    assert result["aligned"] is True
    for repo in ("repo-a", "repo-b"):
        assert result["repos"][repo]["status"] == "already_aligned"


# ── Drift fix (clean tree) ───────────────────────────────────────────────

def test_realign_clean_drift(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    # Move ui to main (drift)
    _git(["checkout", "main"], cwd=workspace_with_feature / "repo-b")

    result = realign(ws, "auth-flow")
    assert result["aligned"] is True
    assert result["repos"]["repo-b"]["status"] == "checkout_ok"
    assert result["repos"]["repo-b"]["before"] == "main"
    assert result["repos"]["repo-b"]["after"] == "auth-flow"
    # api wasn't drifted; should be already_aligned
    assert result["repos"]["repo-a"]["status"] == "already_aligned"


# ── Dirty tree blocks without --auto-stash ──────────────────────────────

def test_dirty_tree_raises_blocker(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    # Drift + dirty in ui
    _git(["checkout", "main"], cwd=workspace_with_feature / "repo-b")
    (workspace_with_feature / "repo-b" / "src" / "App.tsx").write_text("modified\n")

    with pytest.raises(BlockerError) as exc_info:
        realign(ws, "auth-flow")
    err = exc_info.value
    assert err.code == "dirty_tree"
    assert "repo-b" in err.actual["dirty_repos"]
    # fix_actions includes the auto_stash form
    actions = [(fa.action, fa.args) for fa in err.fix_actions]
    assert any(a == "realign" and args.get("auto_stash") for a, args in actions)


# ── Dirty tree handled by --auto-stash ──────────────────────────────────

def test_auto_stash_succeeds_when_dirty(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    _git(["checkout", "main"], cwd=workspace_with_feature / "repo-b")
    (workspace_with_feature / "repo-b" / "src" / "App.tsx").write_text("dirty before realign\n")

    result = realign(ws, "auth-flow", auto_stash=True)
    assert result["aligned"] is True
    ui_entry = result["repos"]["repo-b"]
    assert ui_entry["status"] == "checkout_ok"
    assert ui_entry.get("stash_ref") == "stash@{0}"
    # And the dirty file is no longer present (it's stashed)
    assert "dirty before realign" not in (workspace_with_feature / "repo-b" / "src" / "App.tsx").read_text()


# ── Branch missing in a repo ─────────────────────────────────────────────

def test_branch_missing_reports_failed(workspace_with_feature):
    """If the feature branch doesn't exist in a repo, that repo fails (not auto-create)."""
    _features_file(workspace_with_feature, {
        "ghost-feature": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    result = realign(ws, "ghost-feature")
    assert result["aligned"] is False
    for repo in ("repo-a", "repo-b"):
        assert result["repos"][repo]["status"] == "failed"
        assert result["repos"][repo]["reason"] == "branch_not_found"


# ── Single-repo feature ──────────────────────────────────────────────────

def test_single_repo_feature_only_touches_its_repo(workspace_with_feature):
    """ui-only feature should not touch api even if api is on a weird branch."""
    _features_file(workspace_with_feature, {
        "ui-only": {"repos": ["repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    git.create_branch(workspace_with_feature / "repo-b", "ui-only")
    # ui starts on auth-flow (per fixture); needs to switch to ui-only
    _git(["checkout", "main"], cwd=workspace_with_feature / "repo-a")  # api on main; should be ignored

    result = realign(ws, "ui-only")
    assert "repo-a" not in result["repos"]
    assert result["repos"]["repo-b"]["status"] == "checkout_ok"


# ── Explicit repos override ──────────────────────────────────────────────

def test_repos_override_filters_target(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    _git(["checkout", "main"], cwd=workspace_with_feature / "repo-a")
    _git(["checkout", "main"], cwd=workspace_with_feature / "repo-b")

    result = realign(ws, "auth-flow", repos=["repo-b"])
    assert "repo-a" not in result["repos"]
    assert result["repos"]["repo-b"]["status"] == "checkout_ok"


def test_unknown_repo_in_override_raises(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        realign(ws, "auth-flow", repos=["repo-a", "ghost"])
    assert exc_info.value.code == "unknown_repo"


# ── Unknown alias rejected ───────────────────────────────────────────────

def test_unknown_feature_alias_raises(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        realign(ws, "no-such-feature")
    assert exc_info.value.code == "unknown_alias"


# ── Mixed: one drift, one already aligned ───────────────────────────────

def test_mixed_repos_partial_realign(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    # api stays on auth-flow; ui drifts to main
    _git(["checkout", "main"], cwd=workspace_with_feature / "repo-b")

    result = realign(ws, "auth-flow")
    assert result["aligned"] is True
    assert result["repos"]["repo-a"]["status"] == "already_aligned"
    assert result["repos"]["repo-b"]["status"] == "checkout_ok"
