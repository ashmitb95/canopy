"""Tests for canopy.actions.commit — feature-scoped multi-repo commit."""
import json
import os
import subprocess

import pytest

from canopy.actions.active_feature import write_active
from canopy.actions.commit import commit
from canopy.actions.errors import BlockerError
from canopy.git import repo as git
from canopy.workspace.config import RepoConfig, WorkspaceConfig
from canopy.workspace.workspace import Workspace


# ── Fixtures + helpers ───────────────────────────────────────────────────

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


def _git(args, cwd):
    subprocess.run(
        ["git"] + args, cwd=cwd, check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )


def _set_canonical(workspace_dir, feature, ws):
    """Mark `feature` canonical in active_feature.json."""
    write_active(ws, feature=feature, per_repo_paths={
        r.config.name: str(r.abs_path) for r in ws.repos
    })


# ── Happy path: explicit feature ─────────────────────────────────────────

def test_commit_all_repos_explicit_feature(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)

    # Modify a tracked file in each repo so there's something to commit.
    (workspace_with_feature / "repo-a" / "src" / "models.py").write_text(
        "class User:\n    new_field: str\n"
    )
    (workspace_with_feature / "repo-b" / "src" / "types.ts").write_text(
        "export interface User { name: string; }\n"
    )

    result = commit(ws, "wave 2.3 test", feature="auth-flow")
    assert result["feature"] == "auth-flow"
    for repo in ("repo-a", "repo-b"):
        assert result["results"][repo]["status"] == "ok"
        assert "sha" in result["results"][repo]
        assert result["results"][repo]["files_changed"] == 1


# ── Canonical feature inferred when no `feature` arg ─────────────────────

def test_commit_uses_canonical_when_no_feature_passed(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    _set_canonical(workspace_with_feature, "auth-flow", ws)

    (workspace_with_feature / "repo-a" / "src" / "app.py").write_text("changed\n")

    result = commit(ws, "from canonical")
    assert result["feature"] == "auth-flow"
    assert result["results"]["repo-a"]["status"] == "ok"
    assert result["results"]["repo-b"]["status"] == "nothing"


# ── No canonical, no explicit → blocker ──────────────────────────────────

def test_commit_blocks_when_no_canonical_and_no_feature(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)

    with pytest.raises(BlockerError) as exc:
        commit(ws, "no scope")
    assert exc.value.code == "no_canonical_feature"


# ── Wrong-branch pre-flight ──────────────────────────────────────────────

def test_commit_blocks_when_repo_on_wrong_branch(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    _git(["checkout", "main"], cwd=workspace_with_feature / "repo-b")

    with pytest.raises(BlockerError) as exc:
        commit(ws, "drifted", feature="auth-flow")
    assert exc.value.code == "wrong_branch"
    assert "repo-b" in exc.value.details["per_repo"]
    assert exc.value.details["per_repo"]["repo-b"]["expected"] == "auth-flow"
    assert exc.value.details["per_repo"]["repo-b"]["actual"] == "main"


# ── Nothing to commit per-repo ──────────────────────────────────────────

def test_commit_returns_nothing_when_repo_clean(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)

    # api is dirty, ui is clean.
    (workspace_with_feature / "repo-a" / "src" / "app.py").write_text("changed\n")

    result = commit(ws, "partial", feature="auth-flow")
    assert result["results"]["repo-a"]["status"] == "ok"
    assert result["results"]["repo-b"]["status"] == "nothing"


# ── Hook failure ────────────────────────────────────────────────────────

def test_commit_reports_hooks_failed(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)

    api = workspace_with_feature / "repo-a"
    hook = api / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'pre-commit failed'\nexit 1\n")
    hook.chmod(0o755)

    (api / "src" / "app.py").write_text("changed\n")
    (workspace_with_feature / "repo-b" / "src" / "types.ts").write_text("changed\n")

    result = commit(ws, "with hook", feature="auth-flow")
    assert result["results"]["repo-a"]["status"] == "hooks_failed"
    assert "pre-commit" in result["results"]["repo-a"]["hook_output"]
    # ui still committed; one repo's hook failure doesn't cancel the others.
    assert result["results"]["repo-b"]["status"] == "ok"


def test_commit_no_hooks_skips_failing_hook(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)

    api = workspace_with_feature / "repo-a"
    hook = api / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)

    (api / "src" / "app.py").write_text("changed\n")
    result = commit(ws, "skip", feature="auth-flow", no_hooks=True)
    assert result["results"]["repo-a"]["status"] == "ok"


# ── Per-repo paths filter ────────────────────────────────────────────────

def test_commit_paths_filter_only_stages_named_files(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)

    api = workspace_with_feature / "repo-a"
    (api / "src" / "app.py").write_text("changed app\n")
    (api / "src" / "models.py").write_text("changed models\n")

    # Only stage app.py via paths filter.
    result = commit(
        ws, "scoped", feature="auth-flow", paths=["src/app.py"],
    )
    assert result["results"]["repo-a"]["status"] == "ok"
    assert result["results"]["repo-a"]["files_changed"] == 1
    # models.py should still be dirty (unstaged) in api.
    assert git.dirty_file_count(api) == 1


# ── Repo subset filter ───────────────────────────────────────────────────

def test_commit_repos_filter_skips_other_repos(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)

    (workspace_with_feature / "repo-a" / "src" / "app.py").write_text("changed\n")
    (workspace_with_feature / "repo-b" / "src" / "types.ts").write_text("changed\n")

    result = commit(ws, "api only", feature="auth-flow", repos=["repo-a"])
    assert "repo-a" in result["results"]
    assert "repo-b" not in result["results"]


def test_commit_repos_filter_outside_feature_blocks(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)

    with pytest.raises(BlockerError) as exc:
        commit(ws, "bogus", feature="auth-flow", repos=["nonexistent"])
    assert exc.value.code == "repos_filter_empty"


# ── Amend ────────────────────────────────────────────────────────────────

def test_commit_amend_replaces_head_in_each_repo(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)

    api = workspace_with_feature / "repo-a"
    ui = workspace_with_feature / "repo-b"
    pre_api = git.head_sha(api)
    pre_ui = git.head_sha(ui)

    # Stage one new change per repo so the amend has content to absorb.
    (api / "src" / "app.py").write_text("amended app\n")
    (ui / "src" / "types.ts").write_text("amended types\n")

    result = commit(ws, "amended", feature="auth-flow", amend=True)
    assert result["results"]["repo-a"]["status"] == "ok"
    assert result["results"]["repo-a"].get("amended") is True
    assert result["results"]["repo-a"]["sha"] != pre_api
    assert result["results"]["repo-b"]["sha"] != pre_ui


# ── Empty-message guard ─────────────────────────────────────────────────

def test_commit_empty_message_raises(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc:
        commit(ws, "", feature="auth-flow")
    assert exc.value.code == "empty_message"


# ── --address (M3): bot-comment resolution ──────────────────────────────


from unittest.mock import patch
from canopy.actions.bot_resolutions import is_resolved, load_resolutions
from canopy.actions.commit import (
    _format_address_message, _comment_title, _parse_comment_id,
)


def _bot_comment(comment_id, *, body="rename foo to bar"):
    return {
        "id": comment_id, "path": "src/auth.py", "line": 1, "body": body,
        "author": "coderabbit", "author_type": "Bot", "state": "",
        "created_at": "2030-01-01T00:00:00Z",
        "url": f"https://github.com/o/r/pull/1#discussion_r{comment_id}",
        "in_reply_to_id": None,
    }


def _set_remote(repo_path, url):
    subprocess.run(
        ["git", "remote", "add", "origin", url],
        cwd=repo_path, check=True, capture_output=True, text=True,
    )


def _open_pr():
    return {"number": 1, "title": "x", "url": "u", "state": "open",
            "head_branch": "auth-flow", "base_branch": "main", "body": "",
            "review_decision": "REVIEW_REQUIRED", "mergeable": "", "draft": False}


# helper unit tests (module-private but worth pinning)


def test_parse_comment_id_accepts_numeric():
    assert _parse_comment_id("123456") == "123456"


def test_parse_comment_id_accepts_hash_form():
    assert _parse_comment_id("#789") == "789"


def test_parse_comment_id_accepts_full_url():
    url = "https://github.com/o/r/pull/142#discussion_r999"
    assert _parse_comment_id(url) == "999"


def test_parse_comment_id_rejects_garbage():
    with pytest.raises(BlockerError) as exc:
        _parse_comment_id("not-an-id")
    assert exc.value.code == "invalid_comment_id"


def test_comment_title_first_line():
    assert _comment_title("first line\nsecond") == "first line"
    assert _comment_title("") == ""


def test_comment_title_truncates():
    long_title = "a" * 200
    out = _comment_title(long_title, max_len=50)
    assert out.endswith("…")
    assert len(out) == 51


def test_format_address_message_with_user_message():
    msg = _format_address_message("rename complete", "rename foo", "https://gh/c/1")
    assert msg.startswith("rename complete")
    assert 'Addresses bot comment: "rename foo" (https://gh/c/1)' in msg


def test_format_address_message_without_user_message():
    msg = _format_address_message("", "rename foo", "https://gh/c/1")
    assert msg == 'Addresses bot comment: "rename foo" (https://gh/c/1)'


# integration tests


def test_commit_with_address_records_resolution(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature, repos=("repo-a",))

    (workspace_with_feature / "repo-a" / "src" / "models.py").write_text(
        "renamed\n"
    )

    with patch("canopy.actions.feature_state.gh.find_pull_request",
               return_value=_open_pr()), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([_bot_comment(123456)], 0)):
        result = commit(
            ws, "user message",
            feature="auth-flow", address="123456",
        )

    assert result["results"]["repo-a"]["status"] == "ok"
    addressed = result["addressed"]
    assert addressed["comment_id"] == "123456"
    assert addressed["recorded"] is True
    assert addressed["sha"]   # has the commit sha
    # Resolution persisted to disk
    assert is_resolved(workspace_with_feature, 123456) is True
    entry = load_resolutions(workspace_with_feature)["123456"]
    assert entry["feature"] == "auth-flow"
    assert entry["repo"] == "repo-a"


def test_commit_with_address_accepts_url(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature, repos=("repo-a",))

    (workspace_with_feature / "repo-a" / "src" / "app.py").write_text("changed\n")

    url = "https://github.com/o/r/pull/1#discussion_r999"
    with patch("canopy.actions.feature_state.gh.find_pull_request",
               return_value=_open_pr()), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([_bot_comment(999)], 0)):
        result = commit(ws, "fix", feature="auth-flow", address=url)

    assert result["addressed"]["comment_id"] == "999"
    assert result["addressed"]["recorded"] is True


def test_commit_with_address_rejects_unknown_id(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature, repos=("repo-a",))

    with patch("canopy.actions.feature_state.gh.find_pull_request",
               return_value=_open_pr()), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([_bot_comment(1)], 0)):
        with pytest.raises(BlockerError) as exc:
            commit(ws, "fix", feature="auth-flow", address="999999")
    assert exc.value.code == "not_a_bot_comment"


def test_commit_with_address_uses_only_auto_message_when_no_message(
    workspace_with_feature,
):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    _set_remote(workspace_with_feature / "repo-a", "git@github.com:owner/repo-a.git")
    ws = _make_workspace(workspace_with_feature, repos=("repo-a",))

    (workspace_with_feature / "repo-a" / "src" / "app.py").write_text("changed\n")

    with patch("canopy.actions.feature_state.gh.find_pull_request",
               return_value=_open_pr()), \
         patch("canopy.actions.feature_state.gh.get_review_comments",
               return_value=([_bot_comment(123, body="please rename hit_rate")], 0)):
        result = commit(ws, "", feature="auth-flow", address="123")

    sha = result["results"]["repo-a"]["sha"]
    msg = subprocess.run(
        ["git", "log", "-1", "--format=%B", sha],
        cwd=workspace_with_feature / "repo-a",
        check=True, capture_output=True, text=True,
    ).stdout
    assert msg.strip().startswith('Addresses bot comment: "please rename hit_rate"')
