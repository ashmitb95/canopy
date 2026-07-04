"""Reclaim-as-vacate: free a warm slot when its PR is merged.

Slots are generic reusable dirs. Reclaim = checkout base + drop the
slots.json entry (slot returns to the free pool; dir + warm deps persist).
Clean worktree only; a dirty merged slot is surfaced as an advisory and
left untouched. Detection is passive (reads prs_cache — no network here).
"""
from __future__ import annotations

from typing import Any

from ..workspace.workspace import Workspace


def _merged(workspace: Workspace, feature: str) -> bool:
    from . import prs_cache
    cached = prs_cache.read(workspace)
    if not cached:
        return False
    repos = (cached.get("features", {}).get(feature) or {}).get("repos", {})
    states = [(r or {}).get("state") for r in repos.values()]
    return bool(states) and all(s in ("merged", "closed") for s in states)


def _dirty_repo(workspace: Workspace, sid: str, feature: str):
    """Return (repo_paths, dirty_repo_or_None) for the feature's slot worktrees."""
    from . import slots as sm
    from .aliases import repos_for_feature
    from ..git import repo as git
    repo_paths = {}
    dirty = None
    for repo_name in (repos_for_feature(workspace, feature) or {}):
        wt = sm.slot_worktree_path(workspace, sid, repo_name)
        if not (wt / ".git").exists():
            continue
        repo_paths[repo_name] = wt
        try:
            if git.is_dirty(wt):
                dirty = repo_name
                break
        except Exception:
            dirty = repo_name
            break
    return repo_paths, dirty


def reclaimable_advisories(workspace: Workspace) -> list[dict[str, Any]]:
    """READ-ONLY: list merged-but-dirty warm slots (no vacate side effects)."""
    from . import slots as sm
    state = sm.read_state(workspace)
    if state is None:
        return []
    out = []
    for sid, entry in state.slots.items():
        feature = entry.feature
        if not _merged(workspace, feature):
            continue
        _, dirty = _dirty_repo(workspace, sid, feature)
        if dirty:
            out.append({
                "code": "reclaimable_but_dirty", "feature": feature, "slot": sid,
                "message": (f"{feature}'s PR is merged but slot {sid} ({dirty}) "
                            f"has uncommitted changes — resolve before it frees."),
            })
    return out


def reclaim_merged(workspace: Workspace) -> dict[str, Any]:
    """Free every warm slot whose feature's PR(s) are all merged/closed and
    whose worktree is clean. Returns {freed:[...], advisories:[...]}."""
    from . import slots as sm
    from ..git import repo as git

    state = sm.read_state(workspace)
    if state is None:
        return {"freed": [], "advisories": []}
    freed: list[str] = []
    advisories: list[dict] = []
    for sid, entry in list(state.slots.items()):
        feature = entry.feature
        if not _merged(workspace, feature):
            continue
        repo_paths, dirty = _dirty_repo(workspace, sid, feature)
        if dirty:
            advisories.append({
                "code": "reclaimable_but_dirty", "feature": feature, "slot": sid,
                "message": (f"{feature}'s PR is merged but slot {sid} ({dirty}) "
                            f"has uncommitted changes — resolve before it frees."),
            })
            continue
        for repo_name, wt in repo_paths.items():
            base = workspace.get_repo(repo_name).config.default_branch
            try:
                git.checkout(wt, base)
            except Exception:
                pass
        state = sm.read_state(workspace)     # re-read; drop entry; preserve rest
        state.slots.pop(sid, None)
        state.last_touched.pop(feature, None)
        sm.write_state(workspace, state)
        freed.append(feature)
    return {"freed": freed, "advisories": advisories}
