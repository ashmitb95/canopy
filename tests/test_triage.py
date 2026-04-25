"""Tests for canopy.actions.triage — daily entry-point query."""
import json
import subprocess
from unittest.mock import patch

import pytest

from canopy.actions.errors import BlockerError
from canopy.actions.triage import triage
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


def _pr(number, branch, decision="REVIEW_REQUIRED", title="x"):
    return {
        "number": number, "title": title, "url": f"https://github.com/owner/x/pull/{number}",
        "state": "open", "head_branch": branch, "base_branch": "dev", "body": "",
        "review_decision": decision, "mergeable": "", "draft": False,
    }


def _comment(path="src/x.py", body="fix", author="reviewer", author_type="User",
             created_at="2030-01-01T00:00:00Z"):
    return {
        "path": path, "line": 1, "body": body, "author": author,
        "author_type": author_type, "state": "", "created_at": created_at,
        "url": "", "in_reply_to_id": None,
    }


# ── Empty workspace returns empty list ──────────────────────────────────

def test_no_prs_returns_empty(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    _set_remote(workspace_with_feature / "ui", "git@github.com:owner/ui.git")
    with patch("canopy.actions.triage.gh.list_open_prs", return_value=[]):
        result = triage(ws)
    assert result["features"] == []


# ── Single feature, multi-repo ──────────────────────────────────────────

def test_groups_multi_repo_feature_via_explicit_lane(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {
            "repos": ["api", "ui"], "status": "active",
            "linear_issue": "ENG-412",
            "linear_url": "https://linear.app/x/ENG-412",
            "linear_title": "Auth Flow",
        },
    })
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    _set_remote(workspace_with_feature / "ui", "git@github.com:owner/ui.git")

    def _list(workspace_root, owner, slug, author=None, **kw):
        if slug == "api":
            return [_pr(100, "auth-flow", decision="REVIEW_REQUIRED")]
        return [_pr(200, "auth-flow", decision="REVIEW_REQUIRED")]

    with patch("canopy.actions.triage.gh.list_open_prs", side_effect=_list), \
         patch("canopy.actions.triage.gh.get_review_comments",
               return_value=([], 0)):
        result = triage(ws)

    assert len(result["features"]) == 1
    f = result["features"][0]
    assert f["feature"] == "auth-flow"
    assert f["linear_issue"] == "ENG-412"
    assert f["priority"] == "review_required"
    assert set(f["repos"].keys()) == {"api", "ui"}


# ── Implicit feature (branch shared, not in features.json) ──────────────

def test_implicit_feature_when_branch_shared(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    _set_remote(workspace_with_feature / "ui", "git@github.com:owner/ui.git")

    def _list(workspace_root, owner, slug, author=None, **kw):
        if slug == "api":
            return [_pr(100, "DOC-3010")]
        return [_pr(200, "DOC-3010")]

    with patch("canopy.actions.triage.gh.list_open_prs", side_effect=_list), \
         patch("canopy.actions.triage.gh.get_review_comments",
               return_value=([], 0)):
        result = triage(ws)

    assert len(result["features"]) == 1
    assert result["features"][0]["feature"] == "DOC-3010"
    assert set(result["features"][0]["repos"].keys()) == {"api", "ui"}


# ── Single-repo PR also surfaces as a feature ───────────────────────────

def test_single_repo_pr_is_a_feature(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    _set_remote(workspace_with_feature / "ui", "git@github.com:owner/ui.git")

    def _list(workspace_root, owner, slug, author=None, **kw):
        if slug == "ui":
            return [_pr(50, "DOC-3008")]
        return []

    with patch("canopy.actions.triage.gh.list_open_prs", side_effect=_list), \
         patch("canopy.actions.triage.gh.get_review_comments",
               return_value=([], 0)):
        result = triage(ws)

    assert len(result["features"]) == 1
    assert result["features"][0]["feature"] == "DOC-3008"
    assert list(result["features"][0]["repos"].keys()) == ["ui"]


# ── Priority tiers ──────────────────────────────────────────────────────

def test_changes_requested_outranks_review_required(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    _set_remote(workspace_with_feature / "ui", "git@github.com:owner/ui.git")

    def _list(workspace_root, owner, slug, author=None, **kw):
        if slug == "api":
            return [_pr(100, "feat-a", decision="CHANGES_REQUESTED")]
        return [_pr(200, "feat-b", decision="REVIEW_REQUIRED")]

    with patch("canopy.actions.triage.gh.list_open_prs", side_effect=_list), \
         patch("canopy.actions.triage.gh.get_review_comments",
               return_value=([], 0)):
        result = triage(ws)

    priorities = [f["priority"] for f in result["features"]]
    # first should be the CHANGES_REQUESTED one
    assert priorities[0] == "changes_requested"
    assert priorities[1] == "review_required"


def test_bot_actionable_promotes_to_review_required_with_bot(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    _set_remote(workspace_with_feature / "ui", "git@github.com:owner/ui.git")

    def _list(workspace_root, owner, slug, author=None, **kw):
        if slug == "api":
            return [_pr(100, "bot-feat", decision="REVIEW_REQUIRED")]
        return []

    bot_comment = _comment(author="claude[bot]", author_type="Bot")
    with patch("canopy.actions.triage.gh.list_open_prs", side_effect=_list), \
         patch("canopy.actions.triage.gh.get_review_comments",
               return_value=([bot_comment], 0)):
        result = triage(ws)

    assert result["features"][0]["priority"] == "review_required_with_bot_comments"
    assert result["features"][0]["repos"]["api"]["has_actionable_bot_thread"] is True


def test_all_approved_priority(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    _set_remote(workspace_with_feature / "ui", "git@github.com:owner/ui.git")

    def _list(workspace_root, owner, slug, author=None, **kw):
        if slug == "api":
            return [_pr(100, "ready", decision="APPROVED")]
        return [_pr(200, "ready", decision="APPROVED")]

    with patch("canopy.actions.triage.gh.list_open_prs", side_effect=_list), \
         patch("canopy.actions.triage.gh.get_review_comments",
               return_value=([], 0)):
        result = triage(ws)

    assert result["features"][0]["priority"] == "approved"


# ── Sorted by priority order ────────────────────────────────────────────

def test_features_ordered_by_priority(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    _set_remote(workspace_with_feature / "ui", "git@github.com:owner/ui.git")

    def _list(workspace_root, owner, slug, author=None, **kw):
        if slug == "api":
            return [
                _pr(1, "approved-feat", decision="APPROVED"),
                _pr(2, "changes-feat", decision="CHANGES_REQUESTED"),
                _pr(3, "review-feat", decision="REVIEW_REQUIRED"),
            ]
        return []

    with patch("canopy.actions.triage.gh.list_open_prs", side_effect=_list), \
         patch("canopy.actions.triage.gh.get_review_comments",
               return_value=([], 0)):
        result = triage(ws)

    priorities = [f["priority"] for f in result["features"]]
    # changes_requested first, then review_required, then approved
    assert priorities == ["changes_requested", "review_required", "approved"]


# ── Errors ──────────────────────────────────────────────────────────────

def test_unknown_repo_raises(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        triage(ws, repos=["api", "ghost"])
    assert exc_info.value.code == "unknown_repo"
