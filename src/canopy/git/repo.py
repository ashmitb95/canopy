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


# ── Stash ─────────────────────────────────────────────────────────────────

def stash_save(repo_path: Path, message: str = "") -> bool:
    """Stash uncommitted changes. Returns True if anything was stashed."""
    args = ["stash", "push"]
    if message:
        args.extend(["-m", message])
    output = _run(args, cwd=repo_path)
    # "No local changes to save" means nothing was stashed
    return "No local changes" not in output


def stash_pop(repo_path: Path, index: int = 0) -> str:
    """Pop a stash entry. Returns output message."""
    return _run(["stash", "pop", f"stash@{{{index}}}"], cwd=repo_path)


def stash_list(repo_path: Path) -> list[dict]:
    """List stash entries.

    Returns:
        List of {index, branch, message}
    """
    output = _run_ok(["stash", "list", "--format=%gd|%gs"], cwd=repo_path)
    if not output:
        return []

    entries = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 1)
        ref = parts[0].strip()  # stash@{0}
        desc = parts[1].strip() if len(parts) > 1 else ""
        # Extract index from stash@{N}
        try:
            idx = int(ref.split("{")[1].rstrip("}"))
        except (IndexError, ValueError):
            idx = 0
        entries.append({
            "index": idx,
            "ref": ref,
            "message": desc,
        })
    return entries


def stash_drop(repo_path: Path, index: int = 0) -> str:
    """Drop a stash entry."""
    return _run(["stash", "drop", f"stash@{{{index}}}"], cwd=repo_path)


# ── Branch management ─────────────────────────────────────────────────────

def delete_branch(repo_path: Path, name: str, force: bool = False) -> str:
    """Delete a local branch."""
    flag = "-D" if force else "-d"
    return _run(["branch", flag, name], cwd=repo_path)


def rename_branch(repo_path: Path, old_name: str, new_name: str) -> str:
    """Rename a local branch."""
    return _run(["branch", "-m", old_name, new_name], cwd=repo_path)


def all_branches(repo_path: Path) -> list[dict]:
    """List all local branches with metadata.

    Returns:
        List of {name, is_current, sha, subject}
    """
    output = _run_ok(
        ["branch", "--format=%(HEAD)|%(refname:short)|%(objectname:short)|%(subject)"],
        cwd=repo_path,
    )
    if not output:
        return []

    entries = []
    for line in output.splitlines():
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        entries.append({
            "name": parts[1].strip(),
            "is_current": parts[0].strip() == "*",
            "sha": parts[2].strip(),
            "subject": parts[3].strip(),
        })
    return entries


# ── Worktree ──────────────────────────────────────────────────────────────

def is_worktree(repo_path: Path) -> bool:
    """Check if repo_path is a linked worktree (not the main working tree).

    Linked worktrees have a `.git` *file* (not directory) that points to
    the main repo's `.git/worktrees/<name>/` directory.
    """
    git_path = repo_path / ".git"
    return git_path.is_file()


def worktree_main_path(repo_path: Path) -> Path | None:
    """If repo_path is a linked worktree, return the main working tree path.

    Returns None if this is the main working tree (not a linked worktree).
    """
    common = _run_ok(["rev-parse", "--git-common-dir"], cwd=repo_path)
    local = _run_ok(["rev-parse", "--git-dir"], cwd=repo_path)

    if not common or not local:
        return None

    common_resolved = (repo_path / common).resolve()
    local_resolved = (repo_path / local).resolve()

    if common_resolved == local_resolved:
        return None  # main working tree

    # common-dir is the main repo's .git — its parent is the main working tree
    return common_resolved.parent


def worktree_list(repo_path: Path) -> list[dict]:
    """List all worktrees for the repo at repo_path.

    Returns:
        List of {path, head, branch, is_bare}
    """
    output = _run_ok(["worktree", "list", "--porcelain"], cwd=repo_path)
    if not output:
        return []

    worktrees = []
    current: dict = {}
    for line in output.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line[9:], "head": "", "branch": "", "is_bare": False}
        elif line.startswith("HEAD "):
            current["head"] = line[5:]
        elif line.startswith("branch "):
            # "branch refs/heads/main" -> "main"
            ref = line[7:]
            current["branch"] = ref.replace("refs/heads/", "")
        elif line == "bare":
            current["is_bare"] = True
        elif line == "detached":
            current["branch"] = "(detached)"

    if current:
        worktrees.append(current)

    return worktrees


def worktree_for_branch(repo_path: Path, branch: str) -> str | None:
    """Find the worktree path where a branch is checked out.

    Returns the worktree path string, or None if the branch isn't
    checked out in any worktree.
    """
    for wt in worktree_list(repo_path):
        if wt.get("branch") == branch:
            return wt["path"]
    return None


def worktree_add(
    repo_path: Path,
    dest_path: Path,
    branch: str,
    create_branch: bool = True,
) -> str:
    """Create a new linked worktree.

    Args:
        repo_path: The main repo (or any existing worktree of it).
        dest_path: Where to create the new worktree directory.
        branch: Branch name to checkout in the worktree.
        create_branch: If True and branch doesn't exist, create it (-b).

    Returns:
        Output message from git.
    """
    args = ["worktree", "add"]
    if create_branch and not branch_exists(repo_path, branch):
        args.extend(["-b", branch])
    args.append(str(dest_path))
    if not create_branch or branch_exists(repo_path, branch):
        args.append(branch)
    return _run(args, cwd=repo_path)


def worktree_remove(repo_path: Path, worktree_path: Path, force: bool = False) -> str:
    """Remove a linked worktree."""
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(worktree_path))
    return _run(args, cwd=repo_path)


# ── Log ───────────────────────────────────────────────────────────────────

def log_structured(
    repo_path: Path,
    ref: str = "HEAD",
    max_count: int = 20,
) -> list[dict]:
    """Get structured log entries.

    Returns:
        List of {sha, short_sha, author, date, subject}
    """
    sep = "\x1f"  # unit separator
    fmt = f"%H{sep}%h{sep}%an{sep}%ai{sep}%s"
    output = _run_ok(
        ["log", ref, f"--format={fmt}", f"--max-count={max_count}"],
        cwd=repo_path,
    )
    if not output:
        return []

    entries = []
    for line in output.splitlines():
        parts = line.split(sep)
        if len(parts) < 5:
            continue
        entries.append({
            "sha": parts[0],
            "short_sha": parts[1],
            "author": parts[2],
            "date": parts[3],
            "subject": parts[4],
        })
    return entries
