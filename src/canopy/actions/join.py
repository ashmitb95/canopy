"""canopy join <repo> — the explicit lazy-growth primitive.

Creates (or adopts) the active feature's branch in <repo>'s trunk checkout,
registers the repo in features.json, and promotes the feature to
slots.canonical (so the enforcement gate recognizes commits there). Raw
`git checkout -b` does NOT join — only this does.
"""
from __future__ import annotations

from typing import Any

from ..workspace.workspace import Workspace
from .errors import BlockerError


def join(workspace: Workspace, repo: str) -> dict[str, Any]:
    from . import active as active_mod
    from . import slots as slots_mod
    from ..features.coordinator import FeatureCoordinator
    from ..git import repo as git

    state = slots_mod.read_state(workspace)
    feature = (state.canonical.feature if state and state.canonical
               else active_mod.get_active(workspace))
    if not feature:
        raise BlockerError(code="no_active_feature",
                           what="no active feature — run `canopy start <alias>` first")
    try:
        rs = workspace.get_repo(repo)
    except KeyError:
        raise BlockerError(code="unknown_repo", what=f"unknown repo '{repo}'")

    coord = FeatureCoordinator(workspace)
    features = coord._load_features()
    entry = features.setdefault(feature, {"repos": [], "status": "active"})
    already = repo in (entry.get("repos") or [])

    # Create the branch off default_branch unless it already exists (adopt).
    try:
        if not git.branch_exists(rs.abs_path, feature):
            git.create_branch(rs.abs_path, feature, start_point=rs.config.default_branch)
        git.checkout(rs.abs_path, feature)
    except git.GitError as ex:
        raise BlockerError(
            code="join_failed",
            what=f"could not create/checkout branch '{feature}' in {repo}: {ex}",
        )

    if not already:
        entry.setdefault("repos", [])
        if repo not in entry["repos"]:
            entry["repos"].append(repo)
        features[feature] = entry
        coord._save_features(features)

    # Promote to canonical so the gate recognizes this checkout — PRESERVE slots.
    state = state or slots_mod.SlotState(slot_count=workspace.config.slots)
    paths = {}
    if state.canonical and state.canonical.feature == feature:
        paths = dict(state.canonical.per_repo_paths)
    paths[repo] = str(rs.abs_path)
    state.canonical = slots_mod.CanonicalEntry(
        feature=feature, activated_at=slots_mod.now_iso(), per_repo_paths=paths)
    slots_mod.write_state(workspace, state)
    active_mod.set_active(workspace, feature)

    return {"feature": feature, "repo": repo,
            "status": "already_joined" if already else "joined",
            "branch": feature}
