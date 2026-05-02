"""Tests for canopy.actions.bot_status — per-feature bot-comment rollup (M3)."""
from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from canopy.actions.bot_resolutions import record_resolution
from canopy.actions.bot_status import bot_comments_status
from canopy.actions.errors import BlockerError
from canopy.workspace.config import RepoConfig, WorkspaceConfig
from canopy.workspace.workspace import Workspace


def _make_workspace(workspace_dir):
    config = WorkspaceConfig(
        name="test",
        repos=[RepoConfig(name="repo-a", path="./repo-a", role="x", lang="x")],
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


def _bot_comment(comment_id, *, body="rename foo to bar"):
    return {
        "id": comment_id, "path": "src/auth.py", "line": 1, "body": body,
        "author": "coderabbit", "author_type": "Bot", "state": "",
        "created_at": "2030-01-01T00:00:00Z",
        "url": f"https://github.com/o/r/pull/1#discussion_r{comment_id}",
        "in_reply_to_id": None,
    }


def _pr():
    return {"number": 142, "title": "x", "url": "u", "state": "open",
            "head_branch": "auth-flow", "base_branch": "main", "body": "",
            "review_decision": "REVIEW_REQUIRED", "mergeable": "", "draft": False}


def test_status_empty_when_no_pr_no_resolutions(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature)

    with patch("canopy.actions.feature_state.gh.find_pull_request",
               return_value=None), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([], 0)):
        result = bot_comments_status(ws, feature="auth-flow")

    assert result["feature"] == "auth-flow"
    assert result["any_bot_comments"] is False
    assert result["all_resolved"] is True   # vacuously true
    assert result["repos"]["repo-a"]["total"] == 0


def test_status_all_unresolved(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature)

    with patch("canopy.actions.feature_state.gh.find_pull_request",
               return_value=_pr()), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([_bot_comment(1), _bot_comment(2)], 0)):
        result = bot_comments_status(ws, feature="auth-flow")

    repo_info = result["repos"]["repo-a"]
    assert repo_info["pr_number"] == 142
    assert repo_info["total"] == 2
    assert repo_info["resolved"] == 0
    assert repo_info["unresolved"] == 2
    assert result["all_resolved"] is False
    assert result["any_bot_comments"] is True


def test_status_mixed_resolved_unresolved(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature)

    record_resolution(
        workspace_with_feature, comment_id=1, feature="auth-flow",
        repo="repo-a", commit_sha="abc12345", comment_title="addressed already",
        comment_url="https://github.com/o/r/pull/1#discussion_r1",
    )

    with patch("canopy.actions.feature_state.gh.find_pull_request",
               return_value=_pr()), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([_bot_comment(2)], 0)):
        result = bot_comments_status(ws, feature="auth-flow")

    repo_info = result["repos"]["repo-a"]
    assert repo_info["resolved"] == 1
    assert repo_info["unresolved"] == 1
    assert repo_info["total"] == 2
    assert result["all_resolved"] is False

    threads_by_id = {str(t["id"]): t for t in repo_info["threads"]}
    assert threads_by_id["1"]["resolved"] is True
    assert threads_by_id["1"]["resolved_by_commit"] == "abc12345"
    assert threads_by_id["2"]["resolved"] is False


def test_status_all_resolved_when_resolutions_match_open_threads(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature)

    record_resolution(
        workspace_with_feature, comment_id=42, feature="auth-flow",
        repo="repo-a", commit_sha="sha", comment_title="t",
    )

    # Live API returns the same comment (still on the PR), but we've recorded it.
    with patch("canopy.actions.feature_state.gh.find_pull_request",
               return_value=_pr()), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([_bot_comment(42)], 0)):
        result = bot_comments_status(ws, feature="auth-flow")

    repo_info = result["repos"]["repo-a"]
    assert repo_info["unresolved"] == 0
    assert repo_info["resolved"] == 1
    assert result["all_resolved"] is True


def test_status_blocker_when_no_canonical_feature(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as excinfo:
        bot_comments_status(ws, feature=None)
    assert excinfo.value.code == "no_canonical_feature"
