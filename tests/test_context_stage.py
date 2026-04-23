"""
Tests for context detection and canopy preflight command.
"""
import os
import subprocess
from pathlib import Path

import pytest

from canopy.git import repo as git
from canopy.workspace.context import detect_context, CanopyContext
from canopy.workspace.config import WorkspaceConfig, RepoConfig
from canopy.workspace.workspace import Workspace
from canopy.features.coordinator import FeatureCoordinator


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


def _setup_feature_worktrees(workspace_dir):
    """Create a feature with worktrees and return the feature dir."""
    ws = _make_workspace(workspace_dir)
    coordinator = FeatureCoordinator(ws)
    coordinator.create("auth-flow", use_worktrees=True)
    return workspace_dir / ".canopy" / "worktrees" / "auth-flow"


# ── Context detection: feature directory ─────────────────────────────────

class TestContextFeatureDir:
    def test_detect_feature_dir(self, canopy_toml):
        feature_dir = _setup_feature_worktrees(canopy_toml)

        ctx = detect_context(cwd=feature_dir)

        assert ctx.context_type == "feature_dir"
        assert ctx.feature == "auth-flow"
        assert len(ctx.repo_paths) == 2
        assert set(ctx.repo_names) == {"api", "ui"}
        assert ctx.branch == "auth-flow"

    def test_detect_repo_worktree(self, canopy_toml):
        feature_dir = _setup_feature_worktrees(canopy_toml)
        api_wt = feature_dir / "api"

        ctx = detect_context(cwd=api_wt)

        assert ctx.context_type == "repo_worktree"
        assert ctx.feature == "auth-flow"
        assert len(ctx.repo_paths) == 1
        assert ctx.repo_names == ["api"]
        assert ctx.branch == "auth-flow"

    def test_detect_subdirectory_of_repo_worktree(self, canopy_toml):
        """Context detection should work from subdirs inside a worktree."""
        feature_dir = _setup_feature_worktrees(canopy_toml)
        api_wt = feature_dir / "api"
        subdir = api_wt / "src"
        subdir.mkdir(parents=True, exist_ok=True)

        ctx = detect_context(cwd=subdir)

        assert ctx.context_type == "repo_worktree"
        assert ctx.feature == "auth-flow"
        assert ctx.repo_names == ["api"]


# ── Context detection: normal repo ───────────────────────────────────────

class TestContextNormalRepo:
    def test_detect_normal_repo(self, canopy_toml):
        api_path = canopy_toml / "api"

        ctx = detect_context(cwd=api_path)

        assert ctx.context_type == "repo"
        assert ctx.repo_names == ["api"]
        assert ctx.workspace_root == canopy_toml

    def test_detect_repo_on_feature_branch(self, workspace_with_feature):
        """When on a non-default branch, feature should be detected."""
        # Write canopy.toml so workspace root is found
        toml_content = """\
[workspace]
name = "test-workspace"

[[repos]]
name = "api"
path = "./api"

[[repos]]
name = "ui"
path = "./ui"
"""
        (workspace_with_feature / "canopy.toml").write_text(toml_content)
        api_path = workspace_with_feature / "api"

        ctx = detect_context(cwd=api_path)

        assert ctx.context_type == "repo"
        assert ctx.feature == "auth-flow"
        assert ctx.branch == "auth-flow"


# ── Context detection: workspace root ────────────────────────────────────

class TestContextWorkspaceRoot:
    def test_detect_workspace_root(self, canopy_toml):
        ctx = detect_context(cwd=canopy_toml)

        assert ctx.context_type == "workspace_root"
        assert ctx.workspace_root == canopy_toml
        assert len(ctx.repo_paths) == 2

    def test_unknown_context(self, tmp_path):
        """Random directory should return unknown."""
        ctx = detect_context(cwd=tmp_path)
        assert ctx.context_type == "unknown"


# ── Context to_dict ─────────────────────────────────────────────────────

class TestContextDict:
    def test_to_dict(self, canopy_toml):
        feature_dir = _setup_feature_worktrees(canopy_toml)
        ctx = detect_context(cwd=feature_dir)

        d = ctx.to_dict()
        assert d["feature"] == "auth-flow"
        assert d["context_type"] == "feature_dir"
        assert len(d["repo_paths"]) == 2
        assert len(d["repo_names"]) == 2


# ── canopy preflight: from feature directory ─────────────────────────────

class TestPreflightFromFeatureDir:
    def test_preflight_stages_all_repos(self, canopy_toml):
        """Preflight from the feature dir should stage across all repo worktrees."""
        from canopy.integrations.precommit import run_precommit

        feature_dir = _setup_feature_worktrees(canopy_toml)

        # Make changes in both worktree repos
        (feature_dir / "api" / "new_api.py").write_text("api change\n")
        (feature_dir / "ui" / "new_ui.ts").write_text("ui change\n")

        # Simulate what cmd_preflight does
        ctx = detect_context(cwd=feature_dir)
        assert ctx.context_type == "feature_dir"
        assert len(ctx.repo_paths) == 2

        results = {}
        for repo_path, repo_name in zip(ctx.repo_paths, ctx.repo_names):
            status = git.status_porcelain(repo_path)
            if not status:
                results[repo_name] = {"status": "clean"}
                continue
            git._run(["add", "-A"], cwd=repo_path)
            hook_result = run_precommit(repo_path)
            results[repo_name] = {
                "status": "staged" if hook_result["passed"] else "hooks_failed",
                "hooks": hook_result,
            }

        # Both should be staged (no hooks in test repos = pass)
        assert results["api"]["status"] == "staged"
        assert results["ui"]["status"] == "staged"

        # Verify NO commits were made — preflight does not commit
        api_log = git.log_structured(feature_dir / "api", max_count=1)
        assert api_log[0]["subject"] != "new_api.py"  # no commit with our changes

        # But changes should be staged (in the index)
        staged_api = git._run(["diff", "--cached", "--name-only"], cwd=feature_dir / "api")
        assert "new_api.py" in staged_api

        staged_ui = git._run(["diff", "--cached", "--name-only"], cwd=feature_dir / "ui")
        assert "new_ui.ts" in staged_ui

    def test_preflight_single_repo_worktree(self, canopy_toml):
        """Preflight from inside a specific repo worktree should only check that repo."""
        from canopy.integrations.precommit import run_precommit

        feature_dir = _setup_feature_worktrees(canopy_toml)

        # Change only api
        (feature_dir / "api" / "api_only.py").write_text("only api\n")

        ctx = detect_context(cwd=feature_dir / "api")
        assert ctx.context_type == "repo_worktree"
        assert len(ctx.repo_paths) == 1

        # Stage + run hooks
        git._run(["add", "-A"], cwd=ctx.repo_paths[0])
        hook_result = run_precommit(ctx.repo_paths[0])

        assert hook_result["passed"] is True

        # Should be staged, not committed
        staged = git._run(["diff", "--cached", "--name-only"], cwd=feature_dir / "api")
        assert "api_only.py" in staged

    def test_preflight_clean_repos(self, canopy_toml):
        """Clean repos should report 'clean' and not fail."""
        feature_dir = _setup_feature_worktrees(canopy_toml)

        ctx = detect_context(cwd=feature_dir)
        results = {}
        for repo_path, repo_name in zip(ctx.repo_paths, ctx.repo_names):
            status = git.status_porcelain(repo_path)
            if not status:
                results[repo_name] = "clean"
                continue

        assert results["api"] == "clean"
        assert results["ui"] == "clean"

    def test_preflight_partial_changes(self, canopy_toml):
        """Only repos with changes should get staged."""
        from canopy.integrations.precommit import run_precommit

        feature_dir = _setup_feature_worktrees(canopy_toml)

        # Only change api
        (feature_dir / "api" / "partial.py").write_text("partial\n")

        ctx = detect_context(cwd=feature_dir)
        results = {}
        for repo_path, repo_name in zip(ctx.repo_paths, ctx.repo_names):
            status = git.status_porcelain(repo_path)
            if not status:
                results[repo_name] = "clean"
                continue
            git._run(["add", "-A"], cwd=repo_path)
            hook_result = run_precommit(repo_path)
            results[repo_name] = "staged" if hook_result["passed"] else "failed"

        assert results["api"] == "staged"
        assert results["ui"] == "clean"
