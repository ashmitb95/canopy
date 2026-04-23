"""
Tests for canopy config, canopy done, and worktree limit enforcement.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from canopy.workspace.config import (
    get_config_value,
    set_config_value,
    get_all_config,
    load_config,
    ConfigError,
    ConfigNotFoundError,
    WORKSPACE_SETTINGS,
)


# ── Helpers ─────────────────────────────────────────────────────────────

def _git(args, cwd):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@test.com",
    }
    result = subprocess.run(
        ["git"] + args, capture_output=True, text=True, cwd=cwd, env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


# ── Config get/set ──────────────────────────────────────────────────────

class TestConfigGetSet:
    def test_get_config_name(self, canopy_toml):
        """Read the workspace name from canopy.toml."""
        val = get_config_value(canopy_toml, "name")
        assert val == "test-workspace"

    def test_get_config_unset(self, canopy_toml):
        """Read a setting that hasn't been set."""
        val = get_config_value(canopy_toml, "max_worktrees")
        assert val is None

    def test_set_config_max_worktrees(self, canopy_toml):
        """Set max_worktrees and read it back."""
        set_config_value(canopy_toml, "max_worktrees", "5")
        val = get_config_value(canopy_toml, "max_worktrees")
        assert val == 5

    def test_set_config_updates_existing(self, canopy_toml):
        """Setting a value twice updates it."""
        set_config_value(canopy_toml, "max_worktrees", "3")
        set_config_value(canopy_toml, "max_worktrees", "7")
        val = get_config_value(canopy_toml, "max_worktrees")
        assert val == 7

    def test_set_config_returns_coerced(self, canopy_toml):
        """set_config_value returns the coerced value."""
        result = set_config_value(canopy_toml, "max_worktrees", "10")
        assert result == 10
        assert isinstance(result, int)

    def test_get_all_config(self, canopy_toml):
        """get_all_config returns all workspace settings."""
        set_config_value(canopy_toml, "max_worktrees", "4")
        settings = get_all_config(canopy_toml)
        assert settings["name"] == "test-workspace"
        assert settings["max_worktrees"] == 4

    def test_unknown_key_raises(self, canopy_toml):
        """Unknown settings raise ConfigError."""
        with pytest.raises(ConfigError, match="Unknown setting"):
            get_config_value(canopy_toml, "nonexistent_key")

    def test_invalid_int_value(self, canopy_toml):
        """Non-integer value for int setting raises."""
        with pytest.raises(ConfigError, match="Invalid value"):
            set_config_value(canopy_toml, "max_worktrees", "not-a-number")

    def test_load_config_reads_max_worktrees(self, canopy_toml):
        """load_config populates max_worktrees on WorkspaceConfig."""
        set_config_value(canopy_toml, "max_worktrees", "3")
        config = load_config(canopy_toml)
        assert config.max_worktrees == 3

    def test_load_config_default_max_worktrees(self, canopy_toml):
        """max_worktrees defaults to 0 (unlimited)."""
        config = load_config(canopy_toml)
        assert config.max_worktrees == 0


# ── Worktree limit enforcement ──────────────────────────────────────────

class TestWorktreeLimit:
    def test_create_under_limit(self, workspace_with_feature, canopy_toml):
        """Creating a worktree under the limit succeeds."""
        from canopy.workspace.workspace import Workspace
        from canopy.features.coordinator import FeatureCoordinator

        set_config_value(canopy_toml, "max_worktrees", "5")
        config = load_config(canopy_toml)
        ws = Workspace(config)
        coordinator = FeatureCoordinator(ws)

        lane = coordinator.create("under-limit", use_worktrees=True)
        assert lane.name == "under-limit"

        # Cleanup
        coordinator.done("under-limit", force=True)

    def test_create_at_limit_fails(self, workspace_with_feature, canopy_toml):
        """Creating a worktree at the limit raises WorktreeLimitError."""
        from canopy.workspace.workspace import Workspace
        from canopy.features.coordinator import FeatureCoordinator, WorktreeLimitError

        config = load_config(canopy_toml)
        ws = Workspace(config)
        coordinator = FeatureCoordinator(ws)

        # Create one worktree
        coordinator.create("first", use_worktrees=True)

        # Set limit to 1
        set_config_value(canopy_toml, "max_worktrees", "1")
        # Reload config
        config = load_config(canopy_toml)
        ws = Workspace(config)
        coordinator = FeatureCoordinator(ws)

        with pytest.raises(WorktreeLimitError) as exc_info:
            coordinator.create("second", use_worktrees=True)

        assert exc_info.value.current == 1
        assert exc_info.value.limit == 1

        # Cleanup
        coordinator.done("first", force=True)

    def test_limit_zero_means_unlimited(self, workspace_with_feature, canopy_toml):
        """max_worktrees=0 means no limit."""
        from canopy.workspace.workspace import Workspace
        from canopy.features.coordinator import FeatureCoordinator

        config = load_config(canopy_toml)
        ws = Workspace(config)
        coordinator = FeatureCoordinator(ws)

        # Should succeed with default limit of 0
        lane = coordinator.create("unlimited-test", use_worktrees=True)
        assert lane.name == "unlimited-test"

        coordinator.done("unlimited-test", force=True)

    def test_stale_candidates_returned(self, workspace_with_feature, canopy_toml):
        """WorktreeLimitError includes stale worktree candidates."""
        from canopy.workspace.workspace import Workspace
        from canopy.features.coordinator import FeatureCoordinator, WorktreeLimitError

        config = load_config(canopy_toml)
        ws = Workspace(config)
        coordinator = FeatureCoordinator(ws)

        # Create a worktree and mark it done (but don't remove it — simulate stale)
        coordinator.create("stale-one", use_worktrees=True)

        # Set limit to 1
        set_config_value(canopy_toml, "max_worktrees", "1")
        config = load_config(canopy_toml)
        ws = Workspace(config)
        coordinator = FeatureCoordinator(ws)

        with pytest.raises(WorktreeLimitError) as exc_info:
            coordinator.create("blocked", use_worktrees=True)

        # stale-one should appear as a candidate (clean, no changes ahead)
        stale_names = [s["name"] for s in exc_info.value.stale]
        assert "stale-one" in stale_names

        coordinator.done("stale-one", force=True)


# ── canopy done ─────────────────────────────────────────────────────────

class TestFeatureDone:
    def test_done_removes_worktrees(self, workspace_with_feature, canopy_toml):
        """canopy done removes worktree directories."""
        from canopy.workspace.workspace import Workspace
        from canopy.features.coordinator import FeatureCoordinator

        config = load_config(canopy_toml)
        ws = Workspace(config)
        coordinator = FeatureCoordinator(ws)

        coordinator.create("to-clean", use_worktrees=True)
        wt_dir = canopy_toml / ".canopy" / "worktrees" / "to-clean"
        assert wt_dir.exists()

        result = coordinator.done("to-clean", force=True)

        assert not wt_dir.exists()
        assert "api" in result["worktrees_removed"]
        assert "ui" in result["worktrees_removed"]

    def test_done_deletes_branches(self, workspace_with_feature, canopy_toml):
        """canopy done deletes local branches."""
        from canopy.workspace.workspace import Workspace
        from canopy.features.coordinator import FeatureCoordinator
        from canopy.git import repo as git

        config = load_config(canopy_toml)
        ws = Workspace(config)
        coordinator = FeatureCoordinator(ws)

        coordinator.create("to-delete", use_worktrees=True)
        result = coordinator.done("to-delete", force=True)

        assert result["branches_deleted"]["api"] == "ok"
        assert result["branches_deleted"]["ui"] == "ok"

        # Verify branches are actually gone
        assert not git.branch_exists(canopy_toml / "api", "to-delete")
        assert not git.branch_exists(canopy_toml / "ui", "to-delete")

    def test_done_archives_feature(self, workspace_with_feature, canopy_toml):
        """canopy done marks feature as 'done' in features.json."""
        from canopy.workspace.workspace import Workspace
        from canopy.features.coordinator import FeatureCoordinator

        config = load_config(canopy_toml)
        ws = Workspace(config)
        coordinator = FeatureCoordinator(ws)

        coordinator.create("to-archive", use_worktrees=True)
        result = coordinator.done("to-archive", force=True)

        assert result["archived"] is True

        # Verify in features.json
        features = coordinator._load_features()
        assert features["to-archive"]["status"] == "done"
        assert "worktree_paths" not in features["to-archive"]

    def test_done_dirty_without_force_fails(self, workspace_with_feature, canopy_toml):
        """canopy done fails if worktrees are dirty and --force not set."""
        from canopy.workspace.workspace import Workspace
        from canopy.features.coordinator import FeatureCoordinator

        config = load_config(canopy_toml)
        ws = Workspace(config)
        coordinator = FeatureCoordinator(ws)

        coordinator.create("dirty-test", use_worktrees=True)

        # Make a worktree dirty
        wt_path = canopy_toml / ".canopy" / "worktrees" / "dirty-test" / "api"
        (wt_path / "dirty_file.py").write_text("# dirty\n")

        with pytest.raises(ValueError, match="uncommitted changes"):
            coordinator.done("dirty-test")

        # Cleanup
        coordinator.done("dirty-test", force=True)

    def test_done_nonexistent_feature(self, workspace_with_feature, canopy_toml):
        """canopy done raises for unknown features."""
        from canopy.workspace.workspace import Workspace
        from canopy.features.coordinator import FeatureCoordinator

        config = load_config(canopy_toml)
        ws = Workspace(config)
        coordinator = FeatureCoordinator(ws)

        with pytest.raises(ValueError, match="not found"):
            coordinator.done("nonexistent-feature")

    def test_done_frees_worktree_slot(self, workspace_with_feature, canopy_toml):
        """After done, a new worktree can be created within the limit."""
        from canopy.workspace.workspace import Workspace
        from canopy.features.coordinator import FeatureCoordinator

        set_config_value(canopy_toml, "max_worktrees", "1")
        config = load_config(canopy_toml)
        ws = Workspace(config)
        coordinator = FeatureCoordinator(ws)

        coordinator.create("slot-1", use_worktrees=True)
        coordinator.done("slot-1", force=True)

        # Reload to get fresh count
        config = load_config(canopy_toml)
        ws = Workspace(config)
        coordinator = FeatureCoordinator(ws)

        # Should succeed — slot freed
        lane = coordinator.create("slot-2", use_worktrees=True)
        assert lane.name == "slot-2"

        coordinator.done("slot-2", force=True)
