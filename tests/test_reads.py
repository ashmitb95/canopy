"""Tests for canopy.actions.reads — alias-aware read primitives.

GitHub-side reads are mocked at the integrations.github layer; we're
testing the read-tool composition + alias resolution + return shape,
not the MCP/gh transport (covered separately).
"""
import json
import os
import subprocess
from unittest.mock import patch

import pytest

from canopy.actions.errors import BlockerError
from canopy.actions.reads import (
    github_get_branch, github_get_pr, github_get_pr_comments,
    linear_get_issue,
)
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


def _set_remote(repo_path, url):
    subprocess.run(
        ["git", "remote", "add", "origin", url],
        cwd=repo_path, check=True, capture_output=True, text=True,
    )


# ── linear_get_issue ─────────────────────────────────────────────────────

def _fake_provider(fake_issue):
    """Build a Mock provider whose get_issue returns the given Issue."""
    from unittest.mock import MagicMock
    provider = MagicMock()
    provider.get_issue.return_value = fake_issue
    return provider


def test_linear_get_issue_by_id_directly(workspace_with_feature):
    """Provider returns Issue; reads adapter shapes it for backward compat."""
    from canopy.providers.types import Issue
    ws = _make_workspace(workspace_with_feature)
    fake = Issue(
        id="SIN-412", identifier="SIN-412", title="Test",
        description="d", state="in_progress",
        url="https://linear.app/x/issue/SIN-412",
        raw={"state": {"name": "Active"}},
    )
    with patch("canopy.actions.reads.get_issue_provider", return_value=_fake_provider(fake)):
        result = linear_get_issue(ws, "SIN-412")
    assert result["alias"] == "SIN-412"
    assert result["issue_id"] == "SIN-412"
    assert result["title"] == "Test"
    assert result["state"] == "Active"  # raw state preserved for backward compat


def test_linear_get_issue_via_feature_alias(workspace_with_feature):
    from canopy.providers.types import Issue
    _features_file(workspace_with_feature, {
        "auth-flow": {
            "repos": ["repo-a", "repo-b"], "status": "active",
            "linear_issue": "SIN-412",
        },
    })
    ws = _make_workspace(workspace_with_feature)
    fake = Issue(
        id="SIN-412", identifier="SIN-412", title="Auth Flow",
        description="", state="in_progress",
        url="https://linear.app/x/SIN-412",
        raw={"state": {"name": "Active"}},
    )
    provider = _fake_provider(fake)
    with patch("canopy.actions.reads.get_issue_provider", return_value=provider):
        result = linear_get_issue(ws, "auth-flow")
    provider.get_issue.assert_called_once_with("SIN-412")  # resolved alias
    assert result["issue_id"] == "SIN-412"


def test_linear_get_issue_no_linear_link_raises(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        linear_get_issue(ws, "auth-flow")
    assert exc_info.value.code == "no_linear_id"


# ── issue_get (M5+, canonical Issue shape — F-6 fix) ─────────────────────


def test_issue_get_returns_canonical_shape(workspace_with_feature):
    """F-6: new CLI/action surface returns Issue.to_dict() directly,
    with canonical state mapping ('todo'/'in_progress'/'done'/'cancelled')
    rather than raw provider strings."""
    from canopy.actions.reads import issue_get
    from canopy.providers.types import Issue
    ws = _make_workspace(workspace_with_feature)
    fake = Issue(
        id="SIN-412", identifier="SIN-412", title="Test",
        description="d", state="in_progress",
        url="https://linear.app/x/issue/SIN-412",
        assignee="alice",
        labels=("bug", "p1"),
        raw={"state": {"name": "Active"}},   # raw "Active", canonical "in_progress"
    )
    with patch("canopy.actions.reads.get_issue_provider", return_value=_fake_provider(fake)):
        result = issue_get(ws, "SIN-412")
    # Canonical fields
    assert result["identifier"] == "SIN-412"
    assert result["state"] == "in_progress"   # NOT "Active"
    assert result["title"] == "Test"
    assert result["assignee"] == "alice"
    assert result["labels"] == ["bug", "p1"]   # to_dict converts tuple → list
    # Convenience field
    assert result["alias"] == "SIN-412"


def test_issue_get_propagates_provider_not_configured(workspace_with_feature):
    from canopy.actions.reads import issue_get
    from canopy.providers.types import ProviderNotConfigured
    from unittest.mock import MagicMock
    ws = _make_workspace(workspace_with_feature)
    provider = MagicMock()
    provider.get_issue.side_effect = ProviderNotConfigured("nope")
    with patch("canopy.actions.reads.get_issue_provider", return_value=provider):
        with pytest.raises(BlockerError) as exc_info:
            issue_get(ws, "SIN-412")
    assert exc_info.value.code == "issue_provider_not_configured"


# ── github_get_pr ────────────────────────────────────────────────────────

def test_github_get_pr_specific_form(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    fake_pr = {
        "number": 1287, "title": "Fix X", "url": "https://github.com/owner/repo-a/pull/1287",
        "state": "open", "head_branch": "auth-flow", "base_branch": "dev",
        "body": "", "review_decision": "CHANGES_REQUESTED",
        "mergeable": "MERGEABLE", "draft": False,
    }
    with patch("canopy.actions.reads.gh.get_pull_request_by_number",
               return_value=fake_pr):
        result = github_get_pr(ws, "repo-a#1287")
    assert "repo-a" in result["repos"]
    assert result["repos"]["repo-a"]["found"] is True
    assert result["repos"]["repo-a"]["pr_number"] == 1287
    assert result["repos"]["repo-a"]["review_decision"] == "CHANGES_REQUESTED"


def test_github_get_pr_url_form(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    with patch("canopy.actions.reads.gh.get_pull_request_by_number",
               return_value={"number": 99, "title": "x", "url": "u",
                             "state": "open", "head_branch": "b", "base_branch": "dev",
                             "body": "", "review_decision": "", "mergeable": "", "draft": False}):
        result = github_get_pr(ws, "https://github.com/owner/repo-a/pull/99")
    assert result["repos"]["repo-a"]["pr_number"] == 99


def test_github_get_pr_via_feature_alias_multi_repo(workspace_with_feature):
    """Feature alias returns PRs across all repos in the lane."""
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    _set_remote(workspace_with_feature / "repo-b", "git@github.com:owner/repo-b.git")

    fake_pr_for_alias = {
        "number": 100, "title": "x", "url": "u", "state": "open",
        "head_branch": "auth-flow", "base_branch": "dev", "body": "",
        "review_decision": "", "mergeable": "", "draft": False,
    }
    # resolve_pr_targets now uses find_pull_request (per-repo branch),
    # not review_status, since it operates on per-repo expected branches.
    with patch("canopy.integrations.github.find_pull_request",
               return_value=fake_pr_for_alias) as _, \
         patch("canopy.actions.reads.gh.get_pull_request_by_number",
               return_value=fake_pr_for_alias):
        result = github_get_pr(ws, "auth-flow")

    assert set(result["repos"].keys()) == {"repo-a", "repo-b"}


def test_github_get_pr_not_found_marks_found_false(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    with patch("canopy.actions.reads.gh.get_pull_request_by_number",
               return_value=None):
        result = github_get_pr(ws, "repo-a#999")
    assert result["repos"]["repo-a"]["found"] is False
    assert result["repos"]["repo-a"]["pr_number"] == 999


# ── github_get_branch ────────────────────────────────────────────────────

def test_github_get_branch_specific_form_existing(workspace_with_feature):
    """workspace_with_feature has 'auth-flow' branch in both repos."""
    ws = _make_workspace(workspace_with_feature)
    result = github_get_branch(ws, "repo-a:auth-flow")
    assert "repo-a" in result["repos"]
    assert result["repos"]["repo-a"]["branch"] == "auth-flow"
    assert result["repos"]["repo-a"]["exists_locally"] is True
    assert len(result["repos"]["repo-a"]["head_sha"]) == 40
    assert result["repos"]["repo-a"]["has_upstream"] is False  # no remote configured
    assert result["repos"]["repo-a"]["ahead"] == 0


def test_github_get_branch_nonexistent_branch(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    result = github_get_branch(ws, "repo-a:nonexistent-branch")
    assert result["repos"]["repo-a"]["exists_locally"] is False
    assert "head_sha" not in result["repos"]["repo-a"]


def test_github_get_branch_via_feature_alias(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    result = github_get_branch(ws, "auth-flow")
    assert set(result["repos"].keys()) == {"repo-a", "repo-b"}
    for r in ("repo-a", "repo-b"):
        assert result["repos"][r]["branch"] == "auth-flow"
        assert result["repos"][r]["exists_locally"] is True


def test_github_get_branch_filtered_by_repo(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    result = github_get_branch(ws, "auth-flow", repo="repo-b")
    assert list(result["repos"].keys()) == ["repo-b"]


# ── github_get_pr_comments ───────────────────────────────────────────────

def test_github_get_pr_comments_specific_form(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")

    fake_comments = ([
        {"path": "src/app.py", "line": 1, "body": "fix this",
         "author": "reviewer", "author_type": "User", "state": "",
         "created_at": "2030-01-01T00:00:00Z", "url": "", "in_reply_to_id": None},
    ], 0)
    fake_pr = {"number": 42, "title": "x", "url": "u", "state": "open",
                "head_branch": "auth-flow", "base_branch": "dev", "body": "",
                "review_decision": "", "mergeable": "", "draft": False}

    with patch("canopy.actions.reads.gh.get_review_comments",
               return_value=fake_comments), \
         patch("canopy.actions.reads.gh.get_pull_request_by_number",
               return_value=fake_pr):
        result = github_get_pr_comments(ws, "repo-a#42")

    assert result["alias"] == "repo-a#42"
    assert result["actionable_count"] >= 1
    assert "repo-a" in result["repos"]
    assert result["repos"]["repo-a"]["pr_number"] == 42
    assert "actionable_threads" in result["repos"]["repo-a"]
