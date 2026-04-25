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

def test_per_repo_branches_map_groups_mismatched_branches(workspace_with_feature):
    """doc-1003 has different branch names per repo; explicit `branches`
    map in features.json should group them under one feature lane."""
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
    ws = _make_workspace(workspace_with_feature)
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    _set_remote(workspace_with_feature / "ui", "git@github.com:owner/ui.git")

    def _list(workspace_root, owner, slug, author=None, **kw):
        if slug == "api":
            return [_pr(11, "doc-1003-fixes")]
        return [_pr(22, "DOC-1003-fixes-v2")]

    with patch("canopy.actions.triage.gh.list_open_prs", side_effect=_list), \
         patch("canopy.actions.triage.gh.get_review_comments",
               return_value=([], 0)):
        result = triage(ws)

    assert len(result["features"]) == 1
    assert result["features"][0]["feature"] == "doc-1003"
    assert set(result["features"][0]["repos"].keys()) == {"api", "ui"}


def test_unknown_repo_raises(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        triage(ws, repos=["api", "ghost"])
    assert exc_info.value.code == "unknown_repo"


# ── PR3 step 3: canonical-slot enrichment ───────────────────────────────

def test_triage_marks_canonical_feature(workspace_with_feature):
    """When a feature is the active canonical, triage tags it
    is_canonical=True + physical_state='canonical' + per-repo path =
    main repo."""
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    _set_remote(workspace_with_feature / "ui", "git@github.com:owner/ui.git")
    ws = _make_workspace(workspace_with_feature)

    # Make auth-flow canonical
    from canopy.actions.switch import switch
    switch(ws, "auth-flow")

    def _list(_root, _owner, slug, author=None, **kw):
        return [_pr(1, "auth-flow")]

    with patch("canopy.actions.triage.gh.list_open_prs", side_effect=_list), \
         patch("canopy.actions.triage.gh.get_review_comments",
               return_value=([], 0)):
        result = triage(ws)

    assert result["canonical_feature"] == "auth-flow"
    feat = result["features"][0]
    assert feat["feature"] == "auth-flow"
    assert feat["is_canonical"] is True
    assert feat["physical_state"] == "canonical"
    # Per-repo paths point at main checkouts
    for r in ("api", "ui"):
        info = feat["repos"][r]
        assert info["physical_state"] == "canonical"
        assert info["path"].endswith(f"/{r}")


def test_triage_marks_warm_feature_with_worktree_path(workspace_with_feature):
    """A non-canonical but worktree-backed feature reports physical_state='warm'
    with per-repo paths pointing at the warm worktree dir."""
    # Need a second feature so auth-flow can become warm
    api = workspace_with_feature / "api"
    ui = workspace_with_feature / "ui"
    subprocess.run(["git", "checkout", "-qb", "feat-b"], cwd=api, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "fb"], cwd=api, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=api, check=True)
    subprocess.run(["git", "checkout", "-qb", "feat-b"], cwd=ui, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "fb"], cwd=ui, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=ui, check=True)

    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
        "feat-b": {"repos": ["api", "ui"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    _set_remote(workspace_with_feature / "ui", "git@github.com:owner/ui.git")
    ws = _make_workspace(workspace_with_feature)

    from canopy.actions.switch import switch
    switch(ws, "auth-flow")    # canonical = auth-flow
    switch(ws, "feat-b")        # canonical = feat-b; auth-flow → warm

    def _list(_root, _owner, slug, author=None, **kw):
        return [_pr(1, "auth-flow")]    # only auth-flow has a PR

    with patch("canopy.actions.triage.gh.list_open_prs", side_effect=_list), \
         patch("canopy.actions.triage.gh.get_review_comments",
               return_value=([], 0)):
        result = triage(ws)

    assert result["canonical_feature"] == "feat-b"
    feat = next(f for f in result["features"] if f["feature"] == "auth-flow")
    assert feat["is_canonical"] is False
    assert feat["physical_state"] == "warm"
    for r in ("api", "ui"):
        info = feat["repos"][r]
        assert info["physical_state"] == "warm"
        assert ".canopy/worktrees/auth-flow/" in info["path"]


def test_triage_marks_cold_feature_no_worktree(workspace_with_feature):
    """A feature with no worktree (just a branch) reports physical_state='cold'
    and an empty per-repo path."""
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "api", "git@github.com:owner/api.git")
    _set_remote(workspace_with_feature / "ui", "git@github.com:owner/ui.git")
    ws = _make_workspace(workspace_with_feature)
    # No switch — no active feature, no warm worktree

    def _list(_root, _owner, slug, author=None, **kw):
        return [_pr(1, "auth-flow")]

    with patch("canopy.actions.triage.gh.list_open_prs", side_effect=_list), \
         patch("canopy.actions.triage.gh.get_review_comments",
               return_value=([], 0)):
        result = triage(ws)

    assert result["canonical_feature"] is None
    feat = result["features"][0]
    assert feat["is_canonical"] is False
    assert feat["physical_state"] == "cold"
    for r in ("api", "ui"):
        assert feat["repos"][r]["physical_state"] == "cold"
        assert feat["repos"][r]["path"] == ""
