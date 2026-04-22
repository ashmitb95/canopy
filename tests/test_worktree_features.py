"""
Tests for worktree-smart feature lanes, IDE launcher, and worktree creation.
"""
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from canopy.git import repo as git
from canopy.features.coordinator import FeatureCoordinator
from canopy.workspace.config import WorkspaceConfig, RepoConfig
from canopy.workspace.workspace import Workspace


# ── Helpers ──────────────────────────────────────────────────────────────

def _git(args, cwd):
    result = subprocess.run(
        ["git"] + args,
        capture_output=True, text=True, cwd=cwd,
        env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com",
             "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"},
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def _make_workspace(workspace_dir) -> Workspace:
    config = WorkspaceConfig(
        name="test",
        repos=[
            RepoConfig(name="api", path="./api", role="backend", lang="python"),
            RepoConfig(name="ui", path="./ui", role="frontend", lang="typescript"),
        ],
        root=workspace_dir,
    )
    return Workspace(config)


# ── Feature create with --worktree ──────────────────────────────────────

class TestFeatureCreateWorktree:
    def test_create_with_worktrees(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        coordinator = FeatureCoordinator(ws)

        lane = coordinator.create("payment-flow", use_worktrees=True)

        assert lane.name == "payment-flow"
        assert "api" in lane.repos
        assert "ui" in lane.repos

        # Worktree directories should exist
        wt_base = workspace_dir / ".canopy" / "worktrees" / "payment-flow"
        assert (wt_base / "api").exists()
        assert (wt_base / "ui").exists()

        # They should be on the right branch
        assert git.current_branch(wt_base / "api") == "payment-flow"
        assert git.current_branch(wt_base / "ui") == "payment-flow"

        # Main repos should still be on main
        assert git.current_branch(workspace_dir / "api") == "main"
        assert git.current_branch(workspace_dir / "ui") == "main"

        # Features.json should record worktree info
        features_path = workspace_dir / ".canopy" / "features.json"
        features = json.loads(features_path.read_text())
        assert features["payment-flow"]["use_worktrees"] is True
        assert "api" in features["payment-flow"]["worktree_paths"]

    def test_create_with_custom_worktree_base(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        coordinator = FeatureCoordinator(ws)
        custom_base = workspace_dir / "my-worktrees"

        lane = coordinator.create(
            "custom-wt", use_worktrees=True, worktree_base=custom_base
        )

        assert (custom_base / "custom-wt" / "api").exists()
        assert (custom_base / "custom-wt" / "ui").exists()

    def test_create_worktree_subset(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        coordinator = FeatureCoordinator(ws)

        lane = coordinator.create(
            "api-only-wt", repos=["api"], use_worktrees=True
        )

        wt_base = workspace_dir / ".canopy" / "worktrees" / "api-only-wt"
        assert (wt_base / "api").exists()
        assert not (wt_base / "ui").exists()


# ── Worktree-smart switch ───────────────────────────────────────────────

class TestWorktreeSmartSwitch:
    def test_switch_detects_worktree(self, workspace_dir):
        """Switch should report worktree path instead of failing."""
        ws = _make_workspace(workspace_dir)
        coordinator = FeatureCoordinator(ws)

        # Create feature with worktrees
        coordinator.create("wt-switch-test", use_worktrees=True)

        # Try to switch — branches are in worktrees, can't checkout
        results = coordinator.switch("wt-switch-test")

        for repo_name, result in results.items():
            assert isinstance(result, str)
            assert "already in worktree:" in result

    def test_switch_mixed_worktree_and_branch(self, workspace_dir):
        """Some repos in worktrees, some not — should handle both."""
        ws = _make_workspace(workspace_dir)
        coordinator = FeatureCoordinator(ws)

        # Create feature with worktree for api, regular branch for ui
        coordinator.create("mixed-test", use_worktrees=True)

        # Now switch — api and ui are both in worktrees
        # Manually remove ui worktree and recreate as just a branch
        wt_base = workspace_dir / ".canopy" / "worktrees" / "mixed-test"
        git.worktree_remove(workspace_dir / "ui", wt_base / "ui")

        # Now api has a worktree, ui has just a branch
        results = coordinator.switch("mixed-test")
        assert "already in worktree:" in results["api"]
        assert results["ui"] is True


# ── Worktree-smart enrich / status ──────────────────────────────────────

class TestWorktreeSmartStatus:
    def test_status_includes_worktree_path(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        coordinator = FeatureCoordinator(ws)

        coordinator.create("status-wt-test", use_worktrees=True)
        lane = coordinator.status("status-wt-test")

        for repo_name, state in lane.repo_states.items():
            assert "worktree_path" in state
            assert "status-wt-test" in state["worktree_path"]


# ── resolve_paths ────────────────────────────────────────────────────────

class TestResolvePaths:
    def test_resolve_worktree_paths(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        coordinator = FeatureCoordinator(ws)

        coordinator.create("resolve-wt", use_worktrees=True)
        paths = coordinator.resolve_paths("resolve-wt")

        assert "api" in paths
        assert "ui" in paths
        # Should point to worktree directories
        for repo, path in paths.items():
            assert "resolve-wt" in path
            assert Path(path).exists()

    def test_resolve_branch_paths(self, workspace_with_feature):
        """When branch is checked out (no worktree), return repo path."""
        ws = _make_workspace(workspace_with_feature)
        coordinator = FeatureCoordinator(ws)

        paths = coordinator.resolve_paths("auth-flow")

        assert "api" in paths
        assert "ui" in paths
        # Should point to the repo directories (branch is current)
        assert paths["api"] == str((workspace_with_feature / "api").resolve())

    def test_resolve_dot_workspace(self, workspace_dir):
        """resolve_paths for '.' isn't supported — that's the IDE command."""
        # Just verify resolve_paths works for a feature
        ws = _make_workspace(workspace_dir)
        coordinator = FeatureCoordinator(ws)
        coordinator.create("resolve-test")
        paths = coordinator.resolve_paths("resolve-test")
        assert len(paths) == 2


# ── IDE launcher (.code-workspace generation) ────────────────────────────

class TestWorkspaceFileGeneration:
    def test_generates_workspace_file(self, workspace_dir):
        from canopy.cli.main import _generate_workspace_file

        paths = [
            str(workspace_dir / "api"),
            str(workspace_dir / "ui"),
        ]
        ws_file = _generate_workspace_file(workspace_dir, "test-feature", paths)

        assert Path(ws_file).exists()
        data = json.loads(Path(ws_file).read_text())
        assert len(data["folders"]) == 2
        assert data["settings"]["canopy.feature"] == "test-feature"
        assert ws_file.endswith(".code-workspace")


# ── git.repo: worktree_add / worktree_for_branch ────────────────────────

class TestWorktreeAddAndQuery:
    def test_worktree_add_creates_directory(self, workspace_dir):
        api = workspace_dir / "api"
        wt_path = workspace_dir / "api-new-wt"

        git.worktree_add(api, wt_path, "new-wt-branch", create_branch=True)

        assert wt_path.exists()
        assert git.is_worktree(wt_path)
        assert git.current_branch(wt_path) == "new-wt-branch"

        # Cleanup
        git.worktree_remove(api, wt_path)

    def test_worktree_for_branch_found(self, workspace_dir):
        api = workspace_dir / "api"
        wt_path = workspace_dir / "api-find-wt"

        git.worktree_add(api, wt_path, "find-me", create_branch=True)

        result = git.worktree_for_branch(api, "find-me")
        assert result is not None
        assert "api-find-wt" in result

        # Cleanup
        git.worktree_remove(api, wt_path)

    def test_worktree_for_branch_not_found(self, workspace_dir):
        api = workspace_dir / "api"
        result = git.worktree_for_branch(api, "nonexistent-branch")
        assert result is None

    def test_worktree_add_existing_branch(self, workspace_dir):
        api = workspace_dir / "api"
        git.create_branch(api, "pre-existing")
        wt_path = workspace_dir / "api-pre-existing"

        git.worktree_add(api, wt_path, "pre-existing", create_branch=False)

        assert wt_path.exists()
        assert git.current_branch(wt_path) == "pre-existing"

        # Cleanup
        git.worktree_remove(api, wt_path)
