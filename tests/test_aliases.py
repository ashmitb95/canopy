"""Tests for canopy.actions.aliases — universal alias + per-tool specifics."""
import json
import os
import subprocess

import pytest

from canopy.actions.aliases import (
    BranchTarget, PRTarget,
    resolve_branch_targets, resolve_feature, resolve_issue_id,
    resolve_linear_id, resolve_pr_targets,
)
from canopy.actions.errors import BlockerError
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
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    assert resolve_feature(ws, "auth-flow") == "auth-flow"


def test_resolve_feature_via_linear_id(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {
            "repos": ["repo-a", "repo-b"], "status": "active",
            "linear_issue": "SIN-412",
        },
    })
    ws = _make_workspace(workspace_with_feature)
    assert resolve_feature(ws, "SIN-412") == "auth-flow"


def test_resolve_feature_implicit_branch_match(workspace_with_feature):
    """Branches existing in 2+ repos count as an implicit feature."""
    ws = _make_workspace(workspace_with_feature)
    # workspace_with_feature creates 'auth-flow' branches in both repos
    assert resolve_feature(ws, "auth-flow") == "auth-flow"


def test_resolve_feature_single_repo_branch_resolves(workspace_with_feature):
    """Branch existing in only one repo (no features.json entry) should still resolve."""
    from canopy.git import repo as git
    git.create_branch(workspace_with_feature / "repo-a", "lonely-branch")
    ws = _make_workspace(workspace_with_feature)
    assert resolve_feature(ws, "lonely-branch") == "lonely-branch"


def test_resolve_feature_via_branches_map(workspace_with_feature):
    """Per-repo branches map: alias matching the api-side branch resolves
    to the feature lane name (not the branch name itself)."""
    _features_file(workspace_with_feature, {
        "sin-1003": {
            "repos": ["repo-a", "repo-b"],
            "status": "active",
            "branches": {
                "repo-a": "sin-1003-fixes",
                "repo-b": "SIN-1003-fixes-v2",
            },
        },
    })
    from canopy.git import repo as git
    git.create_branch(workspace_with_feature / "repo-a", "sin-1003-fixes")
    git.create_branch(workspace_with_feature / "repo-b", "SIN-1003-fixes-v2")
    ws = _make_workspace(workspace_with_feature)
    assert resolve_feature(ws, "sin-1003") == "sin-1003"
    assert resolve_feature(ws, "sin-1003-fixes") == "sin-1003"
    assert resolve_feature(ws, "SIN-1003-fixes-v2") == "sin-1003"


def test_resolve_feature_unknown_raises_with_available(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "real-feature": {"repos": ["repo-a", "repo-b"], "status": "active"},
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
    assert resolve_linear_id(ws, "SIN-412") == "SIN-412"
    assert resolve_linear_id(ws, "SIN-3029") == "SIN-3029"


def test_resolve_linear_id_via_feature_lookup(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {
            "repos": ["repo-a", "repo-b"], "status": "active",
            "linear_issue": "SIN-412",
        },
    })
    ws = _make_workspace(workspace_with_feature)
    assert resolve_linear_id(ws, "auth-flow") == "SIN-412"


def test_resolve_linear_id_no_link_raises(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        resolve_linear_id(ws, "auth-flow")
    assert exc_info.value.code == "no_linear_id"


# ── resolve_issue_id (M5+ provider-aware — F-7) ─────────────────────────


def test_resolve_issue_id_linear_id_via_provider(workspace_with_feature):
    """Linear-shaped ids are recognised by LinearProvider.parse_alias."""
    ws = _make_workspace(workspace_with_feature)
    assert resolve_issue_id(ws, "SIN-412") == "SIN-412"


def test_resolve_issue_id_github_id_when_provider_swapped(workspace_with_feature):
    """When the workspace selects github_issues, bare/hash/owner-repo forms work."""
    from unittest.mock import patch
    from canopy.providers.github_issues import GitHubIssuesProvider
    ws = _make_workspace(workspace_with_feature)
    provider = GitHubIssuesProvider({"repo": "owner/repo"}, workspace_root=workspace_with_feature)
    # `aliases.py` imports get_issue_provider lazily inside the function — patch at the source module.
    with patch("canopy.providers.get_issue_provider", return_value=provider):
        assert resolve_issue_id(ws, "5") == "5"
        assert resolve_issue_id(ws, "#5") == "5"
        assert resolve_issue_id(ws, "owner/repo#5") == "owner/repo#5"
        assert resolve_issue_id(ws, "https://github.com/owner/repo/issues/5") == "owner/repo#5"


def test_resolve_issue_id_falls_back_to_feature_lookup(workspace_with_feature):
    """When the alias isn't a provider-native id, walk features.json."""
    _features_file(workspace_with_feature, {
        "auth-flow": {
            "repos": ["repo-a", "repo-b"], "status": "active",
            "linear_issue": "SIN-99",
        },
    })
    ws = _make_workspace(workspace_with_feature)
    assert resolve_issue_id(ws, "auth-flow") == "SIN-99"


def test_resolve_issue_id_unknown_alias_blocks(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        resolve_issue_id(ws, "neither-id-nor-feature")
    assert exc_info.value.code == "unknown_alias"
    # Provider name surfaced in the error so the user knows what shapes are expected
    assert "provider" in (exc_info.value.details or {})


def test_resolve_issue_id_feature_without_linked_issue_blocks(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},  # no linear_issue
    })
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        resolve_issue_id(ws, "auth-flow")
    assert exc_info.value.code == "no_linked_issue"


def test_resolve_linear_id_back_compat_reissues_legacy_code(workspace_with_feature):
    """The deprecated wrapper preserves the old ``no_linear_id`` code so
    existing assertions on it continue to work until callers migrate."""
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        resolve_linear_id(ws, "auth-flow")
    assert exc_info.value.code == "no_linear_id"   # legacy code preserved


# ── resolve_branch_targets ───────────────────────────────────────────────

def test_resolve_branch_specific_form(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    targets = resolve_branch_targets(ws, "repo-a:custom-branch")
    assert targets == [BranchTarget("repo-a", "custom-branch")]


def test_resolve_branch_specific_with_unknown_repo(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        resolve_branch_targets(ws, "ghost:foo")
    assert exc_info.value.code == "unknown_repo"


def test_resolve_branch_via_feature_alias(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    targets = resolve_branch_targets(ws, "auth-flow")
    assert {t.repo for t in targets} == {"repo-a", "repo-b"}
    assert {t.branch for t in targets} == {"auth-flow"}


def test_resolve_branch_filtered_by_repo(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    targets = resolve_branch_targets(ws, "auth-flow", repo="repo-a")
    assert targets == [BranchTarget("repo-a", "auth-flow")]


def test_resolve_branch_repo_not_in_feature(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "ui-only": {"repos": ["repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        resolve_branch_targets(ws, "ui-only", repo="repo-a")
    assert exc_info.value.code == "repo_not_in_feature"


def test_resolve_branch_specific_repo_mismatch(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        resolve_branch_targets(ws, "repo-a:foo", repo="repo-b")
    assert exc_info.value.code == "alias_repo_mismatch"


# ── resolve_pr_targets ───────────────────────────────────────────────────

def test_resolve_pr_url_form(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    targets = resolve_pr_targets(ws, "https://github.com/owner/repo-a/pull/1287")
    assert targets == [PRTarget("repo-a", "owner", "repo-a", 1287)]


def test_resolve_pr_specific_form(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    targets = resolve_pr_targets(ws, "repo-a#42")
    assert targets == [PRTarget("repo-a", "owner", "repo-a", 42)]


def test_resolve_pr_specific_unknown_repo(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        resolve_pr_targets(ws, "ghost#1")
    assert exc_info.value.code == "unknown_repo"


def test_resolve_pr_url_unmatched_remote_raises(workspace_with_feature):
    """URL points at a github repo none of the canopy repos match."""
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    with pytest.raises(BlockerError) as exc_info:
        resolve_pr_targets(ws, "https://github.com/other/repo/pull/1")
    assert exc_info.value.code == "unknown_github_repo"
