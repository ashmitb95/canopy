"""Tests for canopy.actions.commit — feature-scoped multi-repo commit."""
import inspect
import json
import os
import subprocess

import pytest

from canopy.actions import commit as commit_mod
from canopy.actions import slots as slots_mod
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
    """Mark `feature` canonical in slots.json."""
    state = slots_mod.read_state(ws) or slots_mod.SlotState()
    state.canonical = slots_mod.CanonicalEntry(
        feature=feature,
        activated_at=slots_mod.now_iso(),
        per_repo_paths={r.config.name: str(r.abs_path) for r in ws.repos},
    )
    slots_mod.write_state(ws, state)


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


# ── Commit is commit-only: no --address / thread-resolution fat ─────────


def test_commit_signature_has_no_address_params():
    sig = inspect.signature(commit_mod.commit)
    assert "address" not in sig.parameters
    assert "resolve_thread" not in sig.parameters


def test_commit_module_imports_no_fat():
    src = inspect.getsource(commit_mod)
    for fat in ("bot_resolutions", "thread_actions", "_per_repo_facts",
                "historian", "list_review_threads"):
        assert fat not in src, f"commit must not reference {fat}"
