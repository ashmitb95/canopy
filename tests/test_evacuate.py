"""Tests for evacuate.py — slot-keyed evacuate_repo and fastpath_swap_repo."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from canopy.actions import evacuate, slots
from canopy.actions.errors import BlockerError
from canopy.workspace.config import load_config
from canopy.workspace.workspace import Workspace


def _checkout(repo_path: Path, branch: str) -> None:
    subprocess.run(["git", "checkout", branch], cwd=repo_path, check=True,
                   capture_output=True)


class TestEvacuateRepo:
    """evacuate_repo: stash → checkout target → worktree add → stash pop."""

    def test_evacuate_to_named_slot(self, workspace_with_feature, canopy_toml_for_workspace):
        ws = Workspace(load_config(canopy_toml_for_workspace))
        api = ws.get_repo("repo-a")

        # workspace_with_feature leaves repo-a on auth-flow — exactly what we need.
        result = evacuate.evacuate_repo(
            ws,
            feature_being_evacuated="auth-flow",
            repo_name="repo-a",
            repo_path=api.abs_path,
            slot_id="worktree-1",
            target_branch="main",
        )

        assert result["status"] == "evacuated"
        assert result["slot_id"] == "worktree-1"
        assert result["worktree_path"].endswith("worktree-1/repo-a")
        # Slot dir exists and is a git worktree
        slot_path = ws.config.root / ".canopy/worktrees/worktree-1/repo-a"
        assert (slot_path / ".git").exists()
        # main repo-a is now on main
        from canopy.git import repo as git
        assert git.current_branch(api.abs_path) == "main"

    def test_evacuate_raises_when_slot_path_occupied(
        self, workspace_with_feature, canopy_toml_for_workspace
    ):
        ws = Workspace(load_config(canopy_toml_for_workspace))
        api = ws.get_repo("repo-a")

        # Create the slot path manually to simulate collision.
        slot_path = ws.config.root / ".canopy/worktrees/worktree-1/repo-a"
        slot_path.mkdir(parents=True, exist_ok=True)

        with pytest.raises(BlockerError) as exc_info:
            evacuate.evacuate_repo(
                ws,
                feature_being_evacuated="auth-flow",
                repo_name="repo-a",
                repo_path=api.abs_path,
                slot_id="worktree-1",
                target_branch="main",
            )
        assert exc_info.value.code == "slot_worktree_path_occupied"

    def test_evacuate_stashes_dirty_work_and_pops(
        self, workspace_with_feature, canopy_toml_for_workspace
    ):
        ws = Workspace(load_config(canopy_toml_for_workspace))
        api = ws.get_repo("repo-a")

        # Leave a dirty file in repo-a (on auth-flow).
        dirty_file = api.abs_path / "src" / "dirty.py"
        dirty_file.write_text("# dirty\n")

        result = evacuate.evacuate_repo(
            ws,
            feature_being_evacuated="auth-flow",
            repo_name="repo-a",
            repo_path=api.abs_path,
            slot_id="worktree-1",
            target_branch="main",
        )

        assert result["stashed"] is True
        assert result["popped"] is True
        # Dirty file should appear in the worktree after pop.
        wt_path = Path(result["worktree_path"])
        assert (wt_path / "src" / "dirty.py").exists()
        # Main tree should be clean (dirty file was stashed and moved into wt).
        from canopy.git import repo as git
        assert not git.is_dirty(api.abs_path)


class TestFastpathSwapRepo:
    """fastpath_swap_repo: 5-op active-rotation swap."""

    def _setup_slot(
        self,
        ws: Workspace,
        slot_id: str,
        feature: str,
        repo_name: str,
        repo_path: Path,
        target_branch: str,
    ) -> Path:
        """Evacuate feature into slot_id so fastpath_swap can exercise the swap."""
        evacuate.evacuate_repo(
            ws,
            feature_being_evacuated=feature,
            repo_name=repo_name,
            repo_path=repo_path,
            slot_id=slot_id,
            target_branch=target_branch,
        )
        return slots.slot_worktree_path(ws, slot_id, repo_name)

    def test_fastpath_swap_basic(self, workspace_with_feature, canopy_toml_for_workspace):
        """Y (auth-flow) is warm in slot, X (feat-b) canonical → swap."""
        ws = Workspace(load_config(canopy_toml_for_workspace))
        api = ws.get_repo("repo-a")
        api_path = api.abs_path

        # Create feat-b branch
        _checkout(api_path, "main")
        subprocess.run(["git", "checkout", "-b", "feat-b"], cwd=api_path, check=True,
                       capture_output=True)

        # Evacuate auth-flow into worktree-1 (main switches to main/feat-b below)
        # First get auth-flow into slot: checkout auth-flow, evacuate to slot.
        _checkout(api_path, "feat-b")   # free up main tree from feat-b
        # For the test: feat-b is in main; auth-flow is in the slot.
        # Evacuate auth-flow to slot from feat-b → need auth-flow checked out.
        _checkout(api_path, "auth-flow")
        slot_path = self._setup_slot(
            ws, "worktree-1", "auth-flow", "repo-a", api_path, "feat-b"
        )

        # Now: main has feat-b, slot has auth-flow.
        # Swap: bring auth-flow to main, push feat-b into slot.
        result = evacuate.fastpath_swap_repo(
            ws,
            x_feature="feat-b",
            y_feature="auth-flow",
            repo_name="repo-a",
            repo_path=api_path,
            slot_id="worktree-1",
            default_branch="main",
        )

        assert result["status"] == "fastpath_swapped"
        assert result["slot_id"] == "worktree-1"
        assert result["swapped_in"] == "auth-flow"
        assert result["swapped_out"] == "feat-b"
        # Main now has auth-flow
        from canopy.git import repo as git
        assert git.current_branch(api_path) == "auth-flow"
        # Slot now has feat-b
        assert git.current_branch(slot_path) == "feat-b"

    def test_fastpath_swap_raises_when_slot_missing(
        self, workspace_with_feature, canopy_toml_for_workspace
    ):
        ws = Workspace(load_config(canopy_toml_for_workspace))
        api = ws.get_repo("repo-a")

        with pytest.raises(BlockerError) as exc_info:
            evacuate.fastpath_swap_repo(
                ws,
                x_feature="feat-b",
                y_feature="auth-flow",
                repo_name="repo-a",
                repo_path=api.abs_path,
                slot_id="worktree-1",
                default_branch="main",
            )
        assert exc_info.value.code == "fastpath_slot_missing"
