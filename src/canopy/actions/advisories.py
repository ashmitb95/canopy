"""Observe-as-advisory: surface (never enforce) registry/disk drift.

Compares each repo's live current branch against the active feature's
registry. A repo NOT registered to the active feature but sitting on the
feature's expected branch is a 'join candidate' — the agent likely created
the branch with raw git and forgot ``canopy join``. Pure local read; never
mutates, never blocks.
"""
from __future__ import annotations

from typing import Any

from ..workspace.workspace import Workspace


def compute_advisories(workspace: Workspace, active_feature: str | None) -> list[dict[str, Any]]:
    if not active_feature:
        return []
    from .aliases import repos_for_feature
    from ..git import repo as git

    registered = set((repos_for_feature(workspace, active_feature) or {}).keys())
    out: list[dict[str, Any]] = []
    for rs in workspace.repos:
        if rs.config.name in registered or not rs.abs_path.exists():
            continue
        try:
            cur = git.current_branch(rs.abs_path)
        except Exception:
            continue
        if cur == active_feature:
            out.append({
                "code": "unregistered_join_candidate",
                "repo": rs.config.name,
                "branch": cur,
                "message": (f"{rs.config.name} is on '{cur}' (matches the active "
                            f"feature '{active_feature}') but isn't registered — "
                            f"`canopy join {rs.config.name}`, or ignore if scratch."),
            })
    try:
        from . import reclaim
        out.extend(reclaim.reclaimable_advisories(workspace))
    except Exception:
        pass
    return out
