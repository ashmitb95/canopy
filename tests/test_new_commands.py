"""
Tests for new CLI commands: stash, checkout, commit, log, branch, worktree.

Tests both the git.repo functions and git.multi orchestration layer.
"""
import os
import subprocess
from pathlib import Path

import pytest

from canopy.git import repo as git
from canopy.git import multi
from canopy.workspace.config import WorkspaceConfig, RepoConfig, load_config
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
    """Build a Workspace object from a workspace_dir fixture."""
    config = WorkspaceConfig(
        name="test",
        repos=[
            RepoConfig(name="repo-a", path="./repo-a", role="backend", lang="python"),
            RepoConfig(name="repo-b", path="./repo-b", role="frontend", lang="typescript"),
        ],
        root=workspace_dir,
    )
    return Workspace(config)


# ── git.repo: stash ──────────────────────────────────────────────────────

class TestStashRepo:
    def test_stash_save_and_list(self, workspace_dir):
        api = workspace_dir / "repo-a"
        (api / "src" / "new_file.py").write_text("hello\n")
        _git(["add", "."], cwd=api)

        assert git.stash_save(api, "test stash") is True
        stashes = git.stash_list(api)
        assert len(stashes) >= 1
        assert stashes[0]["index"] == 0
        assert "test stash" in stashes[0]["message"]

    def test_stash_save_clean(self, workspace_dir):
        api = workspace_dir / "repo-a"
        assert git.stash_save(api) is False

    def test_stash_pop(self, workspace_dir):
        api = workspace_dir / "repo-a"
        (api / "src" / "stashed.py").write_text("stashed content\n")
        _git(["add", "."], cwd=api)
        git.stash_save(api, "to pop")

        assert not (api / "src" / "stashed.py").exists()
        git.stash_pop(api, 0)
        assert (api / "src" / "stashed.py").exists()

    def test_stash_drop(self, workspace_dir):
        api = workspace_dir / "repo-a"
        (api / "src" / "tmp.py").write_text("tmp\n")
        _git(["add", "."], cwd=api)
        git.stash_save(api, "to drop")
        assert len(git.stash_list(api)) == 1

        git.stash_drop(api, 0)
        assert len(git.stash_list(api)) == 0


# ── git.repo: branch management ─────────────────────────────────────────

class TestBranchRepo:
    def test_delete_branch(self, workspace_dir):
        api = workspace_dir / "repo-a"
        git.create_branch(api, "to-delete")
        assert git.branch_exists(api, "to-delete")
        git.delete_branch(api, "to-delete")
        assert not git.branch_exists(api, "to-delete")

    def test_delete_branch_force(self, workspace_dir):
        api = workspace_dir / "repo-a"
        git.create_branch(api, "unmerged")
        _git(["checkout", "unmerged"], cwd=api)
        (api / "unmerged.py").write_text("x\n")
        _git(["add", "."], cwd=api)
        _git(["commit", "-m", "unmerged commit"], cwd=api)
        _git(["checkout", "main"], cwd=api)
        # Normal delete should fail for unmerged branch
        with pytest.raises(git.GitError):
            git.delete_branch(api, "unmerged", force=False)
        # Force delete should work
        git.delete_branch(api, "unmerged", force=True)
        assert not git.branch_exists(api, "unmerged")

    def test_rename_branch(self, workspace_dir):
        api = workspace_dir / "repo-a"
        git.create_branch(api, "old-name")
        git.rename_branch(api, "old-name", "new-name")
        assert not git.branch_exists(api, "old-name")
        assert git.branch_exists(api, "new-name")

    def test_all_branches(self, workspace_dir):
        api = workspace_dir / "repo-a"
        git.create_branch(api, "feature-x")
        branches = git.all_branches(api)
        names = [b["name"] for b in branches]
        assert "main" in names
        assert "feature-x" in names
        current = [b for b in branches if b["is_current"]]
        assert len(current) == 1
        assert current[0]["name"] == "main"


# ── git.repo: log ────────────────────────────────────────────────────────

class TestLogRepo:
    def test_log_structured(self, workspace_dir):
        api = workspace_dir / "repo-a"
        entries = git.log_structured(api, max_count=5)
        assert len(entries) >= 1
        entry = entries[0]
        assert "sha" in entry
        assert "short_sha" in entry
        assert "author" in entry
        assert "date" in entry
        assert "subject" in entry
        assert entry["subject"] == "Initial commit"


# ── git.repo: worktree ──────────────────────────────────────────────────

class TestWorktreeRepo:
    def test_is_worktree_false(self, workspace_dir):
        api = workspace_dir / "repo-a"
        assert git.is_worktree(api) is False

    def test_worktree_main_path_none(self, workspace_dir):
        api = workspace_dir / "repo-a"
        assert git.worktree_main_path(api) is None

    def test_worktree_list_single(self, workspace_dir):
        api = workspace_dir / "repo-a"
        worktrees = git.worktree_list(api)
        assert len(worktrees) == 1
        assert worktrees[0]["branch"] == "main"

    def test_worktree_linked(self, workspace_dir):
        """Create a linked worktree and verify detection."""
        api = workspace_dir / "repo-a"
        wt_path = workspace_dir / "api-feature"
        _git(["worktree", "add", str(wt_path), "-b", "wt-branch"], cwd=api)

        # The linked worktree should be detected
        assert git.is_worktree(wt_path) is True
        main = git.worktree_main_path(wt_path)
        assert main is not None
        assert main.resolve() == api.resolve()

        # Main repo should list both worktrees
        worktrees = git.worktree_list(api)
        assert len(worktrees) == 2
        wt_paths = {wt["path"] for wt in worktrees}
        assert str(api) in wt_paths or str(api.resolve()) in wt_paths

        # Cleanup
        _git(["worktree", "remove", str(wt_path)], cwd=api)


# ── git.multi: stash ────────────────────────────────────────────────────

class TestStashMulti:
    def test_stash_save_all(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        api = workspace_dir / "repo-a"
        (api / "dirty.py").write_text("dirty\n")
        _git(["add", "."], cwd=api)

        results = multi.stash_save_all(ws, message="bulk stash")
        assert results["repo-a"] == "stashed"
        assert results["repo-b"] == "clean"

    def test_stash_list_all(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        api = workspace_dir / "repo-a"
        (api / "dirty.py").write_text("dirty\n")
        _git(["add", "."], cwd=api)
        multi.stash_save_all(ws, message="test")

        results = multi.stash_list_all(ws)
        assert "repo-a" in results
        assert len(results["repo-a"]) == 1
        assert "repo-b" not in results  # clean, no stash

    def test_stash_pop_all(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        api = workspace_dir / "repo-a"
        (api / "dirty.py").write_text("dirty\n")
        _git(["add", "."], cwd=api)
        multi.stash_save_all(ws, message="to pop")

        results = multi.stash_pop_all(ws)
        assert results["repo-a"] == "ok"
        assert results["repo-b"] == "no stash"

    def test_stash_drop_all(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        api = workspace_dir / "repo-a"
        (api / "dirty.py").write_text("dirty\n")
        _git(["add", "."], cwd=api)
        multi.stash_save_all(ws, message="to drop")

        results = multi.stash_drop_all(ws)
        assert results["repo-a"] == "ok"
        assert results["repo-b"] == "no stash"

    def test_stash_filtered_repos(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        api = workspace_dir / "repo-a"
        ui = workspace_dir / "repo-b"
        (api / "dirty.py").write_text("dirty\n")
        _git(["add", "."], cwd=api)
        (ui / "dirty.ts").write_text("dirty\n")
        _git(["add", "."], cwd=ui)

        results = multi.stash_save_all(ws, repos=["repo-a"])
        assert "repo-a" in results
        assert "repo-b" not in results


# ── git.multi: commit ───────────────────────────────────────────────────

class TestCommitMulti:
    def test_commit_all(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        api = workspace_dir / "repo-a"
        ui = workspace_dir / "repo-b"

        (api / "new.py").write_text("new\n")
        _git(["add", "."], cwd=api)

        results = multi.commit_all(ws, "cross-repo commit")
        assert len(results["repo-a"]) == 12  # short sha
        assert results["repo-b"] == "nothing to commit"

    def test_commit_filtered(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        api = workspace_dir / "repo-a"
        (api / "new.py").write_text("new\n")
        _git(["add", "."], cwd=api)

        results = multi.commit_all(ws, "only api", repos=["repo-a"])
        assert "repo-a" in results
        assert "repo-b" not in results


# ── git.multi: log ──────────────────────────────────────────────────────

class TestLogMulti:
    def test_log_all(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        entries = multi.log_all(ws, max_count=10)
        assert len(entries) >= 2  # at least one from each repo
        repos = {e["repo"] for e in entries}
        assert "repo-a" in repos
        assert "repo-b" in repos

    def test_log_all_sorted_by_date(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        entries = multi.log_all(ws, max_count=10)
        # Verify descending date order
        for i in range(len(entries) - 1):
            assert entries[i]["date"] >= entries[i + 1]["date"]


# ── git.multi: branch ──────────────────────────────────────────────────

class TestBranchMulti:
    def test_branches_all(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        results = multi.branches_all(ws)
        assert "repo-a" in results
        assert "repo-b" in results
        api_names = [b["name"] for b in results["repo-a"]]
        assert "main" in api_names

    def test_delete_branch_all(self, workspace_with_feature):
        ws = _make_workspace(workspace_with_feature)
        # First switch back to main
        multi.checkout_all(ws, "main")
        # force=True because auth-flow has unmerged commits
        results = multi.delete_branch_all(ws, "auth-flow", force=True)
        assert results["repo-a"] == "ok"
        assert results["repo-b"] == "ok"

    def test_delete_branch_not_found(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        results = multi.delete_branch_all(ws, "nonexistent")
        assert results["repo-a"] == "not found"
        assert results["repo-b"] == "not found"

    def test_rename_branch_all(self, workspace_with_feature):
        ws = _make_workspace(workspace_with_feature)
        # Switch to main first
        multi.checkout_all(ws, "main")
        results = multi.rename_branch_all(ws, "auth-flow", "auth-v2")
        assert results["repo-a"] == "ok"
        assert results["repo-b"] == "ok"
        assert git.branch_exists(workspace_with_feature / "repo-a", "auth-v2")
        assert not git.branch_exists(workspace_with_feature / "repo-a", "auth-flow")

    def test_rename_branch_not_found(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        results = multi.rename_branch_all(ws, "ghost", "new-ghost")
        assert results["repo-a"] == "not found"


# ── discovery: worktree detection ───────────────────────────────────────

class TestDiscoveryWorktree:
    def test_discover_detects_worktree(self, workspace_dir):
        """Worktrees should be discovered with is_worktree=True."""
        from canopy.workspace.discovery import discover_repos

        api = workspace_dir / "repo-a"
        wt_path = workspace_dir / "api-wt"
        _git(["worktree", "add", str(wt_path), "-b", "wt-test"], cwd=api)

        repos = discover_repos(workspace_dir)
        names = {r.name: r for r in repos}
        assert "repo-a" in names
        assert "api-wt" in names
        assert names["repo-a"].is_worktree is False
        assert names["api-wt"].is_worktree is True
        assert names["api-wt"].worktree_main is not None

        _git(["worktree", "remove", str(wt_path)], cwd=api)
