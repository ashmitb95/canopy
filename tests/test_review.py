"""
Tests for the review workflow: GitHub integration, pre-commit detection,
and the review_status / review_comments / review_prep coordinator methods.

GitHub MCP calls are mocked — these tests verify the data flow and
orchestration, not actual GitHub API responses.
"""
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from canopy.integrations.github import (
    _extract_owner_repo,
    _normalize_pr,
    _normalize_comments,
    _extract_prs,
    is_github_configured,
    GitHubNotConfiguredError,
    PullRequestNotFoundError,
)
from canopy.integrations.precommit import (
    detect_precommit,
    run_precommit,
)


# ── Helper ──────────────────────────────────────────────────────────────

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


# ── GitHub URL parsing ──────────────────────────────────────────────────

class TestExtractOwnerRepo:
    def test_ssh_url(self):
        assert _extract_owner_repo("git@github.com:ashmitb/canopy.git") == ("ashmitb", "canopy")

    def test_ssh_url_no_git_suffix(self):
        assert _extract_owner_repo("git@github.com:org/repo") == ("org", "repo")

    def test_https_url(self):
        assert _extract_owner_repo("https://github.com/ashmitb/canopy.git") == ("ashmitb", "canopy")

    def test_https_url_no_git_suffix(self):
        assert _extract_owner_repo("https://github.com/org/repo") == ("org", "repo")

    def test_non_github_url(self):
        assert _extract_owner_repo("https://gitlab.com/org/repo.git") is None

    def test_empty_url(self):
        assert _extract_owner_repo("") is None

    def test_malformed_url(self):
        assert _extract_owner_repo("not-a-url") is None


# ── PR normalization ────────────────────────────────────────────────────

class TestNormalizePr:
    def test_standard_github_shape(self):
        pr = _normalize_pr({
            "number": 42,
            "title": "Add auth module",
            "html_url": "https://github.com/org/repo/pull/42",
            "state": "open",
            "head": {"ref": "auth-flow"},
            "body": "Adds authentication...",
        })
        assert pr["number"] == 42
        assert pr["title"] == "Add auth module"
        assert pr["url"] == "https://github.com/org/repo/pull/42"
        assert pr["head_branch"] == "auth-flow"

    def test_minimal_pr(self):
        pr = _normalize_pr({"number": 1})
        assert pr["number"] == 1
        assert pr["title"] == ""
        assert pr["head_branch"] == ""


# ── Comment normalization ───────────────────────────────────────────────

class TestNormalizeComments:
    def test_standard_comments(self):
        raw = [
            {
                "path": "src/auth.py",
                "line": 10,
                "body": "Add error handling here",
                "user": {"login": "reviewer1", "type": "User"},
                "created_at": "2025-01-01T00:00:00Z",
                "html_url": "https://github.com/org/repo/pull/42#comment-1",
            },
            {
                "path": "src/models.py",
                "line": 5,
                "body": "Missing docstring",
                "user": {"login": "reviewer2", "type": "User"},
                "created_at": "2025-01-02T00:00:00Z",
            },
        ]
        comments = _normalize_comments(raw)
        assert len(comments) == 2
        assert comments[0]["path"] == "src/auth.py"
        assert comments[0]["author"] == "reviewer1"
        assert comments[1]["body"] == "Missing docstring"

    def test_resolved_comments_filtered(self):
        raw = [
            {"path": "a.py", "body": "fix this", "user": {"login": "r"}},
            {"path": "b.py", "body": "resolved", "user": {"login": "r"}, "state": "RESOLVED"},
            {"path": "c.py", "body": "also resolved", "user": {"login": "r"}, "resolved": True},
        ]
        comments = _normalize_comments(raw)
        assert len(comments) == 1
        assert comments[0]["path"] == "a.py"

    def test_bot_comments_filtered(self):
        raw = [
            {"path": "a.py", "body": "real comment", "user": {"login": "human", "type": "User"}},
            {"path": "b.py", "body": "bot comment", "user": {"login": "github-actions[bot]", "type": "Bot"}},
        ]
        comments = _normalize_comments(raw)
        assert len(comments) == 1
        assert comments[0]["author"] == "human"

    def test_empty_list(self):
        assert _normalize_comments([]) == []

    def test_dict_wrapped_comments(self):
        raw = {"comments": [
            {"path": "a.py", "body": "fix", "user": {"login": "r"}},
        ]}
        comments = _normalize_comments(raw)
        assert len(comments) == 1


# ── PR extraction with branch filter ───────────────────────────────────

class TestExtractPrs:
    def test_filters_by_branch(self):
        prs = [
            {"number": 1, "head": {"ref": "auth-flow"}},
            {"number": 2, "head": {"ref": "payment-flow"}},
        ]
        result = _extract_prs(prs, "auth-flow")
        assert len(result) == 1
        assert result[0]["number"] == 1

    def test_empty_when_no_match(self):
        prs = [{"number": 1, "head": {"ref": "other-branch"}}]
        result = _extract_prs(prs, "auth-flow")
        assert result == []


# ── Pre-commit detection ────────────────────────────────────────────────

class TestPrecommitDetection:
    def test_detect_framework(self, tmp_path):
        (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n")
        assert detect_precommit(tmp_path) == "framework"

    def test_detect_git_hook(self, tmp_path):
        hooks_dir = tmp_path / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)
        hook = hooks_dir / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)
        assert detect_precommit(tmp_path) == "git_hook"

    def test_detect_none(self, tmp_path):
        (tmp_path / ".git").mkdir()
        assert detect_precommit(tmp_path) == "none"

    def test_detect_worktree_hook(self, workspace_dir):
        """Worktrees inherit hooks from the main repo."""
        api = workspace_dir / "api"
        # Add a pre-commit hook to the main repo
        hooks_dir = api / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook = hooks_dir / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)

        # Create a worktree
        wt_path = workspace_dir / ".canopy" / "worktrees" / "test-feat" / "api"
        wt_path.parent.mkdir(parents=True, exist_ok=True)
        _git(["worktree", "add", "-b", "test-feat", str(wt_path)], cwd=api)

        # The worktree should detect the hook from the main repo
        assert detect_precommit(wt_path) == "git_hook"

        # Cleanup
        _git(["worktree", "remove", str(wt_path)], cwd=api)


class TestRunPrecommit:
    def test_no_hooks_passes(self, tmp_path):
        (tmp_path / ".git").mkdir()
        result = run_precommit(tmp_path)
        assert result["type"] == "none"
        assert result["passed"] is True

    def test_passing_git_hook(self, tmp_path):
        # Set up a real git repo with a passing hook
        _git(["init", "-b", "main"], cwd=tmp_path)
        _git(["config", "user.email", "test@test.com"], cwd=tmp_path)
        _git(["config", "user.name", "Test"], cwd=tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        _git(["add", "."], cwd=tmp_path)
        _git(["commit", "-m", "init"], cwd=tmp_path)

        hooks_dir = tmp_path / ".git" / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        hook = hooks_dir / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)

        result = run_precommit(tmp_path)
        assert result["type"] == "git_hook"
        assert result["passed"] is True

    def test_failing_git_hook(self, tmp_path):
        _git(["init", "-b", "main"], cwd=tmp_path)
        _git(["config", "user.email", "test@test.com"], cwd=tmp_path)
        _git(["config", "user.name", "Test"], cwd=tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        _git(["add", "."], cwd=tmp_path)
        _git(["commit", "-m", "init"], cwd=tmp_path)

        hooks_dir = tmp_path / ".git" / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        hook = hooks_dir / "pre-commit"
        hook.write_text("#!/bin/sh\necho 'Hook failed'\nexit 1\n")
        hook.chmod(0o755)

        result = run_precommit(tmp_path)
        assert result["type"] == "git_hook"
        assert result["passed"] is False


# ── GitHub MCP config ───────────────────────────────────────────────────

class TestGitHubConfig:
    def test_not_configured(self, tmp_path):
        assert is_github_configured(tmp_path) is False

    def test_configured(self, tmp_path):
        canopy_dir = tmp_path / ".canopy"
        canopy_dir.mkdir()
        (canopy_dir / "mcps.json").write_text(json.dumps({
            "github": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_test"},
            }
        }))
        assert is_github_configured(tmp_path) is True


# ── Coordinator review_status (mocked MCP) ─────────────────────────────

class TestReviewStatus:
    def test_no_github_config_raises(self, workspace_with_feature, canopy_toml):
        """review_status raises if GitHub MCP isn't configured."""
        from canopy.workspace.config import load_config
        from canopy.workspace.workspace import Workspace
        from canopy.features.coordinator import FeatureCoordinator

        config = load_config(canopy_toml)
        ws = Workspace(config)
        coordinator = FeatureCoordinator(ws)

        with pytest.raises(GitHubNotConfiguredError):
            coordinator.review_status("auth-flow")


# ── Coordinator review_prep (real git, no MCP needed) ──────────────────

class TestReviewPrep:
    def test_prep_stages_dirty_files(self, workspace_with_feature, canopy_toml):
        """review_prep stages changes and reports results."""
        from canopy.workspace.config import load_config
        from canopy.workspace.workspace import Workspace
        from canopy.features.coordinator import FeatureCoordinator

        config = load_config(canopy_toml)
        ws = Workspace(config)
        coordinator = FeatureCoordinator(ws)

        # Create feature with worktrees
        lane = coordinator.create("prep-test", use_worktrees=True)

        # Make changes in a worktree
        wt_path = canopy_toml / ".canopy" / "worktrees" / "prep-test" / "api"
        (wt_path / "new_file.py").write_text("# new file\n")

        result = coordinator.review_prep("prep-test", message="fix: address review")

        assert result["feature"] == "prep-test"
        assert result["message"] == "fix: address review"
        assert "api" in result["repos"]

        api_result = result["repos"]["api"]
        assert api_result["staged"] is True
        assert api_result["dirty_count"] >= 1
        assert api_result["precommit"]["type"] == "none"
        assert api_result["precommit"]["passed"] is True

        # Cleanup
        from canopy.git import repo as git_repo
        api_main = canopy_toml / "api"
        git_repo.worktree_remove(api_main, wt_path, force=True)
        ui_wt_path = canopy_toml / ".canopy" / "worktrees" / "prep-test" / "ui"
        ui_main = canopy_toml / "ui"
        git_repo.worktree_remove(ui_main, ui_wt_path, force=True)

    def test_prep_clean_repos(self, workspace_with_feature, canopy_toml):
        """review_prep handles clean repos gracefully."""
        from canopy.workspace.config import load_config
        from canopy.workspace.workspace import Workspace
        from canopy.features.coordinator import FeatureCoordinator

        config = load_config(canopy_toml)
        ws = Workspace(config)
        coordinator = FeatureCoordinator(ws)

        # Create worktrees but don't modify anything
        lane = coordinator.create("clean-test", use_worktrees=True)

        result = coordinator.review_prep("clean-test")

        assert result["all_passed"] is True
        for repo_name, info in result["repos"].items():
            assert info["staged"] is False
            assert info["dirty_count"] == 0

        # Cleanup
        from canopy.git import repo as git_repo
        for repo_name in ["api", "ui"]:
            wt_path = canopy_toml / ".canopy" / "worktrees" / "clean-test" / repo_name
            main_path = canopy_toml / repo_name
            git_repo.worktree_remove(main_path, wt_path, force=True)

    def test_prep_with_precommit_hook(self, workspace_with_feature, canopy_toml):
        """review_prep runs pre-commit hooks when present."""
        from canopy.workspace.config import load_config
        from canopy.workspace.workspace import Workspace
        from canopy.features.coordinator import FeatureCoordinator

        config = load_config(canopy_toml)
        ws = Workspace(config)
        coordinator = FeatureCoordinator(ws)

        # Create worktrees
        lane = coordinator.create("hook-test", use_worktrees=True)

        # Install a passing pre-commit hook in the api repo
        # The hook lives in the main repo's .git/hooks/ — worktrees inherit it
        api_main = canopy_toml / "api"
        hooks_dir = api_main / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook = hooks_dir / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)

        # Make a change
        wt_path = canopy_toml / ".canopy" / "worktrees" / "hook-test" / "api"
        (wt_path / "touched.py").write_text("# touched\n")

        result = coordinator.review_prep("hook-test")

        api_result = result["repos"]["api"]
        assert api_result["precommit"]["type"] == "git_hook"
        assert api_result["precommit"]["passed"] is True
        assert api_result["staged"] is True

        # Cleanup
        from canopy.git import repo as git_repo
        for repo_name in ["api", "ui"]:
            wt_path = canopy_toml / ".canopy" / "worktrees" / "hook-test" / repo_name
            main_path = canopy_toml / repo_name
            git_repo.worktree_remove(main_path, wt_path, force=True)
