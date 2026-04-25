"""Per-repo evacuate primitive — moves the currently-canonical feature
into a warm worktree so a different feature can take its slot in main.

This is the engine `switch` calls in active-rotation mode. Per repo, the
recipe is:

    1. ``git stash push --include-untracked``  (no-op if clean)
    2. ``git checkout`` Y in main               (caller does this)
    3. ``git worktree add`` for X at the canonical worktree path
    4. ``git stash pop`` inside the new X worktree

Note that step 2 lives in the caller because the order matters: we must
free X from main BEFORE adding a worktree on X, otherwise git refuses
("branch already checked out"). The caller orchestrates; this module
exposes the per-step helpers and a one-shot ``evacuate_repo`` for the
common case.

Wind-down mode does NOT call this module; it uses the simpler
``stash + checkout`` path with no worktree-add (X goes cold).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..git import repo as git
from ..workspace.workspace import Workspace
from .errors import BlockerError


WORKTREES_DIR = ".canopy/worktrees"


def warm_worktree_path(workspace: Workspace, feature: str, repo: str) -> Path:
    """Canonical filesystem location for a warm worktree."""
    return workspace.config.root / WORKTREES_DIR / feature / repo


def has_warm_worktree(workspace: Workspace, feature: str, repo: str) -> bool:
    """True when a warm worktree exists on disk for (feature, repo)."""
    candidate = warm_worktree_path(workspace, feature, repo)
    return candidate.exists() and (candidate / ".git").exists()


def warm_features(workspace: Workspace) -> list[str]:
    """Names of features that currently have at least one warm worktree.

    Ordering is filesystem-stable but not meaningful — callers wanting LRU
    semantics should consult ``active_feature.last_touched``.
    """
    base = workspace.config.root / WORKTREES_DIR
    if not base.exists():
        return []
    out = []
    for entry in sorted(base.iterdir()):
        if entry.is_dir():
            for sub in entry.iterdir():
                if sub.is_dir() and (sub / ".git").exists():
                    out.append(entry.name)
                    break
    return out


def stash_for_evacuation(
    workspace: Workspace, feature: str, repo: str, repo_path: Path,
) -> str | None:
    """Stash the repo's dirty state with the canopy feature tag.

    Returns the stash ref if a stash was created, None if the tree was
    already clean. Tag format matches P12: ``[canopy <feature> @ <ts>] <msg>``
    so the stash can be popped automatically when the feature is warmed
    again later.
    """
    if not git.is_dirty(repo_path):
        return None
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    msg = f"[canopy {feature} @ {ts}] auto-evacuated from main"
    git.stash_save(repo_path, msg, include_untracked=True)
    return _latest_stash_ref(repo_path)


def add_warm_worktree(
    workspace: Workspace, feature: str, repo: str, repo_path: Path,
) -> Path:
    """Create the warm worktree dir for X, checking out X's branch into it.

    Caller must have already moved main off branch X (otherwise git refuses).
    Returns the new worktree's absolute path.
    """
    dest = warm_worktree_path(workspace, feature, repo)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        # Leftover from a previous failed run. Better to refuse than silently
        # overwrite — caller can inspect / clean up.
        raise BlockerError(
            code="warm_worktree_path_occupied",
            what=f"path already exists: {dest}",
            details={"feature": feature, "repo": repo, "path": str(dest)},
        )
    # branch always exists at this point — caller verified during preflight
    # and just checked it out in main, so worktree_add must NOT pass -b.
    git.worktree_add(repo_path, dest, feature, create_branch=False)
    return dest.resolve()


def pop_into_worktree(
    worktree_path: Path, has_stash: bool,
) -> bool:
    """Pop the latest stash (index 0) inside the new worktree.

    No-op when ``has_stash=False``. Index 0 is correct here because
    nothing between ``stash_for_evacuation`` and this call creates a
    new stash, so the one we just pushed is still on top.
    """
    if not has_stash:
        return False
    git.stash_pop(worktree_path, 0)
    return True


def evacuate_repo(
    workspace: Workspace,
    feature_being_evacuated: str,
    repo_name: str,
    repo_path: Path,
    *,
    target_branch: str,
    target_branch_checkout: bool = True,
) -> dict[str, Any]:
    """One-shot: stash → checkout target → add worktree on evacuated branch → pop.

    Args:
        feature_being_evacuated: the feature name losing its canonical slot
            (its branch will be moved to a warm worktree).
        repo_name: repo identifier in canopy config.
        repo_path: absolute path of the repo's main checkout.
        target_branch: branch to leave checked out in main after evacuation.
        target_branch_checkout: if False, skip the ``git checkout target_branch``
            step (caller has already done it). Default True.

    Returns ``{repo, status, stashed, stash_ref?, worktree_path,
    target_branch}``. Raises ``BlockerError`` on any failure (PR2 will
    add per-step rollback; PR1 surfaces the partial state).
    """
    stash_ref = stash_for_evacuation(
        workspace, feature_being_evacuated, repo_name, repo_path,
    )
    if target_branch_checkout:
        git.checkout(repo_path, target_branch)
    new_wt = add_warm_worktree(
        workspace, feature_being_evacuated, repo_name, repo_path,
    )
    popped = pop_into_worktree(new_wt, has_stash=stash_ref is not None)
    return {
        "repo": repo_name,
        "status": "evacuated",
        "stashed": stash_ref is not None,
        "stash_ref": stash_ref,
        "worktree_path": str(new_wt),
        "target_branch": target_branch,
        "popped": popped,
    }


def _latest_stash_ref(repo_path: Path) -> str:
    """Return ``stash@{0}`` after a fresh stash push (always position 0)."""
    return "stash@{0}"
