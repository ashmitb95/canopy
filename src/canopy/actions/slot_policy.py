"""Warm-vs-cold policy for a feature vacating trunk.

WARM iff the feature has an open PR (it's being shepherded) OR live WIP
(uncommitted work worth keeping instant-to-return-to). Else COLD. The PR
signal is the cached registry (prs_cache) — a stale signal is acceptable
here (worst case: a slot kept warm slightly too long, freed at reclaim).
"""
from __future__ import annotations

from ..workspace.workspace import Workspace


def _has_open_pr(workspace: Workspace, feature: str) -> bool:
    from . import prs_cache
    cached = prs_cache.read(workspace)
    if not cached:
        return False
    repos = (cached.get("features", {}).get(feature) or {}).get("repos", {})
    return any((r or {}).get("state") == "open" for r in repos.values())


def _has_live_wip(workspace: Workspace, feature: str) -> bool:
    from .aliases import repos_for_feature
    from ..git import repo as git
    for repo_name, branch in (repos_for_feature(workspace, feature) or {}).items():
        try:
            rs = workspace.get_repo(repo_name)
        except KeyError:
            continue
        if not rs.abs_path.exists():
            continue
        try:
            if git.current_branch(rs.abs_path) == branch and git.is_dirty(rs.abs_path):
                return True
        except Exception:
            continue
    return False


def warm_or_cold(workspace: Workspace, feature: str) -> str:
    """Return "warm" or "cold" for a feature leaving trunk."""
    if _has_open_pr(workspace, feature) or _has_live_wip(workspace, feature):
        return "warm"
    return "cold"
