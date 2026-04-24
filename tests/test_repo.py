"""Tests for git.repo module."""
import os
import subprocess
import pytest
from pathlib import Path

from canopy.git.repo import (
    current_branch, head_sha, short_sha, is_dirty, dirty_file_count,
    default_branch, divergence, changed_files, branches, branch_exists,
    create_branch, checkout, stage_files, commit, status_porcelain,
    log_oneline, diff_stat, GitError,
)


def _git(args, cwd):
    subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True, check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )


@pytest.fixture
def git_repo(tmp_path):
    """A simple git repo with one commit on main."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], cwd=repo)
    _git(["config", "user.email", "t@t.com"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)
    (repo / "hello.py").write_text("print('hello')\n")
    _git(["add", "."], cwd=repo)
    _git(["commit", "-m", "init"], cwd=repo)
    return repo


def test_current_branch(git_repo):
    assert current_branch(git_repo) == "main"


def test_head_sha(git_repo):
    sha = head_sha(git_repo)
    assert len(sha) == 40


def test_short_sha(git_repo):
    sha = short_sha(git_repo)
    assert 4 <= len(sha) <= 12


def test_is_dirty_clean(git_repo):
    assert is_dirty(git_repo) is False


def test_is_dirty_modified(git_repo):
    (git_repo / "hello.py").write_text("print('modified')\n")
    assert is_dirty(git_repo) is True


def test_dirty_file_count(git_repo):
    assert dirty_file_count(git_repo) == 0
    (git_repo / "hello.py").write_text("print('mod')\n")
    (git_repo / "new.py").write_text("new\n")
    assert dirty_file_count(git_repo) == 2


def test_default_branch(git_repo):
    assert default_branch(git_repo) == "main"


def test_branches(git_repo):
    b = branches(git_repo)
    assert "main" in b


def test_create_branch(git_repo):
    create_branch(git_repo, "feature-x")
    assert "feature-x" in branches(git_repo)
    assert branch_exists(git_repo, "feature-x")


def test_create_branch_does_not_inherit_upstream(git_repo, tmp_path):
    """New branches must not inherit the start-point's upstream tracking.

    Without --no-track, a user with branch.autoSetupMerge=always (or =inherit
    matching a remote-tracking start_point) would silently get the new
    branch tracking the start_point's remote. Then `git push` would push to
    the wrong remote branch.
    """
    # Set up a bare remote and push main to it so origin/main exists.
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(["init", "--bare", "-b", "main"], cwd=remote)
    _git(["remote", "add", "origin", str(remote)], cwd=git_repo)
    _git(["push", "-u", "origin", "main"], cwd=git_repo)
    # Aggressive auto-tracking: would normally inherit from any start point.
    _git(["config", "branch.autoSetupMerge", "always"], cwd=git_repo)

    create_branch(git_repo, "no-inherit")

    # No upstream tracking should be configured on the new branch.
    result = subprocess.run(
        ["git", "config", "--get", "branch.no-inherit.remote"],
        cwd=git_repo, capture_output=True, text=True,
    )
    assert result.returncode != 0, (
        f"new branch unexpectedly has upstream tracking: "
        f"branch.no-inherit.remote = {result.stdout.strip()!r}"
    )


def test_branch_exists_false(git_repo):
    assert branch_exists(git_repo, "nonexistent") is False


def test_checkout(git_repo):
    create_branch(git_repo, "feature-y")
    checkout(git_repo, "feature-y")
    assert current_branch(git_repo) == "feature-y"


def test_divergence(git_repo):
    # Create feature branch with a commit
    create_branch(git_repo, "feature-z")
    checkout(git_repo, "feature-z")
    (git_repo / "feature.py").write_text("feature\n")
    _git(["add", "."], cwd=git_repo)
    _git(["commit", "-m", "feature commit"], cwd=git_repo)

    ahead, behind = divergence(git_repo, "feature-z", "main")
    assert ahead == 1
    assert behind == 0


def test_changed_files(git_repo):
    create_branch(git_repo, "changes")
    checkout(git_repo, "changes")
    (git_repo / "new_file.py").write_text("new\n")
    (git_repo / "hello.py").write_text("print('changed')\n")
    _git(["add", "."], cwd=git_repo)
    _git(["commit", "-m", "changes"], cwd=git_repo)

    files = changed_files(git_repo, "changes", "main")
    assert "hello.py" in files
    assert "new_file.py" in files


def test_stage_and_commit(git_repo):
    (git_repo / "staged.py").write_text("staged\n")
    stage_files(git_repo, ["staged.py"])

    status = status_porcelain(git_repo)
    assert any(e["path"] == "staged.py" for e in status)

    new_sha = commit(git_repo, "add staged file")
    assert len(new_sha) == 40


def test_log_oneline(git_repo):
    logs = log_oneline(git_repo, "main", max_count=5)
    assert len(logs) >= 1
    assert "init" in logs[0]


def test_status_porcelain_clean(git_repo):
    assert status_porcelain(git_repo) == []


def test_status_porcelain_dirty(git_repo):
    (git_repo / "hello.py").write_text("modified\n")
    status = status_porcelain(git_repo)
    assert len(status) == 1
    assert status[0]["path"] == "hello.py"
