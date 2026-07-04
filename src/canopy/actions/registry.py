"""The context registry read — canopy's single source of truth for the agent.

Tier 1 (default, ZERO network): workspace + per-feature repo/branch/path +
local git state + slots + advisories + cwd-detected position. Authoritative
for "where am I / what's my code state". Tier 2 (remote=True) adds the live
PR + CI + origin-divergence overlay — see ``_remote_overlay``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..workspace.workspace import Workspace


def _detected(workspace: Workspace, cwd: Path | None) -> dict[str, Any]:
    """cwd → {repo, feature} (absorbs the old debug `context`)."""
    out: dict[str, Any] = {"cwd": str(cwd) if cwd else None,
                           "repo": None, "feature": None}
    if cwd is None:
        return out
    cwd = Path(cwd).resolve()
    for rs in workspace.repos:
        root = rs.abs_path.resolve()
        if cwd == root or root in cwd.parents:
            out["repo"] = rs.config.name
            try:
                from ..git import repo as git
                out["feature"] = git.current_branch(root)
            except Exception:
                pass
            break
    return out


def _local_feature(workspace: Workspace, feature: str) -> dict[str, Any]:
    from .aliases import repos_for_feature
    from ..git import repo as git

    repos: dict[str, Any] = {}
    for repo_name, branch in (repos_for_feature(workspace, feature) or {}).items():
        try:
            rs = workspace.get_repo(repo_name)
        except KeyError:
            continue
        entry: dict[str, Any] = {"branch": branch, "path": str(rs.abs_path)}
        if rs.abs_path.exists():
            try:
                entry["current_branch"] = git.current_branch(rs.abs_path)
                entry["dirty"] = git.is_dirty(rs.abs_path)
                entry["dirty_count"] = git.dirty_file_count(rs.abs_path)
                base = rs.config.default_branch
                if git.branch_exists(rs.abs_path, branch):
                    a, b = git.divergence(rs.abs_path, branch, base)
                    entry["ahead_local"], entry["behind_local"] = a, b
            except Exception:
                pass
        repos[repo_name] = entry
    return {"repos": repos}


def _compute_advisories(workspace: Workspace, active_feature):
    # Replaced in Task 5 by a direct import of advisories.compute_advisories.
    try:
        from .advisories import compute_advisories
        return compute_advisories(workspace, active_feature)
    except ImportError:
        return []


def _remote_overlay(workspace: Workspace, out: dict, author: str) -> None:
    # Replaced in Task 4 with the real live-fetch overlay.
    pass


def context(workspace: Workspace, *, cwd: Path | None = None,
            remote: bool = False, author: str = "@me") -> dict[str, Any]:
    """Assemble the registry. Tier 1 always; Tier 2 when ``remote=True``."""
    from . import slots as slots_mod
    from . import active as active_mod
    from ..features.coordinator import FeatureCoordinator

    state = slots_mod.read_state(workspace)
    canonical = state.canonical.feature if state and state.canonical else None
    active_feat = canonical or active_mod.get_active(workspace)

    features_raw = FeatureCoordinator(workspace)._load_features()
    features: dict[str, Any] = {}
    for name, data in (features_raw or {}).items():
        if data.get("status", "active") != "active":
            continue
        feat = _local_feature(workspace, name)
        linear = None
        if data.get("linear_issue"):
            linear = {"id": data.get("linear_issue"),
                      "title": data.get("linear_title", ""),
                      "url": data.get("linear_url", "")}
        feat["linear"] = linear
        features[name] = feat

    out: dict[str, Any] = {
        "workspace": {"name": workspace.config.name,
                      "root": str(workspace.config.root),
                      "active_feature": active_feat},
        "features": features,
        "slots": {sid: e.feature for sid, e in (state.slots.items() if state else [])},
        "advisories": _compute_advisories(workspace, active_feat),
        "detected": _detected(workspace, cwd),
    }
    if remote:
        _remote_overlay(workspace, out, author)
    return out
