"""
Single-repo Git operations.

Every Git interaction goes through this module — nothing else shells out
to git directly. This is the only module that calls subprocess.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


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


def sha_of(repo_path: Path, ref: str) -> str:
    """Resolve any ref (branch / sha / tag) to its full commit sha.

    Returns empty string if the ref doesn't resolve.
    """
    try:
        return _run(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=repo_path)
    except GitError:
        return ""


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


def changed_files_with_status(repo_path: Path, branch: str, base: str) -> list[dict]:
    """Get files changed between base and branch, with M/A/D status.

    Includes uncommitted changes (working tree + index) so the listing
    matches what the user sees when editing files in a worktree.

    Returns:
        List of {path, status} where status is one of:
          "M" modified, "A" added, "D" deleted, "R" renamed,
          "C" copied, "T" type-changed, "?" untracked.
    """
    entries: dict[str, str] = {}

    committed = _run_ok(
        ["diff", "--name-status", f"{base}...{branch}"], cwd=repo_path,
    )
    for line in committed.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][0].upper()
        path = parts[-1]
        entries[path] = status

    # Porcelain output preserves leading spaces; don't use _run_ok (which strips).
    raw = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=repo_path,
    ).stdout
    for line in raw.splitlines():
        if len(line) < 4:
            continue
        index_status = line[0]
        worktree_status = line[1]
        path = line[3:]
        if index_status == "?" and worktree_status == "?":
            entries[path] = "?"
            continue
        # Prefer index status when staged, otherwise worktree status.
        status = index_status.strip() or worktree_status.strip()
        if status:
            entries[path] = status.upper()

    return [{"path": p, "status": s} for p, s in sorted(entries.items())]


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
    """Create a new branch.

    Uses --no-track so the new branch does not inherit the start_point's
    upstream. Without this, a user gitconfig of branch.autoSetupMerge=inherit
    (or =simple matching a remote-tracking start_point) would silently make
    the new branch track origin/<start_point> — so a later `git push` would
    push to the start_point's branch on the remote. Upstream gets set
    explicitly on first push instead.
    """
    _run(["branch", "--no-track", name, start_point], cwd=repo_path)


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


def stage_all_tracked(repo_path: Path) -> None:
    """Stage all tracked, modified files (mirror of `git add -u`)."""
    _run(["add", "-u"], cwd=repo_path)


def staged_file_count(repo_path: Path) -> int:
    """Count files currently in the index awaiting commit."""
    output = _run_ok(["diff", "--cached", "--name-only"], cwd=repo_path)
    if not output:
        return 0
    return len([line for line in output.split("\n") if line.strip()])


def commit(
    repo_path: Path,
    message: str,
    *,
    amend: bool = False,
    no_hooks: bool = False,
    allow_empty: bool = False,
) -> dict[str, Any]:
    """Create a commit. Returns ``{sha, files_changed}``.

    ``files_changed`` is the count of files touched by the new commit
    (uses ``git show --name-only`` against the resulting HEAD, so it
    works for the first commit and for ``--amend``).

    Args:
        amend: pass ``--amend``. Reuses the existing message via ``-m``
            anyway (caller controls the new message).
        no_hooks: pass ``--no-verify`` to skip pre-commit / commit-msg hooks.
        allow_empty: pass ``--allow-empty``.
    """
    args = ["commit", "-m", message]
    if amend:
        args.append("--amend")
    if no_hooks:
        args.append("--no-verify")
    if allow_empty:
        args.append("--allow-empty")
    _run(args, cwd=repo_path)
    sha = head_sha(repo_path)
    show_out = _run_ok(
        ["show", "--name-only", "--pretty=format:", "HEAD"], cwd=repo_path,
    )
    files_changed = len([line for line in show_out.split("\n") if line.strip()])
    return {"sha": sha, "files_changed": files_changed}


# ── Push / upstream queries ──────────────────────────────────────────────

def has_upstream(repo_path: Path, branch: str | None = None) -> bool:
    """Check whether ``branch`` (or current branch) has a configured upstream."""
    target = f"{branch}@{{upstream}}" if branch else "@{upstream}"
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", target],
        capture_output=True, text=True, cwd=repo_path,
    )
    return result.returncode == 0


def upstream_ref(repo_path: Path, branch: str | None = None) -> str:
    """Return the upstream ref (e.g. ``origin/main``), or empty string if unset."""
    target = f"{branch}@{{upstream}}" if branch else "@{upstream}"
    return _run_ok(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", target],
        cwd=repo_path,
    )


def unpushed_count(repo_path: Path, branch: str | None = None) -> int:
    """Count commits HEAD (or branch) is ahead of its upstream.

    Returns 0 when the branch is up-to-date OR has no upstream — caller
    should check ``has_upstream`` to disambiguate.
    """
    target = branch or "HEAD"
    upstream = f"{branch}@{{upstream}}" if branch else "@{upstream}"
    result = subprocess.run(
        ["git", "rev-list", "--count", f"{upstream}..{target}"],
        capture_output=True, text=True, cwd=repo_path,
    )
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip() or "0")
    except ValueError:
        return 0


def push(
    repo_path: Path,
    *,
    branch: str | None = None,
    remote: str = "origin",
    set_upstream: bool = False,
    force_with_lease: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run ``git push`` and return a structured result.

    Returns one of:
      - ``{status: "ok", pushed_count, ref, set_upstream?, dry_run?}``
      - ``{status: "rejected", reason}`` — non-fast-forward without ``force_with_lease``
      - ``{status: "failed", reason}`` — any other git failure (network, auth, etc.)

    The caller is responsible for the "up-to-date / nothing to push"
    short-circuit (use ``unpushed_count`` first); this primitive always
    invokes ``git push``.
    """
    pushed_count = (
        unpushed_count(repo_path, branch) if not dry_run else 0
    )

    args = ["push"]
    if set_upstream:
        args.append("--set-upstream")
    if force_with_lease:
        args.append("--force-with-lease")
    if dry_run:
        args.append("--dry-run")
    args.append(remote)
    if branch:
        args.append(branch)

    result = subprocess.run(
        ["git"] + args,
        capture_output=True, text=True, cwd=repo_path,
    )
    if result.returncode == 0:
        out: dict[str, Any] = {
            "status": "ok",
            "pushed_count": pushed_count,
            "ref": f"{remote}/{branch}" if branch else upstream_ref(repo_path),
        }
        if set_upstream:
            out["set_upstream"] = True
        if dry_run:
            out["dry_run"] = True
        return out

    stderr = (result.stderr or "").strip()
    tail = stderr.splitlines()[-3:] if stderr else []
    reason = "\n".join(tail) or stderr or "push failed"

    # Non-fast-forward / hook rejection — git uses "rejected" or "non-fast-forward"
    if "rejected" in stderr or "non-fast-forward" in stderr:
        return {"status": "rejected", "reason": reason}
    return {"status": "failed", "reason": reason}


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

def stash_save(
    repo_path: Path, message: str = "", include_untracked: bool = False,
) -> bool:
    """Stash uncommitted changes. Returns True if anything was stashed.

    ``include_untracked=True`` adds ``-u`` so untracked files are also
    stashed (used by feature-scoped stashes where the user expects
    "everything for this feature" to disappear cleanly).
    """
    args = ["stash", "push"]
    if include_untracked:
        args.append("-u")
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
        # --no-track: see create_branch() for rationale.
        args.extend(["-b", branch, "--no-track"])
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

def commit_iso_date(repo_path: Path, ref: str = "HEAD") -> str:
    """Return the committer date of a ref as ISO 8601 (e.g. ``2026-04-25T12:34:56Z``).

    Used by the review-comment temporal filter to know how old the latest
    commit on the branch is. Returns empty string if the ref doesn't resolve.
    """
    try:
        return _run_ok(
            ["log", "-1", "--format=%cI", ref], cwd=repo_path,
        ).strip()
    except GitError:
        return ""


def commits_touching_path(
    repo_path: Path,
    ref: str,
    path: str,
    since: str | None = None,
) -> list[dict]:
    """Return commits on ``ref`` that touched ``path``, optionally since a date.

    Each entry: ``{sha, short_sha, committed_at, subject}``. Newest first.
    ``since`` should be ISO 8601; commits with committer date ``> since``
    are returned (used to ask: did anything happen after the comment?).
    """
    sep = "\x1f"
    fmt = f"%H{sep}%h{sep}%cI{sep}%s"
    args = ["log", ref, f"--format={fmt}"]
    if since:
        args.append(f"--since={since}")
    args.extend(["--", path])
    try:
        output = _run_ok(args, cwd=repo_path)
    except GitError:
        return []
    if not output:
        return []
    entries = []
    for line in output.splitlines():
        parts = line.split(sep)
        if len(parts) < 4:
            continue
        entries.append({
            "sha": parts[0],
            "short_sha": parts[1],
            "committed_at": parts[2],
            "subject": parts[3],
        })
    return entries


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
