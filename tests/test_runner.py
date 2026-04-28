"""Tests for canopy.agent.runner — directory-safe shell exec."""
import json

import pytest

from canopy.actions.errors import BlockerError, FailedError
from canopy.agent.runner import run_in_repo
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


# ── Path resolution ─────────────────────────────────────────────────────

def test_runs_in_repo_main_path(workspace_dir):
    ws = _make_workspace(workspace_dir)
    result = run_in_repo(ws, repo="repo-a", command="pwd")
    assert result["exit_code"] == 0
    assert result["cwd"] == str(workspace_dir / "repo-a")
    assert result["stdout"].strip().endswith("/repo-a")


def test_unknown_repo_raises_blocker(workspace_dir):
    ws = _make_workspace(workspace_dir)
    with pytest.raises(BlockerError) as exc_info:
        run_in_repo(ws, repo="ghost", command="echo x")
    err = exc_info.value
    assert err.code == "unknown_repo"
    assert "repo-a" in err.expected["available_repos"]
    assert "repo-b" in err.expected["available_repos"]


def test_unknown_feature_raises_blocker(workspace_with_feature):
    """feature= passed but the lane doesn't exist."""
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        run_in_repo(ws, repo="repo-a", command="pwd", feature="not-a-feature")
    assert exc_info.value.code == "unknown_feature"


def test_feature_with_worktree_uses_worktree_path(workspace_dir):
    """When a feature lane has a worktree for the repo, run there."""
    from canopy.features.coordinator import FeatureCoordinator

    ws = _make_workspace(workspace_dir)
    coord = FeatureCoordinator(ws)
    coord.create("wt-feat", repos=["repo-a"], use_worktrees=True)

    result = run_in_repo(ws, repo="repo-a", command="pwd", feature="wt-feat")
    assert result["exit_code"] == 0
    assert "/.canopy/worktrees/wt-feat/repo-a" in result["cwd"]


def test_feature_without_worktree_falls_back_to_repo_path(workspace_with_feature):
    """If the feature lane exists but has no worktree, run in the repo's main path."""
    from canopy.features.coordinator import FeatureCoordinator

    ws = _make_workspace(workspace_with_feature)
    coord = FeatureCoordinator(ws)
    coord.create("auth-flow", repos=["repo-a", "repo-b"], use_worktrees=False)

    result = run_in_repo(ws, repo="repo-a", command="pwd", feature="auth-flow")
    assert result["exit_code"] == 0
    assert result["cwd"] == str(workspace_with_feature / "repo-a")


def test_feature_excluding_repo_falls_back_to_main_path(workspace_with_feature):
    """If the repo isn't part of the feature lane, fall back gracefully."""
    from canopy.features.coordinator import FeatureCoordinator

    ws = _make_workspace(workspace_with_feature)
    coord = FeatureCoordinator(ws)
    coord.create("ui-only", repos=["repo-b"], use_worktrees=False)

    # api isn't in ui-only, but caller asked for api; runner shouldn't blow up.
    result = run_in_repo(ws, repo="repo-a", command="pwd", feature="ui-only")
    assert result["exit_code"] == 0
    assert result["cwd"] == str(workspace_with_feature / "repo-a")


# ── Execution + return shape ────────────────────────────────────────────

def test_returns_exit_code_stdout_stderr_cwd_duration(workspace_dir):
    ws = _make_workspace(workspace_dir)
    result = run_in_repo(ws, repo="repo-a",
                         command="echo hi; echo err >&2; exit 3")
    assert result["exit_code"] == 3
    assert "hi" in result["stdout"]
    assert "err" in result["stderr"]
    assert result["cwd"] == str(workspace_dir / "repo-a")
    assert result["duration_ms"] >= 0


def test_zero_exit_code_does_not_raise(workspace_dir):
    """Non-zero exit is reported in the dict, not raised."""
    ws = _make_workspace(workspace_dir)
    result = run_in_repo(ws, repo="repo-a", command="false")
    assert result["exit_code"] == 1


def test_command_runs_in_correct_dir(workspace_dir):
    """The command actually executes in the resolved directory."""
    ws = _make_workspace(workspace_dir)
    # ls a file that exists only in the api repo
    result = run_in_repo(ws, repo="repo-a", command="ls src/app.py")
    assert result["exit_code"] == 0
    assert "src/app.py" in result["stdout"]

    # Same command in ui should not find that file
    result = run_in_repo(ws, repo="repo-b", command="ls src/app.py")
    assert result["exit_code"] != 0


def test_shell_features_work(workspace_dir):
    """Pipes / && / globs etc. all work since command is shell-executed."""
    ws = _make_workspace(workspace_dir)
    result = run_in_repo(ws, repo="repo-a", command="echo foo && echo bar | tr a-z A-Z")
    assert result["exit_code"] == 0
    assert "foo" in result["stdout"]
    assert "BAR" in result["stdout"]


def test_timeout_raises_failed(workspace_dir):
    ws = _make_workspace(workspace_dir)
    with pytest.raises(FailedError) as exc_info:
        run_in_repo(ws, repo="repo-a", command="sleep 5", timeout_seconds=1)
    err = exc_info.value
    assert err.code == "timeout"
    assert err.details["timeout_seconds"] == 1
    # JSON-serializable
    json.dumps(err.to_dict())
