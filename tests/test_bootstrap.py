"""Smoke tests for ``canopy worktree-bootstrap`` (M6)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from canopy.actions.bootstrap import (
    _copy_env_files, _run_install, _validate_steps,
    bootstrap_feature, bootstrap_repo,
)
from canopy.actions.ide_workspace import render_code_workspace
from canopy.actions.errors import BlockerError
from canopy.workspace.config import RepoConfig, load_config
from canopy.workspace.workspace import Workspace


# ── env-file copy ──────────────────────────────────────────────────────

def test_copy_env_files_copies_existing_files(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir(); dst.mkdir()
    (src / ".env").write_text("FOO=bar\n")
    (src / ".env.local").write_text("DB=local\n")

    result = _copy_env_files([".env", ".env.local"], src, dst, force=False)
    assert result["status"] == "ok"
    assert sorted(result["files_copied"]) == [".env", ".env.local"]
    assert (dst / ".env").read_text() == "FOO=bar\n"


def test_copy_env_files_handles_missing_source(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir(); dst.mkdir()
    # No .env in src

    result = _copy_env_files([".env"], src, dst, force=False)
    assert result["status"] == "missing_source"
    assert result["files_missing"] == [".env"]


def test_copy_env_files_skips_existing_destination(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    dst = tmp_path / "dst"; dst.mkdir()
    (src / ".env").write_text("FROM_SRC\n")
    (dst / ".env").write_text("ALREADY_HERE\n")

    result = _copy_env_files([".env"], src, dst, force=False)
    assert result["files_skipped"] == [".env"]
    assert (dst / ".env").read_text() == "ALREADY_HERE\n"


def test_copy_env_files_force_overwrites(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    dst = tmp_path / "dst"; dst.mkdir()
    (src / ".env").write_text("FROM_SRC\n")
    (dst / ".env").write_text("OLD\n")

    result = _copy_env_files([".env"], src, dst, force=True)
    assert result["files_copied"] == [".env"]
    assert (dst / ".env").read_text() == "FROM_SRC\n"


def test_copy_env_files_nested_paths(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    dst = tmp_path / "dst"; dst.mkdir()
    (src / "apps" / "web").mkdir(parents=True)
    (src / "apps" / "web" / ".env.local").write_text("WEB\n")

    result = _copy_env_files(["apps/web/.env.local"], src, dst, force=False)
    assert result["status"] == "ok"
    assert (dst / "apps" / "web" / ".env.local").read_text() == "WEB\n"


# ── dep install ────────────────────────────────────────────────────────

def test_run_install_returns_ok_for_zero_exit(tmp_path):
    result = _run_install("true", tmp_path)
    assert result["status"] == "ok"
    assert result["exit_code"] == 0


def test_run_install_returns_failed_with_stderr_tail(tmp_path):
    # `false` exits 1 with no stderr — make sure status flips correctly
    result = _run_install("false", tmp_path)
    assert result["status"] == "failed"
    assert result["exit_code"] != 0


# ── step validation ────────────────────────────────────────────────────

def test_validate_steps_accepts_known():
    assert _validate_steps(["env", "deps"]) == {"env", "deps"}


def test_validate_steps_rejects_unknown():
    with pytest.raises(BlockerError) as e:
        _validate_steps(["env", "bogus"])
    assert e.value.code == "unknown_bootstrap_step"


def test_validate_steps_default_is_all():
    assert _validate_steps(None) == {"env", "deps", "ide", "hooks"}


# ── ide-workspace renderer ────────────────────────────────────────────

@pytest.fixture
def workspace_with_bootstrap_config(workspace_dir) -> Workspace:
    """Workspace with a canopy.toml that exercises the new bootstrap fields."""
    toml = """
[workspace]
name = "demo"
ide = "vscode"

[[repos]]
name = "repo-a"
path = "./repo-a"
env_files = [".env", ".env.local"]
install_cmd = "true"
ide_settings = { python = ".venv/bin/python" }

[[repos]]
name = "repo-b"
path = "./repo-b"
env_files = []
install_cmd = ""
"""
    (workspace_dir / "canopy.toml").write_text(toml)
    return Workspace(load_config(workspace_dir))


def test_render_code_workspace_includes_per_repo_settings(workspace_with_bootstrap_config):
    paths = {
        "repo-a": Path("/wt/repo-a"),
        "repo-b": Path("/wt/repo-b"),
    }
    body = render_code_workspace(workspace_with_bootstrap_config, "auth-flow", paths)
    parsed = json.loads(body)
    assert {"name": "repo-a (auth-flow)", "path": "/wt/repo-a",
            "settings": {"python": ".venv/bin/python"}} in parsed["folders"]
    assert {"name": "repo-b (auth-flow)", "path": "/wt/repo-b"} in parsed["folders"]
    assert parsed["settings"]["canopy.feature"] == "auth-flow"


# ── bootstrap_repo (single-repo path) ─────────────────────────────────

def test_bootstrap_repo_runs_env_and_deps(tmp_path, workspace_with_bootstrap_config):
    workspace = workspace_with_bootstrap_config
    api_path = workspace.config.root / "repo-a"
    (api_path / ".env").write_text("FOO\n")
    (api_path / ".env.local").write_text("LOCAL\n")

    worktree = tmp_path / "wt-a"
    worktree.mkdir()

    result = bootstrap_repo(
        workspace, "auth-flow", "repo-a", worktree,
        force=False, steps=("env", "deps"),
    )
    assert result["env"]["status"] == "ok"
    assert sorted(result["env"]["files_copied"]) == [".env", ".env.local"]
    assert result["deps"]["status"] == "ok"


# ── bootstrap_feature end-to-end ──────────────────────────────────────

def test_bootstrap_feature_writes_ide_workspace(tmp_path, workspace_with_bootstrap_config):
    workspace = workspace_with_bootstrap_config
    api_path = workspace.config.root / "repo-a"
    (api_path / ".env").write_text("X\n")
    (api_path / ".env.local").write_text("Y\n")

    wt_a = tmp_path / "wt-a"; wt_a.mkdir()
    wt_b = tmp_path / "wt-b"; wt_b.mkdir()

    state_dir = workspace.config.root / ".canopy"
    state_dir.mkdir(exist_ok=True)
    (state_dir / "features.json").write_text(json.dumps({
        "auth-flow": {
            "repos": ["repo-a", "repo-b"],
            "status": "active",
            "worktree_paths": {"repo-a": str(wt_a), "repo-b": str(wt_b)},
        }
    }))

    result = bootstrap_feature(workspace, "auth-flow")
    assert result["feature"] == "auth-flow"
    assert result["results"]["repo-a"]["env"]["status"] == "ok"
    assert result["results"]["repo-b"]["env"]["status"] == "skipped"
    assert result["ide"]["status"] == "ok"
    ide_path = Path(result["ide"]["path"])
    assert ide_path.exists()
    body = json.loads(ide_path.read_text())
    repo_names = sorted(folder["name"] for folder in body["folders"])
    assert repo_names == ["repo-a (auth-flow)", "repo-b (auth-flow)"]


def test_bootstrap_feature_blocks_when_no_worktrees(workspace_with_bootstrap_config):
    state_dir = workspace_with_bootstrap_config.config.root / ".canopy"
    state_dir.mkdir(exist_ok=True)
    (state_dir / "features.json").write_text(json.dumps({
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    }))
    with pytest.raises(BlockerError) as e:
        bootstrap_feature(workspace_with_bootstrap_config, "auth-flow")
    assert e.value.code == "no_worktrees"


def _ws(root):
    from canopy.workspace.workspace import Workspace
    from canopy.workspace.config import load_config
    return Workspace(load_config(root))


# ── hooks step (per-clone husky install) ───────────────────────────────

def test_bootstrap_hooks_step_installs(canopy_toml_for_workspace, monkeypatch):
    from canopy.actions import bootstrap
    calls = []
    monkeypatch.setattr(bootstrap, "_run_hook_install",
                        lambda worktree_path, repo_cfg: calls.append(worktree_path) or
                        {"status": "ok", "mechanism": "husky-prepare"})
    root = canopy_toml_for_workspace
    result = bootstrap.bootstrap_repo(
        _ws(root), "auth-flow", "repo-a", root / "repo-a", steps=("hooks",))
    assert result["hooks"]["status"] == "ok"
    assert calls


def test_bootstrap_hooks_skipped_when_no_husky(canopy_toml_for_workspace):
    from canopy.actions import bootstrap
    root = canopy_toml_for_workspace
    # repo-a has no package.json prepare script and no .husky/ → skipped
    result = bootstrap.bootstrap_repo(
        _ws(root), "auth-flow", "repo-a", root / "repo-a", steps=("hooks",))
    assert result["hooks"]["status"] == "skipped"


def test_resolve_worktree_paths_uses_slots_json_for_warm_feature(workspace_with_slots):
    """Wave 3.0: a warm feature's worktree paths come from its SLOT, not the
    legacy features.json worktree_paths cache (which is empty in 3.0). Before
    this fix, bootstrap raised no_worktrees for every warm 3.0 feature."""
    from canopy.actions.bootstrap import _resolve_worktree_paths
    from canopy.actions import slots as sm

    ws = workspace_with_slots  # Y warm in worktree-1 (repo-a + repo-b)
    sid = sm.slot_for_feature(ws, "Y")
    assert sid is not None

    paths = _resolve_worktree_paths(ws, "Y")
    assert set(paths) == {"repo-a", "repo-b"}
    assert paths["repo-a"] == sm.slot_worktree_path(ws, sid, "repo-a")
    assert (paths["repo-a"] / ".git").exists()


# ── bootstrap status marker (Task 7) ───────────────────────────────────

def test_bootstrap_status_marker_helpers(canopy_toml_for_workspace):
    from canopy.actions import slots as sm
    ws = _ws(canopy_toml_for_workspace)
    sm.set_bootstrap_status(ws, "worktree-1", "repo-a", "installing")
    assert sm.get_bootstrap_status(ws, "worktree-1", "repo-a") == "installing"
    sm.set_bootstrap_status(ws, "worktree-1", "repo-a", "ready")
    assert sm.get_bootstrap_status(ws, "worktree-1", "repo-a") == "ready"


def test_bootstrap_status_preserves_other_state(canopy_toml_for_workspace):
    from canopy.actions import slots as sm
    ws = _ws(canopy_toml_for_workspace)
    st = sm.SlotState(slot_count=2)
    st.last_touched["feat-x"] = "2026-01-01T00:00:00Z"
    sm.write_state(ws, st)
    sm.set_bootstrap_status(ws, "worktree-1", "repo-a", "installing")
    reloaded = sm.read_state(ws)
    assert reloaded.last_touched.get("feat-x") == "2026-01-01T00:00:00Z"  # untouched
    assert reloaded.bootstrap["worktree-1"]["repo-a"] == "installing"


def test_deps_skipped_when_lockfile_unchanged(canopy_toml_for_workspace, monkeypatch):
    from canopy.actions import bootstrap
    root = canopy_toml_for_workspace
    ran = []
    monkeypatch.setattr(bootstrap, "_run_install",
                        lambda *a, **k: ran.append(1) or {"status": "ok", "exit_code": 0})
    wt = root / "repo-a"
    (wt / "pnpm-lock.yaml").write_text("lock-v1\n")
    bootstrap.bootstrap_repo(_ws(root), "auth-flow", "repo-a", wt, steps=("deps",))
    bootstrap.bootstrap_repo(_ws(root), "auth-flow", "repo-a", wt, steps=("deps",))
    assert len(ran) == 1                     # second call short-circuits
