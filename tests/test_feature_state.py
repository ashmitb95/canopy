"""Tests for canopy.actions.feature_state — dashboard backend."""
import json
import os
import subprocess
from unittest.mock import patch

import pytest

from canopy.actions.feature_state import feature_state
from canopy.actions.preflight_state import record_result
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


def _set_remote(repo_path, url):
    subprocess.run(
        ["git", "remote", "add", "origin", url],
        cwd=repo_path, check=True, capture_output=True, text=True,
    )


def _git(args, cwd):
    subprocess.run(
        ["git"] + args, cwd=cwd, check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )


def _no_pr(*a, **kw):
    return None


def _no_comments(*a, **kw):
    return ([], 0)


# ── drifted (highest priority) ──────────────────────────────────────────

def test_drift_state_supersedes_everything(workspace_with_feature):
    """Once aligned with feature 'auth-flow', moving ui to main → drifted."""
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    _git(["checkout", "main"], cwd=workspace_with_feature / "repo-b")
    ws = _make_workspace(workspace_with_feature)

    with patch("canopy.actions.feature_state.gh.find_pull_request", side_effect=_no_pr), \
         patch("canopy.actions.feature_state.gh.get_review_comments", side_effect=_no_comments):
        result = feature_state(ws, "auth-flow")

    assert result["state"] == "drifted"
    assert result["next_actions"][0]["action"] == "realign"
    assert "repo-b" in result["summary"]["alignment"]["drifted_repos"]


# ── in_progress (dirty, no fresh preflight) ─────────────────────────────

def test_in_progress_when_dirty_and_no_preflight(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    (workspace_with_feature / "repo-a" / "src" / "app.py").write_text("modified\n")
    ws = _make_workspace(workspace_with_feature)

    with patch("canopy.actions.feature_state.gh.find_pull_request", side_effect=_no_pr), \
         patch("canopy.actions.feature_state.gh.get_review_comments", side_effect=_no_comments):
        result = feature_state(ws, "auth-flow")

    assert result["state"] == "in_progress"
    assert result["next_actions"][0]["action"] == "preflight"
    assert "repo-a" in result["summary"]["dirty_repos"]


# ── ready_to_commit (dirty + fresh preflight passed) ────────────────────

def test_ready_to_commit_when_preflight_passed_for_current_head(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    (workspace_with_feature / "repo-a" / "src" / "app.py").write_text("modified\n")
    ws = _make_workspace(workspace_with_feature)

    # Record a preflight result with the current HEADs as the recorded shas.
    record_result(
        workspace_with_feature, "auth-flow",
        passed=True,
        head_sha_per_repo={
            "repo-a": git.head_sha(workspace_with_feature / "repo-a"),
            "repo-b": git.head_sha(workspace_with_feature / "repo-b"),
        },
    )

    with patch("canopy.actions.feature_state.gh.find_pull_request", side_effect=_no_pr), \
         patch("canopy.actions.feature_state.gh.get_review_comments", side_effect=_no_comments):
        result = feature_state(ws, "auth-flow")

    assert result["state"] == "ready_to_commit"
    assert result["next_actions"][0]["action"] == "commit"


def test_stale_preflight_warns_and_falls_back_to_in_progress(workspace_with_feature):
    """A recorded preflight with an old sha should be 'stale' → in_progress."""
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    (workspace_with_feature / "repo-a" / "src" / "app.py").write_text("modified\n")
    ws = _make_workspace(workspace_with_feature)

    # Record with bogus old sha
    record_result(
        workspace_with_feature, "auth-flow",
        passed=True,
        head_sha_per_repo={"repo-a": "0" * 40, "repo-b": "0" * 40},
    )

    with patch("canopy.actions.feature_state.gh.find_pull_request", side_effect=_no_pr), \
         patch("canopy.actions.feature_state.gh.get_review_comments", side_effect=_no_comments):
        result = feature_state(ws, "auth-flow")

    assert result["state"] == "in_progress"
    assert any(w["code"] == "preflight_stale" for w in result["warnings"])


# ── ready_to_push (clean + ahead of remote) ──────────────────────────────

def test_ready_to_push_when_clean_and_ahead(workspace_with_feature, tmp_path):
    """Set up a fake remote so divergence reports api as ahead."""
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    api = workspace_with_feature / "repo-a"
    ui = workspace_with_feature / "repo-b"
    # Fake remote: bare repo, push initial state, then api adds another commit
    for name, repo_path in [("api-remote", api), ("ui-remote", ui)]:
        bare = tmp_path / f"{name}.git"
        bare.mkdir()
        _git(["init", "--bare", "-b", "main"], cwd=bare)
        _git(["remote", "add", "origin", str(bare)], cwd=repo_path)
        _git(["push", "origin", "auth-flow"], cwd=repo_path)
    # api makes a new commit (becomes ahead of origin/auth-flow)
    (api / "src" / "extra.py").write_text("extra\n")
    _git(["add", "."], cwd=api)
    _git(["commit", "-m", "extra"], cwd=api)

    ws = _make_workspace(workspace_with_feature)
    with patch("canopy.actions.feature_state.gh.find_pull_request", side_effect=_no_pr), \
         patch("canopy.actions.feature_state.gh.get_review_comments", side_effect=_no_comments):
        result = feature_state(ws, "auth-flow")

    assert result["state"] == "ready_to_push"
    assert result["next_actions"][0]["action"] == "push"
    assert "repo-a" in result["summary"]["ahead_repos"]


# ── needs_work (clean + caught up + actionable comments) ────────────────

def test_needs_work_with_actionable_comments(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature)

    fake_pr = {"number": 1, "title": "x", "url": "u", "state": "open",
                "head_branch": "auth-flow", "base_branch": "main", "body": "",
                "review_decision": "REVIEW_REQUIRED", "mergeable": "", "draft": False}
    fake_comment = {
        "path": "src/auth.py", "line": 1, "body": "fix this",
        "author": "reviewer", "author_type": "User", "state": "",
        "created_at": "2030-01-01T00:00:00Z", "url": "", "in_reply_to_id": None,
    }
    with patch("canopy.actions.feature_state.gh.find_pull_request", return_value=fake_pr), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([fake_comment], 0)):
        result = feature_state(ws, "auth-flow")

    assert result["state"] == "needs_work"
    assert result["next_actions"][0]["action"] == "address_review_comments"
    assert result["summary"]["actionable_count"] >= 1


# ── approved (all PRs APPROVED, clean) ──────────────────────────────────

def test_approved_when_all_prs_approved(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature)

    fake_pr = {"number": 1, "title": "x", "url": "u", "state": "open",
                "head_branch": "auth-flow", "base_branch": "main", "body": "",
                "review_decision": "APPROVED", "mergeable": "", "draft": False}
    with patch("canopy.actions.feature_state.gh.find_pull_request", return_value=fake_pr), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([], 0)):
        result = feature_state(ws, "auth-flow")

    assert result["state"] == "approved"
    assert result["next_actions"][0]["action"] == "merge"


# ── awaiting_review (clean + PRs open + no actionable) ─────────────────

def test_awaiting_review_when_pr_open_no_feedback(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature)

    fake_pr = {"number": 1, "title": "x", "url": "u", "state": "open",
                "head_branch": "auth-flow", "base_branch": "main", "body": "",
                "review_decision": "REVIEW_REQUIRED", "mergeable": "", "draft": False}
    with patch("canopy.actions.feature_state.gh.find_pull_request", return_value=fake_pr), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([], 0)):
        result = feature_state(ws, "auth-flow")

    assert result["state"] == "awaiting_review"
    assert result["next_actions"][0]["action"] == "refresh"


# ── no_prs (clean, aligned, no PRs anywhere) ────────────────────────────

def test_no_prs_when_clean_and_no_prs(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature)

    with patch("canopy.actions.feature_state.gh.find_pull_request", side_effect=_no_pr), \
         patch("canopy.actions.feature_state.gh.get_review_comments", side_effect=_no_comments):
        result = feature_state(ws, "auth-flow")

    assert result["state"] == "no_prs"
    assert result["next_actions"][0]["action"] == "pr_create"


# ── changes_requested treated as needs_work ─────────────────────────────

def test_changes_requested_decision_is_needs_work(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature)

    fake_pr = {"number": 1, "title": "x", "url": "u", "state": "open",
                "head_branch": "auth-flow", "base_branch": "main", "body": "",
                "review_decision": "CHANGES_REQUESTED", "mergeable": "", "draft": False}
    with patch("canopy.actions.feature_state.gh.find_pull_request", return_value=fake_pr), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([], 0)):
        result = feature_state(ws, "auth-flow")

    assert result["state"] == "needs_work"


# ── B5: worktree-aware path resolution (R5) ─────────────────────────────

def test_worktree_backed_feature_not_drifted_when_main_on_other_branch(
    workspace_dir,
):
    """A worktree-backed feature must check the worktree's branch, not main's.

    Pre-B5, feature_state always checked main repo's HEAD and reported
    'drifted' for every worktree-backed feature whose branch wasn't also
    in main. The bug suggested 'realign' as the next action — which would
    actively destroy any in-flight work in main.
    """
    api = workspace_dir / "repo-a"
    ui = workspace_dir / "repo-b"

    # Simulate a different feature checked out in main
    _git(["checkout", "-b", "in-flight"], cwd=api)
    _git(["checkout", "-b", "in-flight"], cwd=ui)

    # Create the worktree-backed feature via the coordinator
    ws = _make_workspace(workspace_dir)
    from canopy.features.coordinator import FeatureCoordinator
    coord = FeatureCoordinator(ws)
    coord.create("sin-9-demo", use_worktrees=True)

    # Sanity: features.json records the worktree paths
    features = json.loads(
        (workspace_dir / ".canopy" / "features.json").read_text(),
    )
    assert features["sin-9-demo"]["use_worktrees"] is True
    assert "worktree_paths" in features["sin-9-demo"]

    # Main repos are still on in-flight, NOT on sin-9-demo. Pre-B5 this
    # would report state='drifted' suggesting realign. Post-B5 it must
    # check the worktree path and report a non-drifted state.
    with patch("canopy.actions.feature_state.gh.find_pull_request",
               side_effect=_no_pr), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               side_effect=_no_comments):
        result = feature_state(ws, "sin-9-demo")

    assert result["state"] != "drifted", (
        f"worktree-backed feature should not be drifted; got {result}"
    )


def test_drifted_worktree_feature_suggests_switch_not_realign(workspace_dir):
    """If a worktree IS on the wrong branch (rare — manual git checkout
    inside the worktree), the suggested fix is `switch`, not `realign`.
    Realign would touch main, which is the exact thing worktrees were
    supposed to protect."""
    api = workspace_dir / "repo-a"
    ui = workspace_dir / "repo-b"

    _git(["checkout", "-b", "in-flight"], cwd=api)
    _git(["checkout", "-b", "in-flight"], cwd=ui)

    ws = _make_workspace(workspace_dir)
    from canopy.features.coordinator import FeatureCoordinator
    coord = FeatureCoordinator(ws)
    coord.create("sin-10-demo", use_worktrees=True)

    # Manually break the worktree — checkout a different branch inside it
    wt_api = workspace_dir / ".canopy" / "worktrees" / "sin-10-demo" / "repo-a"
    _git(["checkout", "-b", "manual-detour"], cwd=wt_api)

    with patch("canopy.actions.feature_state.gh.find_pull_request",
               side_effect=_no_pr), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               side_effect=_no_comments):
        result = feature_state(ws, "sin-10-demo")

    assert result["state"] == "drifted"
    assert result["next_actions"][0]["action"] == "switch"
    assert result["summary"]["alignment"]["has_worktrees"] is True


def test_per_repo_facts_use_worktree_path_for_dirty_check(workspace_dir):
    """Dirty/branch checks must read from the worktree, not main.

    Make main clean but introduce a dirty file inside the worktree;
    feature_state must report the feature as dirty (via dirty_repos)."""
    api = workspace_dir / "repo-a"
    ui = workspace_dir / "repo-b"

    _git(["checkout", "-b", "in-flight"], cwd=api)
    _git(["checkout", "-b", "in-flight"], cwd=ui)

    ws = _make_workspace(workspace_dir)
    from canopy.features.coordinator import FeatureCoordinator
    coord = FeatureCoordinator(ws)
    coord.create("sin-11-demo", use_worktrees=True)

    # Modify a file inside the api worktree
    wt_api = workspace_dir / ".canopy" / "worktrees" / "sin-11-demo" / "repo-a"
    (wt_api / "src" / "app.py").write_text("dirty in worktree\n")

    with patch("canopy.actions.feature_state.gh.find_pull_request",
               side_effect=_no_pr), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               side_effect=_no_comments):
        result = feature_state(ws, "sin-11-demo")

    assert "repo-a" in result["summary"]["dirty_repos"], (
        f"expected api in dirty_repos (worktree was dirty); summary={result['summary']}"
    )
