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
    from .advisories import compute_advisories
    return compute_advisories(workspace, active_feature)


def _remote_overlay(workspace: Workspace, out: dict, author: str) -> None:
    """Merge live PR data into per-repo entries; cache fallback if offline."""
    from . import triage as triage_mod
    from . import prs_cache
    from .aliases import _resolve_owner_slug
    from ..git import repo as git
    from ..integrations import github as gh

    repo_names = list({r for f in out["features"].values() for r in f["repos"]})
    stale = False
    fetched_at = None
    try:
        prs_by_repo = triage_mod._fetch_open_prs(workspace, repo_names, author)
        idx: dict[tuple[str, str], dict] = {}
        for repo_name, prs in prs_by_repo.items():
            for pr in prs:
                b = pr.get("head_branch") or ""
                if b:
                    idx[(repo_name, b)] = pr
        live_by_feature: dict = {}
        for fname, fdata in out["features"].items():
            live_by_feature[fname] = {"repos": {}}
            for repo_name, entry in fdata["repos"].items():
                pr = idx.get((repo_name, entry["branch"]))
                if pr:
                    slim = {"number": pr.get("number"), "state": pr.get("state"),
                            "review_decision": pr.get("review_decision"),
                            "url": pr.get("url")}
                    # CI check rollup — best-effort; a failure here (e.g. an
                    # unparseable remote) must not take down the whole PR
                    # overlay, so it's caught locally rather than bubbling
                    # to the outer stale-fallback handler.
                    try:
                        owner, slug = _resolve_owner_slug(workspace, repo_name)
                        rollup, _raw = gh.get_pr_checks(
                            workspace.config.root, owner, slug, slim["number"],
                        )
                        slim["checks_summary"] = {
                            "status": rollup.get("status"),
                            "passed": rollup.get("passed"),
                            "failing": rollup.get("failing"),
                            "pending": rollup.get("pending"),
                        }
                    except Exception:
                        pass
                    entry["pr"] = slim
                    live_by_feature[fname]["repos"][repo_name] = slim
        prs_cache.write(workspace, live_by_feature)
    except Exception:
        stale = True
        cached = prs_cache.read(workspace)
        if cached:
            fetched_at = cached.get("fetched_at")
            for fname, fdata in out["features"].items():
                cf = (cached["features"].get(fname) or {}).get("repos", {})
                for repo_name, entry in fdata["repos"].items():
                    if repo_name in cf:
                        entry["pr"] = cf[repo_name]
    # origin divergence is remote-only (needs the last fetch's tracking ref)
    for fdata in out["features"].values():
        for repo_name, entry in fdata["repos"].items():
            try:
                rs = workspace.get_repo(repo_name)
                base = f"origin/{rs.config.default_branch}"
                if git.branch_exists(rs.abs_path, entry["branch"]):
                    a, b = git.divergence(rs.abs_path, entry["branch"], base)
                    entry["ahead_origin"], entry["behind_origin"] = a, b
            except Exception:
                pass
    out["remote"] = {"stale": stale, "fetched_at": fetched_at}


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
