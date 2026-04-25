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

def test_linear_get_issue_by_id_directly(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    fake_issue = {
        "identifier": "ENG-412", "title": "Test", "state": "Active",
        "url": "https://linear.app/x/issue/ENG-412", "description": "d",
        "raw": {},
    }
    with patch("canopy.actions.reads.ln.get_issue", return_value=fake_issue):
        result = linear_get_issue(ws, "ENG-412")
    assert result["alias"] == "ENG-412"
    assert result["issue_id"] == "ENG-412"
    assert result["title"] == "Test"


def test_linear_get_issue_via_feature_alias(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {
            "repos": ["api", "ui"], "status": "active",
            "linear_issue": "ENG-412",
        },
    })
    ws = _make_workspace(workspace_with_feature)
    fake_issue = {
        "identifier": "ENG-412", "title": "Auth Flow", "state": "Active",
        "url": "https://linear.app/x/ENG-412", "description": "",
        "raw": {},
    }
    with patch("canopy.actions.reads.ln.get_issue", return_value=fake_issue) as mock:
        result = linear_get_issue(ws, "auth-flow")
    mock.assert_called_once()
    assert mock.call_args[0][1] == "ENG-412"  # resolved Linear ID
    assert result["issue_id"] == "ENG-412"


def test_linear_get_issue_no_linear_link_raises(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        linear_get_issue(ws, "auth-flow")
    assert exc_info.value.code == "no_linear_id"


# ── github_get_pr ────────────────────────────────────────────────────────

def test_github_get_pr_specific_form(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    fake_pr = {
        "number": 1287, "title": "Fix X", "url": "https://github.com/owner/api/pull/1287",
        "state": "open", "head_branch": "auth-flow", "base_branch": "dev",
        "body": "", "review_decision": "CHANGES_REQUESTED",
        "mergeable": "MERGEABLE", "draft": False,
    }
    with patch("canopy.actions.reads.gh.get_pull_request_by_number",
               return_value=fake_pr):
        result = github_get_pr(ws, "api#1287")
    assert "api" in result["repos"]
    assert result["repos"]["api"]["found"] is True
    assert result["repos"]["api"]["pr_number"] == 1287
    assert result["repos"]["api"]["review_decision"] == "CHANGES_REQUESTED"


def test_github_get_pr_url_form(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    with patch("canopy.actions.reads.gh.get_pull_request_by_number",
               return_value={"number": 99, "title": "x", "url": "u",
                             "state": "open", "head_branch": "b", "base_branch": "dev",
                             "body": "", "review_decision": "", "mergeable": "", "draft": False}):
        result = github_get_pr(ws, "https://github.com/owner/api/pull/99")
    assert result["repos"]["api"]["pr_number"] == 99


def test_github_get_pr_via_feature_alias_multi_repo(workspace_with_feature):
    """Feature alias returns PRs across all repos in the lane."""
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    _set_remote(workspace_with_feature / "ui", "git@github.com:owner/ui.git")

    fake_status = {
        "feature": "auth-flow", "has_prs": True,
        "repos": {
            "api": {"branch": "auth-flow", "owner": "owner", "repo_name": "api",
                     "pr": {"number": 100}},
            "ui":  {"branch": "auth-flow", "owner": "owner", "repo_name": "ui",
                     "pr": {"number": 200}},
        },
    }
    fake_pr = {"number": 0, "title": "x", "url": "u", "state": "open",
                "head_branch": "auth-flow", "base_branch": "dev", "body": "",
                "review_decision": "", "mergeable": "", "draft": False}

    with patch("canopy.features.coordinator.FeatureCoordinator.review_status",
               return_value=fake_status), \
         patch("canopy.actions.reads.gh.get_pull_request_by_number",
               return_value=fake_pr):
        result = github_get_pr(ws, "auth-flow")

    assert set(result["repos"].keys()) == {"api", "ui"}


def test_github_get_pr_not_found_marks_found_false(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    with patch("canopy.actions.reads.gh.get_pull_request_by_number",
               return_value=None):
        result = github_get_pr(ws, "api#999")
    assert result["repos"]["api"]["found"] is False
    assert result["repos"]["api"]["pr_number"] == 999


# ── github_get_branch ────────────────────────────────────────────────────

def test_github_get_branch_specific_form_existing(workspace_with_feature):
    """workspace_with_feature has 'auth-flow' branch in both repos."""
    ws = _make_workspace(workspace_with_feature)
    result = github_get_branch(ws, "api:auth-flow")
    assert "api" in result["repos"]
    assert result["repos"]["api"]["branch"] == "auth-flow"
    assert result["repos"]["api"]["exists_locally"] is True
    assert len(result["repos"]["api"]["head_sha"]) == 40
    assert result["repos"]["api"]["has_upstream"] is False  # no remote configured
    assert result["repos"]["api"]["ahead"] == 0


def test_github_get_branch_nonexistent_branch(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    result = github_get_branch(ws, "api:nonexistent-branch")
    assert result["repos"]["api"]["exists_locally"] is False
    assert "head_sha" not in result["repos"]["api"]


def test_github_get_branch_via_feature_alias(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    result = github_get_branch(ws, "auth-flow")
    assert set(result["repos"].keys()) == {"api", "ui"}
    for r in ("api", "ui"):
        assert result["repos"][r]["branch"] == "auth-flow"
        assert result["repos"][r]["exists_locally"] is True


def test_github_get_branch_filtered_by_repo(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    result = github_get_branch(ws, "auth-flow", repo="ui")
    assert list(result["repos"].keys()) == ["ui"]


# ── github_get_pr_comments ───────────────────────────────────────────────

def test_github_get_pr_comments_specific_form(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")

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
        result = github_get_pr_comments(ws, "api#42")

    assert result["alias"] == "api#42"
    assert result["actionable_count"] >= 1
    assert "api" in result["repos"]
    assert result["repos"]["api"]["pr_number"] == 42
    assert "actionable_threads" in result["repos"]["api"]
