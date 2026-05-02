"""M3 tests for feature_state — bot vs human comment classification + new state."""
from __future__ import annotations

import json
import os
import subprocess
from unittest.mock import patch

from canopy.actions.bot_resolutions import record_resolution
from canopy.actions.feature_state import feature_state, _is_bot_comment
from canopy.workspace.config import RepoConfig, WorkspaceConfig
from canopy.workspace.workspace import Workspace


def _make_workspace(workspace_dir, *, augments=None):
    config = WorkspaceConfig(
        name="test",
        repos=[RepoConfig(name="repo-a", path="./repo-a", role="x", lang="x")],
        root=workspace_dir,
        augments=augments or {},
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


def _bot_comment(comment_id, *, author="coderabbit", body="please rename foo"):
    return {
        "id": comment_id, "path": "src/auth.py", "line": 1, "body": body,
        "author": author, "author_type": "Bot", "state": "",
        "created_at": "2030-01-01T00:00:00Z", "url": f"https://gh/c/{comment_id}",
        "in_reply_to_id": None,
    }


def _human_comment(comment_id, *, author="reviewer", body="this needs work"):
    return {
        "id": comment_id, "path": "src/auth.py", "line": 1, "body": body,
        "author": author, "author_type": "User", "state": "",
        "created_at": "2030-01-01T00:00:00Z", "url": f"https://gh/c/{comment_id}",
        "in_reply_to_id": None,
    }


def _open_pr(review_decision="REVIEW_REQUIRED"):
    return {"number": 1, "title": "x", "url": "u", "state": "open",
            "head_branch": "auth-flow", "base_branch": "main", "body": "",
            "review_decision": review_decision, "mergeable": "", "draft": False}


# ── _is_bot_comment ──────────────────────────────────────────────────────


def test_is_bot_comment_true_when_typed_bot_no_subs_configured():
    assert _is_bot_comment({"author_type": "Bot", "author": "any"}, []) is True


def test_is_bot_comment_false_when_user_no_subs_configured():
    assert _is_bot_comment({"author_type": "User", "author": "alice"}, []) is False


def test_is_bot_comment_requires_substring_match_when_subs_configured():
    bots = ["coderabbit", "korbit"]
    assert _is_bot_comment({"author_type": "Bot", "author": "coderabbit-bot"}, bots) is True
    assert _is_bot_comment({"author_type": "Bot", "author": "korbit"}, bots) is True
    # Typed Bot, but not in the configured list — drops out.
    assert _is_bot_comment({"author_type": "Bot", "author": "copilot"}, bots) is False
    # Substring match but not typed Bot — drops out.
    assert _is_bot_comment({"author_type": "User", "author": "coderabbit-fan"}, bots) is False


# ── awaiting_bot_resolution state ────────────────────────────────────────


def test_awaiting_bot_resolution_when_only_bot_comments(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature)

    with patch("canopy.actions.feature_state.gh.find_pull_request",
               return_value=_open_pr()), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([_bot_comment(101)], 0)):
        result = feature_state(ws, "auth-flow")

    assert result["state"] == "awaiting_bot_resolution"
    assert result["next_actions"][0]["action"] == "address_bot_comments"
    assert result["summary"]["actionable_bot_count"] == 1
    assert result["summary"]["actionable_human_count"] == 0


def test_human_comment_routes_to_needs_work_not_bot_state(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature)

    with patch("canopy.actions.feature_state.gh.find_pull_request",
               return_value=_open_pr()), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([_human_comment(202)], 0)):
        result = feature_state(ws, "auth-flow")

    assert result["state"] == "needs_work"
    assert result["summary"]["actionable_human_count"] == 1
    assert result["summary"]["actionable_bot_count"] == 0


def test_mixed_human_and_bot_routes_to_needs_work(workspace_with_feature):
    """Human signal wins; bot count is included in the preview."""
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature)

    with patch("canopy.actions.feature_state.gh.find_pull_request",
               return_value=_open_pr()), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([_human_comment(1), _bot_comment(2)], 0)):
        result = feature_state(ws, "auth-flow")

    assert result["state"] == "needs_work"
    assert result["summary"]["actionable_human_count"] == 1
    assert result["summary"]["actionable_bot_count"] == 1


def test_approved_with_bot_threads_keeps_state_but_adds_secondary_cta(
    workspace_with_feature,
):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature)

    with patch("canopy.actions.feature_state.gh.find_pull_request",
               return_value=_open_pr(review_decision="APPROVED")), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([_bot_comment(303)], 0)):
        result = feature_state(ws, "auth-flow")

    assert result["state"] == "approved"
    actions = result["next_actions"]
    assert actions[0]["action"] == "merge"
    # Secondary CTA appears for the unresolved bot thread.
    assert any(a["action"] == "address_bot_comments" for a in actions)


def test_recorded_resolution_is_subtracted_from_bot_count(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature)

    # Pre-record a resolution for comment 999 against this feature.
    record_resolution(
        workspace_with_feature, comment_id=999, feature="auth-flow",
        repo="repo-a", commit_sha="deadbeef", comment_title="resolved one",
    )

    # Live PR still surfaces both comments — but 999 is filtered out.
    with patch("canopy.actions.feature_state.gh.find_pull_request",
               return_value=_open_pr()), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([_bot_comment(999), _bot_comment(1000)], 0)):
        result = feature_state(ws, "auth-flow")

    assert result["summary"]["actionable_bot_count"] == 1
    assert result["state"] == "awaiting_bot_resolution"


def test_review_bots_augment_narrows_classification(workspace_with_feature):
    """When review_bots is configured, only matching authors count as bots."""
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(
        workspace_with_feature, augments={"review_bots": ["coderabbit"]},
    )

    with patch("canopy.actions.feature_state.gh.find_pull_request",
               return_value=_open_pr()), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([
                   _bot_comment(1, author="coderabbit"),
                   _bot_comment(2, author="copilot"),  # filtered out by augment
               ], 0)):
        result = feature_state(ws, "auth-flow")

    assert result["summary"]["actionable_bot_count"] == 1
    # The non-matching bot author falls into human bucket — augment is the gate.
    assert result["summary"]["actionable_human_count"] == 1
