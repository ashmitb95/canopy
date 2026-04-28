"""Tests for canopy.git.hooks (install/uninstall, state file, worktrees)."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from canopy.git.hooks import (
    install_hook, uninstall_hook, hook_status,
    read_heads_state, resolve_hooks_dir,
)


def _git(args, cwd):
    subprocess.run(
        ["git"] + args, cwd=cwd, check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )


@pytest.fixture
def workspace(tmp_path):
    """A workspace root with one git repo named 'repo-a'."""
    root = tmp_path / "ws"
    root.mkdir()
    api = root / "repo-a"
    api.mkdir()
    _git(["init", "-b", "main"], cwd=api)
    (api / "README").write_text("x\n")
    _git(["add", "."], cwd=api)
    _git(["commit", "-m", "init"], cwd=api)
    return root, api


def test_install_creates_hook(workspace):
    root, api = workspace
    result = install_hook(api, "repo-a", root)
    assert result.action == "installed"
    hook = api / ".git" / "hooks" / "post-checkout"
    assert hook.exists() and os.access(hook, os.X_OK)
    content = hook.read_text()
    assert "__CANOPY_HOOK_MARKER__" in content
    assert '"repo-a"' in content
    assert str(root.resolve()) in content


def test_reinstall_overwrites_existing_canopy_hook(workspace):
    root, api = workspace
    install_hook(api, "repo-a", root)
    result = install_hook(api, "repo-a", root)
    assert result.action == "reinstalled"


def test_install_chains_existing_user_hook(workspace):
    root, api = workspace
    hook_dir = api / ".git" / "hooks"
    hook_dir.mkdir(exist_ok=True)
    user_hook = hook_dir / "post-checkout"
    user_hook.write_text("#!/bin/sh\necho user hook\n")
    user_hook.chmod(0o755)

    result = install_hook(api, "repo-a", root)
    assert result.action == "chained_existing"
    chained = hook_dir / "post-checkout.canopy-chained"
    assert chained.exists()
    assert "user hook" in chained.read_text()


def test_uninstall_restores_chained_hook(workspace):
    root, api = workspace
    user_hook = api / ".git" / "hooks" / "post-checkout"
    user_hook.parent.mkdir(exist_ok=True)
    user_hook.write_text("#!/bin/sh\necho user\n")
    user_hook.chmod(0o755)

    install_hook(api, "repo-a", root)
    result = uninstall_hook(api, "repo-a")
    assert result.action == "uninstalled_and_restored"
    assert user_hook.exists()
    assert "user" in user_hook.read_text()


def test_uninstall_removes_canopy_hook(workspace):
    root, api = workspace
    install_hook(api, "repo-a", root)
    result = uninstall_hook(api, "repo-a")
    assert result.action == "uninstalled"
    assert not (api / ".git" / "hooks" / "post-checkout").exists()


def test_uninstall_skips_foreign_hook(workspace):
    root, api = workspace
    foreign = api / ".git" / "hooks" / "post-checkout"
    foreign.parent.mkdir(exist_ok=True)
    foreign.write_text("#!/bin/sh\nexit 0\n")
    foreign.chmod(0o755)

    result = uninstall_hook(api, "repo-a")
    assert result.action == "skipped"
    assert foreign.exists()


def test_hook_writes_state_on_branch_checkout(workspace):
    root, api = workspace
    install_hook(api, "repo-a", root)
    _git(["checkout", "-b", "feature-x"], cwd=api)

    state = read_heads_state(root)
    assert "repo-a" in state
    assert state["repo-a"]["branch"] == "feature-x"
    assert len(state["repo-a"]["sha"]) == 40
    assert state["repo-a"]["ts"].endswith("Z")


def test_hook_skips_file_checkout(workspace):
    root, api = workspace
    install_hook(api, "repo-a", root)
    # File checkout (is_branch_checkout=0); state file should NOT be created.
    (api / "README").write_text("modified\n")
    _git(["checkout", "--", "README"], cwd=api)

    state = read_heads_state(root)
    assert state == {}


def test_hook_chains_to_user_hook_after_recording(workspace):
    root, api = workspace
    user_marker = api / ".git" / "hooks" / "USER_HOOK_RAN"
    user_hook = api / ".git" / "hooks" / "post-checkout"
    user_hook.parent.mkdir(exist_ok=True)
    user_hook.write_text(f"#!/bin/sh\ntouch {user_marker}\n")
    user_hook.chmod(0o755)

    install_hook(api, "repo-a", root)
    _git(["checkout", "-b", "feature-y"], cwd=api)

    assert user_marker.exists(), "chained user hook did not run"
    state = read_heads_state(root)
    assert state["repo-a"]["branch"] == "feature-y"


def test_hook_writes_per_repo_entries(workspace):
    root, api = workspace
    ui = root / "repo-b"
    ui.mkdir()
    _git(["init", "-b", "main"], cwd=ui)
    (ui / "x").write_text("x\n")
    _git(["add", "."], cwd=ui)
    _git(["commit", "-m", "init"], cwd=ui)

    install_hook(api, "repo-a", root)
    install_hook(ui, "repo-b", root)
    _git(["checkout", "-b", "feature-api"], cwd=api)
    _git(["checkout", "-b", "feature-ui"], cwd=ui)

    state = read_heads_state(root)
    assert state["repo-a"]["branch"] == "feature-api"
    assert state["repo-b"]["branch"] == "feature-ui"


def test_hook_status(workspace):
    root, api = workspace
    assert hook_status(api)["installed"] is False
    install_hook(api, "repo-a", root)
    status = hook_status(api)
    assert status["installed"] is True
    assert status["chained_present"] is False


def test_resolve_hooks_dir_respects_core_hooks_path(workspace):
    """Husky and similar tools set core.hooksPath; install must follow it
    or git will silently never run our hook."""
    root, api = workspace
    custom_dir = api / ".husky" / "_"
    _git(["config", "core.hooksPath", str(custom_dir.relative_to(api))], cwd=api)

    resolved = resolve_hooks_dir(api).resolve()
    assert resolved == custom_dir.resolve()


def test_install_uses_core_hooks_path_when_set(workspace):
    """End-to-end: with core.hooksPath set, install lands in custom dir
    AND the hook fires on real checkouts."""
    root, api = workspace
    custom_dir = api / ".husky" / "_"
    _git(["config", "core.hooksPath", str(custom_dir.relative_to(api))], cwd=api)

    install_hook(api, "repo-a", root)
    assert (custom_dir / "post-checkout").exists()
    assert not (api / ".git" / "hooks" / "post-checkout").exists(), (
        "hook must not land in default location when core.hooksPath is set"
    )

    _git(["checkout", "-b", "from-husky-dir"], cwd=api)
    state = read_heads_state(root)
    assert state["repo-a"]["branch"] == "from-husky-dir"


def test_resolve_hooks_dir_for_worktree_points_at_main(workspace):
    """Worktrees share hooks with the main repo via commondir; resolver
    should follow that chain so installs land in the shared hooks dir."""
    root, api = workspace
    wt = root / "api-wt"
    _git(["worktree", "add", "-b", "wt-branch", str(wt)], cwd=api)

    main_hooks = (api / ".git" / "hooks").resolve()
    assert resolve_hooks_dir(wt).resolve() == main_hooks


def test_hook_installed_in_main_fires_from_worktree(workspace):
    """The shared hook fires on checkouts in any worktree, recording the
    worktree's branch."""
    root, api = workspace
    install_hook(api, "repo-a", root)

    wt = root / "api-wt"
    _git(["worktree", "add", "-b", "wt-branch", str(wt)], cwd=api)
    _git(["checkout", "-b", "another-branch"], cwd=wt)

    state = read_heads_state(root)
    assert state["repo-a"]["branch"] == "another-branch"


def test_read_heads_state_missing_file(tmp_path):
    assert read_heads_state(tmp_path) == {}
