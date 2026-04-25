"""Tests for canopy.actions.aliases — universal alias + per-tool specifics."""
import json
import os
import subprocess

import pytest

from canopy.actions.aliases import (
    BranchTarget, PRTarget,
    resolve_branch_targets, resolve_feature, resolve_linear_id, resolve_pr_targets,
)
from canopy.actions.errors import BlockerError
from canopy.workspace.config import RepoConfig, WorkspaceConfig
from canopy.workspace.workspace import Workspace


def _make_workspace(workspace_dir, repos=("api", "ui")) -> Workspace:
    config = WorkspaceConfig(
        name="test",
        repos=[
            RepoConfig(name=name, path=f"./{name}", role="x", lang="x")
            for name in repos
        ],
        root=workspace_dir,
    )
    return Workspace(config)


def _set_remote(repo_path, url):
    subprocess.run(
        ["git", "remote", "add", "origin", url],
        cwd=repo_path, check=True, capture_output=True, text=True,
    )


def _features_file(workspace_dir, payload):
    canopy_dir = workspace_dir / ".canopy"
    canopy_dir.mkdir(exist_ok=True)
    (canopy_dir / "features.json").write_text(json.dumps(payload))


# ── resolve_feature ─────────────────────────────────────────────────────

def test_resolve_feature_explicit_match(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    assert resolve_feature(ws, "auth-flow") == "auth-flow"


def test_resolve_feature_via_linear_id(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {
            "repos": ["api", "ui"], "status": "active",
            "linear_issue": "ENG-412",
        },
    })
    ws = _make_workspace(workspace_with_feature)
    assert resolve_feature(ws, "ENG-412") == "auth-flow"


def test_resolve_feature_implicit_branch_match(workspace_with_feature):
    """Branches existing in 2+ repos count as an implicit feature."""
    ws = _make_workspace(workspace_with_feature)
    # workspace_with_feature creates 'auth-flow' branches in both repos
    assert resolve_feature(ws, "auth-flow") == "auth-flow"


def test_resolve_feature_single_repo_branch_resolves(workspace_with_feature):
    """Branch existing in only one repo (no features.json entry) should still resolve."""
    from canopy.git import repo as git
    git.create_branch(workspace_with_feature / "api", "lonely-branch")
    ws = _make_workspace(workspace_with_feature)
    assert resolve_feature(ws, "lonely-branch") == "lonely-branch"


def test_resolve_feature_via_branches_map(workspace_with_feature):
    """Per-repo branches map: alias matching the api-side branch resolves
    to the feature lane name (not the branch name itself)."""
    _features_file(workspace_with_feature, {
        "doc-1003": {
            "repos": ["api", "ui"],
            "status": "active",
            "branches": {
                "api": "doc-1003-fixes",
                "ui": "DOC-1003-fixes-v2",
            },
        },
    })
    from canopy.git import repo as git
    git.create_branch(workspace_with_feature / "api", "doc-1003-fixes")
    git.create_branch(workspace_with_feature / "ui", "DOC-1003-fixes-v2")
    ws = _make_workspace(workspace_with_feature)
    assert resolve_feature(ws, "doc-1003") == "doc-1003"
    assert resolve_feature(ws, "doc-1003-fixes") == "doc-1003"
    assert resolve_feature(ws, "DOC-1003-fixes-v2") == "doc-1003"


def test_resolve_feature_unknown_raises_with_available(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "real-feature": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        resolve_feature(ws, "made-up-feature")
    err = exc_info.value
    assert err.code == "unknown_alias"
    assert "real-feature" in err.expected["explicit_features"]


# ── resolve_linear_id ────────────────────────────────────────────────────

def test_resolve_linear_id_passes_id_through(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    assert resolve_linear_id(ws, "ENG-412") == "ENG-412"
    assert resolve_linear_id(ws, "DOC-3029") == "DOC-3029"


def test_resolve_linear_id_via_feature_lookup(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {
            "repos": ["api", "ui"], "status": "active",
            "linear_issue": "ENG-412",
        },
    })
    ws = _make_workspace(workspace_with_feature)
    assert resolve_linear_id(ws, "auth-flow") == "ENG-412"


def test_resolve_linear_id_no_link_raises(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        resolve_linear_id(ws, "auth-flow")
    assert exc_info.value.code == "no_linear_id"


# ── resolve_branch_targets ───────────────────────────────────────────────

def test_resolve_branch_specific_form(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    targets = resolve_branch_targets(ws, "api:custom-branch")
    assert targets == [BranchTarget("api", "custom-branch")]


def test_resolve_branch_specific_with_unknown_repo(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        resolve_branch_targets(ws, "ghost:foo")
    assert exc_info.value.code == "unknown_repo"


def test_resolve_branch_via_feature_alias(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    targets = resolve_branch_targets(ws, "auth-flow")
    assert {t.repo for t in targets} == {"api", "ui"}
    assert {t.branch for t in targets} == {"auth-flow"}


def test_resolve_branch_filtered_by_repo(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    targets = resolve_branch_targets(ws, "auth-flow", repo="api")
    assert targets == [BranchTarget("api", "auth-flow")]


def test_resolve_branch_repo_not_in_feature(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "ui-only": {"repos": ["ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        resolve_branch_targets(ws, "ui-only", repo="api")
    assert exc_info.value.code == "repo_not_in_feature"


def test_resolve_branch_specific_repo_mismatch(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        resolve_branch_targets(ws, "api:foo", repo="ui")
    assert exc_info.value.code == "alias_repo_mismatch"


# ── resolve_pr_targets ───────────────────────────────────────────────────

def test_resolve_pr_url_form(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    targets = resolve_pr_targets(ws, "https://github.com/owner/api/pull/1287")
    assert targets == [PRTarget("api", "owner", "api", 1287)]


def test_resolve_pr_specific_form(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    targets = resolve_pr_targets(ws, "api#42")
    assert targets == [PRTarget("api", "owner", "api", 42)]


def test_resolve_pr_specific_unknown_repo(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        resolve_pr_targets(ws, "ghost#1")
    assert exc_info.value.code == "unknown_repo"


def test_resolve_pr_url_unmatched_remote_raises(workspace_with_feature):
    """URL points at a github repo none of the canopy repos match."""
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    with pytest.raises(BlockerError) as exc_info:
        resolve_pr_targets(ws, "https://github.com/other/repo/pull/1")
    assert exc_info.value.code == "unknown_github_repo"
