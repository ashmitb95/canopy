"""Tests for git.repo module."""
import os
import subprocess
import pytest
from pathlib import Path

from canopy.git.repo import (
    current_branch, head_sha, short_sha, is_dirty, dirty_file_count,
    default_branch, divergence, changed_files, branches, branch_exists,
    create_branch, checkout, stage_files, stage_all_tracked,
    staged_file_count, commit, status_porcelain,
    log_oneline, diff_stat, GitError,
    has_upstream, upstream_ref, unpushed_count, push,
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

    result = commit(git_repo, "add staged file")
    assert len(result["sha"]) == 40
    assert result["files_changed"] == 1


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


# ── stage_all_tracked / staged_file_count ────────────────────────────────

def test_stage_all_tracked_picks_up_modifications(git_repo):
    (git_repo / "hello.py").write_text("modified\n")
    (git_repo / "untracked.py").write_text("untracked\n")  # should NOT be staged
    stage_all_tracked(git_repo)
    assert staged_file_count(git_repo) == 1


def test_staged_file_count_zero_when_clean(git_repo):
    assert staged_file_count(git_repo) == 0


# ── commit primitive: amend / no_hooks / files_changed ──────────────────

def test_commit_amend_replaces_head(git_repo):
    base = head_sha(git_repo)
    (git_repo / "hello.py").write_text("changed\n")
    stage_all_tracked(git_repo)
    result = commit(git_repo, "amended", amend=True)
    assert result["sha"] != base  # amend rewrites the sha
    assert result["files_changed"] == 1


def test_commit_no_hooks_skips_pre_commit(git_repo):
    # Install a pre-commit hook that always fails.
    hooks_dir = git_repo / ".git" / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    pc = hooks_dir / "pre-commit"
    pc.write_text("#!/bin/sh\nexit 1\n")
    pc.chmod(0o755)

    (git_repo / "hello.py").write_text("changed\n")
    stage_all_tracked(git_repo)

    with pytest.raises(GitError):
        commit(git_repo, "should fail")

    result = commit(git_repo, "skip hooks", no_hooks=True)
    assert len(result["sha"]) == 40


def test_commit_files_changed_for_multi_file_commit(git_repo):
    (git_repo / "a.py").write_text("a\n")
    (git_repo / "b.py").write_text("b\n")
    stage_files(git_repo, ["a.py", "b.py"])
    result = commit(git_repo, "two files")
    assert result["files_changed"] == 2


# ── push / upstream queries ──────────────────────────────────────────────

@pytest.fixture
def git_repo_with_remote(tmp_path):
    """A git repo with a configured (bare) origin remote on `main`."""
    bare = tmp_path / "origin.git"
    bare.mkdir()
    _git(["init", "--bare", "-b", "main"], cwd=bare)

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], cwd=repo)
    _git(["config", "user.email", "t@t.com"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)
    _git(["remote", "add", "origin", str(bare)], cwd=repo)
    (repo / "hello.py").write_text("print('hello')\n")
    _git(["add", "."], cwd=repo)
    _git(["commit", "-m", "init"], cwd=repo)
    return repo


def test_has_upstream_false_before_push(git_repo_with_remote):
    assert has_upstream(git_repo_with_remote) is False


def test_unpushed_count_zero_without_upstream(git_repo_with_remote):
    # Without an upstream, unpushed_count returns 0 — caller disambiguates.
    assert unpushed_count(git_repo_with_remote) == 0


def test_push_set_upstream_then_status_ok(git_repo_with_remote):
    result = push(git_repo_with_remote, branch="main", set_upstream=True)
    assert result["status"] == "ok"
    assert result["set_upstream"] is True
    assert has_upstream(git_repo_with_remote) is True
    assert upstream_ref(git_repo_with_remote) == "origin/main"


def test_push_when_up_to_date_still_returns_ok(git_repo_with_remote):
    push(git_repo_with_remote, branch="main", set_upstream=True)
    # Nothing new to push — git push reports up-to-date but exits 0.
    again = push(git_repo_with_remote)
    assert again["status"] == "ok"
    assert again["pushed_count"] == 0


def test_push_pushed_count_after_new_commit(git_repo_with_remote):
    push(git_repo_with_remote, branch="main", set_upstream=True)
    (git_repo_with_remote / "more.py").write_text("more\n")
    stage_files(git_repo_with_remote, ["more.py"])
    commit(git_repo_with_remote, "second")
    assert unpushed_count(git_repo_with_remote) == 1
    result = push(git_repo_with_remote)
    assert result["status"] == "ok"
    assert result["pushed_count"] == 1


def test_push_dry_run_does_not_advance_upstream(git_repo_with_remote):
    push(git_repo_with_remote, branch="main", set_upstream=True)
    (git_repo_with_remote / "more.py").write_text("more\n")
    stage_files(git_repo_with_remote, ["more.py"])
    commit(git_repo_with_remote, "second")
    result = push(git_repo_with_remote, dry_run=True)
    assert result["status"] == "ok"
    assert result.get("dry_run") is True
    # Upstream still 1 commit behind.
    assert unpushed_count(git_repo_with_remote) == 1


def test_push_rejected_on_non_fast_forward(git_repo_with_remote, tmp_path):
    push(git_repo_with_remote, branch="main", set_upstream=True)

    # Clone the bare remote into a second working tree, push a divergent commit.
    second = tmp_path / "second"
    second.mkdir()
    bare = tmp_path / "origin.git"
    _git(["clone", str(bare), str(second)], cwd=tmp_path)
    _git(["config", "user.email", "u@u.com"], cwd=second)
    _git(["config", "user.name", "Other"], cwd=second)
    (second / "diverged.py").write_text("diverged\n")
    _git(["add", "."], cwd=second)
    _git(["commit", "-m", "diverged"], cwd=second)
    _git(["push", "origin", "main"], cwd=second)

    # Local repo now has its own commit on main; push should be rejected.
    (git_repo_with_remote / "local.py").write_text("local\n")
    stage_files(git_repo_with_remote, ["local.py"])
    commit(git_repo_with_remote, "local change")
    result = push(git_repo_with_remote)
    assert result["status"] == "rejected"
    assert "reason" in result


def test_push_force_with_lease_flag_plumbed(git_repo_with_remote):
    # Flag-plumbing smoke test: passing force_with_lease=True against an
    # already-up-to-date branch should still succeed (no rejection,
    # nothing to force). The non-fast-forward acceptance path is not
    # worth its own integration test — it's a one-flag pass-through.
    push(git_repo_with_remote, branch="main", set_upstream=True)
    result = push(git_repo_with_remote, force_with_lease=True)
    assert result["status"] == "ok"
