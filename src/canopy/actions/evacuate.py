"""Per-repo evacuate primitive — moves the currently-canonical feature
into a warm slot worktree so a different feature can take its slot in main.

This is the engine ``switch`` calls in active-rotation mode. Per repo, the
recipe is:

    1. ``git stash push --include-untracked``  (no-op if clean)
    2. ``git checkout target_branch`` in main  (caller passes target)
    3. ``git worktree add slot_path feature``
    4. ``git stash pop`` inside the new slot

``fastpath_swap_repo`` is the 5-op active-rotation fast path: Y is already
warm in a slot; X is canonical in main → swap them without a full cold
round-trip.

    1. stash X dirty
    2. checkout default_branch in main         (frees X)
    3. checkout x_feature in slot_id worktree  (slot adopts X)
    4. checkout y_feature in main              (main adopts Y)
    5. pop stash inside slot_id (X's dirty work)

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
from . import slots as slots_mod


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
    slot_id: str,
    target_branch: str,
    target_branch_checkout: bool = True,
) -> dict[str, Any]:
    """Move ``feature_being_evacuated`` (currently in main) into ``slot_id``.

    Per-repo recipe (cold-Y / first-time evacuation):
      1. stash X dirty
      2. checkout target_branch in main
      3. ``git worktree add slot_path X``
      4. pop into the new slot

    Args:
        feature_being_evacuated: the feature name losing its canonical slot
            (its branch will be moved into slot_id).
        repo_name: repo identifier in canopy config.
        repo_path: absolute path of the repo's main checkout.
        slot_id: the slot identifier to place the evacuated feature in
            (e.g. ``"worktree-1"``).
        target_branch: branch to leave checked out in main after evacuation.
        target_branch_checkout: if False, skip the ``git checkout target_branch``
            step (caller has already done it). Default True.

    Returns ``{repo, status, stashed, stash_ref, worktree_path, slot_id,
    target_branch, popped}``. Raises ``BlockerError`` on failure.
    """
    stash_ref = stash_for_evacuation(
        workspace, feature_being_evacuated, repo_name, repo_path,
    )
    if target_branch_checkout:
        git.checkout(repo_path, target_branch)
    dest = slots_mod.slot_worktree_path(workspace, slot_id, repo_name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise BlockerError(
            code="slot_worktree_path_occupied",
            what=f"path already exists: {dest}",
            details={
                "feature": feature_being_evacuated,
                "repo": repo_name,
                "slot": slot_id,
                "path": str(dest),
            },
        )
    git.worktree_add(repo_path, dest, feature_being_evacuated, create_branch=False)
    popped = pop_into_worktree(dest.resolve(), has_stash=stash_ref is not None)
    return {
        "repo": repo_name,
        "status": "evacuated",
        "stashed": stash_ref is not None,
        "stash_ref": stash_ref,
        "worktree_path": str(dest.resolve()),
        "slot_id": slot_id,
        "target_branch": target_branch,
        "popped": popped,
    }


def fastpath_swap_repo(
    workspace: Workspace,
    *,
    x_feature: str,
    y_feature: str,
    repo_name: str,
    repo_path: Path,
    slot_id: str,
    default_branch: str,
) -> dict[str, Any]:
    """5-op fast-path: Y warm in slot_id, X canonical → swap them.

    Steps:
      1. stash X dirty (tagged with X)
      2. checkout default_branch in main      (frees X)
      3. checkout x_feature in slot_id wt    (slot adopts X)
      4. checkout y_feature in main           (main adopts Y)
      5. pop stash inside slot_id (X's dirty work)

    Args:
        x_feature: the feature currently canonical in main (being evacuated).
        y_feature: the feature currently warm in slot_id (being promoted).
        repo_name: repo identifier in canopy config.
        repo_path: absolute path of the repo's main checkout.
        slot_id: slot currently holding Y; after swap, holds X.
        default_branch: neutral branch used as a stepping stone to free X.

    Returns ``{repo, status, stashed, stash_ref, worktree_path, slot_id,
    swapped_in, swapped_out, popped}``.
    """
    slot_path = slots_mod.slot_worktree_path(workspace, slot_id, repo_name)
    if not (slot_path / ".git").exists():
        raise BlockerError(
            code="fastpath_slot_missing",
            what=f"slot {slot_id} has no worktree at {slot_path}",
            details={"slot": slot_id, "expected_path": str(slot_path)},
        )

    stash_ref = stash_for_evacuation(workspace, x_feature, repo_name, repo_path)
    git.checkout(repo_path, default_branch)
    git.checkout(slot_path, x_feature)
    git.checkout(repo_path, y_feature)
    popped = pop_into_worktree(slot_path, has_stash=stash_ref is not None)
    return {
        "repo": repo_name,
        "status": "fastpath_swapped",
        "stashed": stash_ref is not None,
        "stash_ref": stash_ref,
        "worktree_path": str(slot_path.resolve()),
        "slot_id": slot_id,
        "swapped_in": y_feature,
        "swapped_out": x_feature,
        "popped": popped,
    }


def _latest_stash_ref(repo_path: Path) -> str:
    """Return ``stash@{0}`` after a fresh stash push (always position 0)."""
    return "stash@{0}"
