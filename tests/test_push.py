"""Tests for canopy.actions.push — feature-scoped multi-repo push."""
import json
import os
import subprocess

import pytest

from canopy.actions.active_feature import write_active
from canopy.actions.errors import BlockerError
from canopy.actions.push import push
from canopy.git import repo as git
from canopy.workspace.config import RepoConfig, WorkspaceConfig
from canopy.workspace.workspace import Workspace


def _git(args, cwd):
    subprocess.run(
        ["git"] + args, cwd=cwd, check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )


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


def _wire_remote(repo_path):
    """Initialize a bare remote next to ``repo_path`` and configure origin."""
    bare = repo_path.parent / f"{repo_path.name}.git"
    bare.mkdir(exist_ok=True)
    _git(["init", "--bare", "-b", "main"], cwd=bare)
    _git(["remote", "add", "origin", str(bare)], cwd=repo_path)
    return bare


@pytest.fixture
def workspace_with_remotes(workspace_with_feature):
    """Wire a bare remote for each repo so push has somewhere to go."""
    for name in ("api", "ui"):
        _wire_remote(workspace_with_feature / name)
    return workspace_with_feature


# ── No canonical, no explicit → blocker ──────────────────────────────────

def test_push_blocks_when_no_canonical_and_no_feature(workspace_with_remotes):
    _features_file(workspace_with_remotes, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_remotes)

    with pytest.raises(BlockerError) as exc:
        push(ws)
    assert exc.value.code == "no_canonical_feature"


# ── No upstream + no set_upstream → blocker ─────────────────────────────

def test_push_blocks_when_no_upstream_and_no_flag(workspace_with_remotes):
    _features_file(workspace_with_remotes, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_remotes)

    with pytest.raises(BlockerError) as exc:
        push(ws, feature="auth-flow")
    assert exc.value.code == "no_upstream"
    assert "api" in exc.value.details["per_repo"]
    assert "ui" in exc.value.details["per_repo"]
    assert exc.value.details["per_repo"]["api"] == "auth-flow"
    # Fix action should propose set_upstream=True for the same feature.
    fix = exc.value.fix_actions[0]
    assert fix.action == "push"
    assert fix.args.get("set_upstream") is True


# ── set_upstream publishes the branch ────────────────────────────────────

def test_push_set_upstream_publishes_each_repo(workspace_with_remotes):
    _features_file(workspace_with_remotes, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_remotes)

    result = push(ws, feature="auth-flow", set_upstream=True)
    assert result["feature"] == "auth-flow"
    for repo in ("api", "ui"):
        assert result["results"][repo]["status"] == "ok"
        assert result["results"][repo].get("set_upstream") is True
        assert git.has_upstream(workspace_with_remotes / repo, "auth-flow")


# ── Up-to-date short-circuit after publish ──────────────────────────────

def test_push_up_to_date_after_initial_publish(workspace_with_remotes):
    _features_file(workspace_with_remotes, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_remotes)
    push(ws, feature="auth-flow", set_upstream=True)

    again = push(ws, feature="auth-flow")
    for repo in ("api", "ui"):
        assert again["results"][repo]["status"] == "up_to_date"
        assert again["results"][repo]["pushed_count"] == 0


# ── Pushed count after a new commit ─────────────────────────────────────

def test_push_pushed_count_advances(workspace_with_remotes):
    _features_file(workspace_with_remotes, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_remotes)
    push(ws, feature="auth-flow", set_upstream=True)

    # Add a new commit in api only.
    api = workspace_with_remotes / "api"
    (api / "new.py").write_text("new\n")
    _git(["add", "."], cwd=api)
    _git(["commit", "-m", "second on auth-flow"], cwd=api)

    result = push(ws, feature="auth-flow")
    assert result["results"]["api"]["status"] == "ok"
    assert result["results"]["api"]["pushed_count"] == 1
    assert result["results"]["ui"]["status"] == "up_to_date"


# ── Dry-run ─────────────────────────────────────────────────────────────

def test_push_dry_run_does_not_advance_remote(workspace_with_remotes):
    _features_file(workspace_with_remotes, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_remotes)
    push(ws, feature="auth-flow", set_upstream=True)

    api = workspace_with_remotes / "api"
    (api / "new.py").write_text("new\n")
    _git(["add", "."], cwd=api)
    _git(["commit", "-m", "second"], cwd=api)

    result = push(ws, feature="auth-flow", dry_run=True)
    assert result["results"]["api"].get("dry_run") is True
    # Real upstream still 1 commit behind after dry-run.
    assert git.unpushed_count(api, "auth-flow") == 1


# ── Repo subset filter ──────────────────────────────────────────────────

def test_push_repos_filter(workspace_with_remotes):
    _features_file(workspace_with_remotes, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_remotes)

    result = push(
        ws, feature="auth-flow", repos=["api"], set_upstream=True,
    )
    assert "api" in result["results"]
    assert "ui" not in result["results"]


# ── Canonical fallback ──────────────────────────────────────────────────

def test_push_uses_canonical_when_no_feature(workspace_with_remotes):
    _features_file(workspace_with_remotes, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_remotes)
    write_active(ws, feature="auth-flow", per_repo_paths={
        r.config.name: str(r.abs_path) for r in ws.repos
    })

    result = push(ws, set_upstream=True)
    assert result["feature"] == "auth-flow"
    for repo in ("api", "ui"):
        assert result["results"][repo]["status"] == "ok"


# ── Rejected: non-fast-forward ───────────────────────────────────────────

def test_push_rejected_on_non_fast_forward(workspace_with_remotes, tmp_path):
    _features_file(workspace_with_remotes, {
        "auth-flow": {"repos": ["api", "ui"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_remotes)
    push(ws, feature="auth-flow", set_upstream=True)

    # Push a divergent commit to api's bare from a clone, then create a
    # local commit that rejects on the next push.
    api = workspace_with_remotes / "api"
    bare = workspace_with_remotes / "api.git"
    second = tmp_path / "second-api"
    second.mkdir()
    _git(["clone", "--branch", "auth-flow", str(bare), str(second)], cwd=tmp_path)
    _git(["config", "user.email", "u@u.com"], cwd=second)
    _git(["config", "user.name", "Other"], cwd=second)
    (second / "from_other.py").write_text("from other\n")
    _git(["add", "."], cwd=second)
    _git(["commit", "-m", "diverged on auth-flow"], cwd=second)
    _git(["push", "origin", "auth-flow"], cwd=second)

    # Local repo writes its own commit → push rejects.
    (api / "local_only.py").write_text("local\n")
    _git(["add", "."], cwd=api)
    _git(["commit", "-m", "local on auth-flow"], cwd=api)

    result = push(ws, feature="auth-flow")
    assert result["results"]["api"]["status"] == "rejected"
    assert "reason" in result["results"]["api"]
