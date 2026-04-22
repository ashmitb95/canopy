"""
Single-repo Git operations.

Every Git interaction goes through this module — nothing else shells out
to git directly. This is the only module that calls subprocess.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(Exception):
    """A git command failed."""
    def __init__(self, message: str, returncode: int = 1):
        super().__init__(message)
        self.returncode = returncode


def _run(args: list[str], cwd: Path, check: bool = True) -> str:
    """Run a git command and return stdout.

    Args:
        args: git subcommand + arguments (without 'git' prefix).
        cwd: repository path.
        check: if True, raise GitError on non-zero exit.

    Returns:
        Stripped stdout string.
    """
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip()
        raise GitError(
            f"git {' '.join(args)} failed: {stderr}",
            returncode=result.returncode,
        )
    return result.stdout.strip()


def _run_ok(args: list[str], cwd: Path) -> str:
    """Run a git command, returning stdout or empty string on failure."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


# ── Query operations ──────────────────────────────────────────────────────

def current_branch(repo_path: Path) -> str:
    """Get the current branch name, or '(detached)' if HEAD is detached."""
    branch = _run_ok(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    return "(detached)" if branch == "HEAD" else branch


def head_sha(repo_path: Path) -> str:
    """Get the full HEAD commit sha."""
    return _run(["rev-parse", "HEAD"], cwd=repo_path)


def short_sha(repo_path: Path) -> str:
    """Get the short HEAD commit sha."""
    return _run(["rev-parse", "--short", "HEAD"], cwd=repo_path)


def is_dirty(repo_path: Path) -> bool:
    """Check if the working tree has any changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=repo_path,
    )
    return bool(result.stdout.strip())


def dirty_file_count(repo_path: Path) -> int:
    """Count files with uncommitted changes."""
    output = _run_ok(["status", "--porcelain"], cwd=repo_path)
    if not output:
        return 0
    return len([line for line in output.split("\n") if line.strip()])


def remote_url(repo_path: Path) -> str:
    """Get the URL of the 'origin' remote, or empty string."""
    return _run_ok(["remote", "get-url", "origin"], cwd=repo_path)


def default_branch(repo_path: Path) -> str:
    """Detect the default branch (main or master)."""
    for candidate in ("main", "master"):
        result = subprocess.run(
            ["git", "rev-parse", "--verify", candidate],
            capture_output=True, text=True, cwd=repo_path,
        )
        if result.returncode == 0:
            return candidate
    return "main"


def divergence(repo_path: Path, branch: str, base: str) -> tuple[int, int]:
    """Count commits ahead and behind base.

    Returns:
        (ahead, behind) tuple.
    """
    ahead_out = _run_ok(["log", f"{base}..{branch}", "--oneline"], cwd=repo_path)
    behind_out = _run_ok(["log", f"{branch}..{base}", "--oneline"], cwd=repo_path)

    ahead = len(ahead_out.strip().split("\n")) if ahead_out else 0
    behind = len(behind_out.strip().split("\n")) if behind_out else 0

    return (ahead, behind)


def changed_files(repo_path: Path, branch: str, base: str) -> list[str]:
    """Get files changed between base and branch (three-dot diff)."""
    output = _run_ok(["diff", "--name-only", f"{base}...{branch}"], cwd=repo_path)
    if not output:
        return []
    return [f for f in output.split("\n") if f.strip()]


def branches(repo_path: Path) -> list[str]:
    """List all local branch names."""
    output = _run_ok(["branch", "--format=%(refname:short)"], cwd=repo_path)
    if not output:
        return []
    return [b.strip() for b in output.split("\n") if b.strip()]


def branch_exists(repo_path: Path, branch: str) -> bool:
    """Check if a local branch exists."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", branch],
        capture_output=True, text=True, cwd=repo_path,
    )
    return result.returncode == 0


# ── Write operations ─────────────────────────────────────────────────────

def create_branch(repo_path: Path, name: str, start_point: str = "HEAD") -> None:
    """Create a new branch."""
    _run(["branch", name, start_point], cwd=repo_path)


def checkout(repo_path: Path, branch: str) -> None:
    """Checkout a branch."""
    _run(["checkout", branch], cwd=repo_path)


def stage_files(repo_path: Path, files: list[str]) -> None:
    """Stage specific files."""
    if files:
        _run(["add"] + files, cwd=repo_path)


def unstage_files(repo_path: Path, files: list[str]) -> None:
    """Unstage specific files."""
    if files:
        _run(["restore", "--staged"] + files, cwd=repo_path)


def commit(repo_path: Path, message: str) -> str:
    """Create a commit with the given message. Returns the new commit sha."""
    _run(["commit", "-m", message], cwd=repo_path)
    return head_sha(repo_path)


# ── Diff / log ────────────────────────────────────────────────────────────

def diff_stat(repo_path: Path, ref_a: str, ref_b: str) -> dict:
    """Get diff stats between two refs.

    Returns:
        {files_changed: int, insertions: int, deletions: int}
    """
    output = _run_ok(
        ["diff", "--shortstat", f"{ref_a}...{ref_b}"],
        cwd=repo_path,
    )
    result = {"files_changed": 0, "insertions": 0, "deletions": 0}
    if not output:
        return result

    # "3 files changed, 45 insertions(+), 12 deletions(-)"
    import re
    m = re.search(r"(\d+) files? changed", output)
    if m:
        result["files_changed"] = int(m.group(1))
    m = re.search(r"(\d+) insertions?", output)
    if m:
        result["insertions"] = int(m.group(1))
    m = re.search(r"(\d+) deletions?", output)
    if m:
        result["deletions"] = int(m.group(1))

    return result


def log_oneline(repo_path: Path, ref_range: str, max_count: int = 20) -> list[str]:
    """Get one-line log entries for a ref range."""
    output = _run_ok(
        ["log", ref_range, "--oneline", f"--max-count={max_count}"],
        cwd=repo_path,
    )
    if not output:
        return []
    return [line for line in output.split("\n") if line.strip()]


def status_porcelain(repo_path: Path) -> list[dict]:
    """Get porcelain status output as structured data.

    Returns:
        List of {path, index_status, worktree_status}
    """
    # Use raw subprocess to preserve leading spaces (porcelain format uses them)
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=repo_path,
    )
    raw = result.stdout
    if not raw or not raw.strip():
        return []

    entries = []
    for line in raw.splitlines():
        if len(line) < 4:
            continue
        index_status = line[0]
        worktree_status = line[1]
        path = line[3:]
        entries.append({
            "path": path,
            "index_status": index_status.strip(),
            "worktree_status": worktree_status.strip(),
        })

    return entries


def pull_rebase(repo_path: Path, remote: str = "origin", branch: str | None = None) -> str:
    """Pull with rebase from remote. Returns output message."""
    args = ["pull", "--rebase", remote]
    if branch:
        args.append(branch)
    return _run(args, cwd=repo_path)


def merge_base(repo_path: Path, ref_a: str, ref_b: str) -> str:
    """Find the merge base of two refs."""
    return _run(["merge-base", ref_a, ref_b], cwd=repo_path)
