"""switch — the canonical-slot focus primitive.

`switch(Y)` promotes Y to the canonical slot (main checkout). Whatever was
canonical before either:

  - **Active rotation (default)**: evacuates to a warm worktree at
    ``.canopy/worktrees/<previous>/<repo>/`` so it stays close at hand.
  - **Wind-down (``release_current=True``)**: goes cold (just the branch +
    a feature-tagged stash if there were dirty changes). Use when the
    previous focus is parked / finished and Y is the new focus.

Per-repo recipe per mode is in ``evacuate.py`` (active-rotation) and
inline below (wind-down). Cap-reached failures surface via
``switch_preflight.py`` as a structured ``BlockerError`` with explicit
fix actions — no silent eviction.

PR1 scope: the canonical-slot behavior end-to-end with preflight as the
primary safety net. PR2 adds journal + rollback walker for the residual
mid-op failures. PR3 adds the fast-path 3-checkout swap when both X and
Y already have homes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..git import repo as git
from ..workspace.workspace import Workspace
from . import active_feature as af
from . import evacuate as evac
from . import switch_preflight as preflight
from .aliases import resolve_feature, repos_for_feature
from .errors import BlockerError, FixAction


def switch(
    workspace: Workspace,
    feature: str,
    *,
    release_current: bool = False,
    no_evict: bool = False,
    evict: str | None = None,
) -> dict[str, Any]:
    """Promote ``feature`` to the canonical slot.

    Args:
        feature: feature alias (resolved via the alias layer). Accepts a
            fresh name too — branches are created from default if missing.
        release_current: wind-down mode. Previously-canonical feature goes
            cold (just stashed if dirty), no warm worktree created.
        no_evict: in active-rotation mode, refuse to evict an LRU warm
            worktree when the cap would fire. Returns a cap-reached
            BlockerError instead. Default False (canopy auto-picks LRU).
        evict: explicit feature name to evict from warm to cold instead of
            the LRU pick. Used when the user wants control after a
            cap-reached blocker surfaced an LRU candidate.

    Returns ``{feature, mode, per_repo_paths, previously_canonical?,
    evacuation?, eviction?, branches_created?, migration?}``.
    """
    feature_name = resolve_feature_safely(workspace, feature)

    # Lazy migration — populate last_touched/active state on first switch
    # in a workspace that was on canopy < 2.9.
    migration_info = _maybe_migrate(workspace)

    repo_branches = repos_for_feature(workspace, feature_name)
    if not repo_branches:
        # Permit fresh feature names (will create branches from default)
        repo_branches = {r.config.name: feature_name for r in workspace.repos}

    pre = preflight.preflight(
        workspace, feature_name, repo_branches,
        release_current=release_current,
        no_evict=no_evict and (evict is None),
    )

    out: dict[str, Any] = {"feature": feature_name}
    if migration_info:
        out["migration"] = migration_info
    previously_canonical = pre["previously_canonical"]
    if previously_canonical:
        out["previously_canonical"] = previously_canonical

    # Step A: optional eviction (active-rotation cap fire) —
    # explicit ``evict=<feature>`` overrides preflight's LRU pick.
    eviction_info: dict[str, Any] | None = None
    eviction_target: str | None = None
    if not release_current:
        if evict:
            eviction_target = evict
        elif pre["cap_will_fire"] and pre["lru_eviction_candidate"]:
            eviction_target = pre["lru_eviction_candidate"]
        if eviction_target:
            eviction_info = _evict_warm_to_cold(workspace, eviction_target)
            out["eviction"] = eviction_info

    # Step B: branches that need creating from default
    if pre["branches_to_create"]:
        out["branches_created"] = _create_missing_branches(
            workspace, pre["branches_to_create"],
        )

    # Step C: per-repo per-mode work
    per_repo_results: list[dict[str, Any]] = []
    new_canonical_paths: dict[str, str] = {}

    for repo_name, target_branch in repo_branches.items():
        try:
            state = workspace.get_repo(repo_name)
        except KeyError:
            continue
        repo_path = state.abs_path

        # If main is already on the target branch, nothing to do for this
        # repo aside from recording its path.
        try:
            current = git.current_branch(repo_path)
        except git.GitError:
            current = None
        new_canonical_paths[repo_name] = str(repo_path.resolve())
        if current == target_branch:
            per_repo_results.append({
                "repo": repo_name, "status": "noop",
                "reason": "already on target branch",
            })
            continue

        # If Y is currently warm in this repo, the warm worktree is
        # holding the branch — must remove it before main can check out Y.
        if evac.has_warm_worktree(workspace, feature_name, repo_name):
            wt_path = evac.warm_worktree_path(workspace, feature_name, repo_name)
            # Refuse if the warm worktree has uncommitted work — that
            # would silently disappear. User must commit/stash first.
            if git.is_dirty(wt_path):
                raise BlockerError(
                    code="warm_worktree_dirty_on_promote",
                    what=(
                        f"warm worktree {wt_path} has uncommitted changes;"
                        f" can't promote {feature_name} to canonical without"
                        f" losing them"
                    ),
                    details={"feature": feature_name, "repo": repo_name,
                             "worktree_path": str(wt_path)},
                    fix_actions=[
                        FixAction(
                            action="commit",
                            args={"feature": feature_name},
                            safe=False,
                            preview=f"commit dirty changes in {wt_path}",
                        ),
                        FixAction(
                            action="stash_save_feature",
                            args={"feature": feature_name},
                            safe=True,
                            preview=f"stash dirty changes in {wt_path}",
                        ),
                    ],
                )
            git.worktree_remove(repo_path, wt_path)

        # Mode A: wind-down — stash X dirty into a feature-tagged stash on
        # X's branch, then plain checkout Y in main. No worktree-add for X.
        if release_current and previously_canonical and current == _branch_for_in_repo(
            workspace, previously_canonical, repo_name,
        ):
            stash_ref = _stash_for_winddown(
                workspace, previously_canonical, repo_path,
            )
            git.checkout(repo_path, target_branch)
            per_repo_results.append({
                "repo": repo_name, "status": "wind_down_then_checkout",
                "previous_branch": _branch_for_in_repo(
                    workspace, previously_canonical, repo_name,
                ),
                "target_branch": target_branch,
                "stashed": stash_ref is not None,
                "stash_ref": stash_ref,
            })
            continue

        # Mode B: active rotation — evacuate X to warm if main is on X.
        if (
            previously_canonical
            and not release_current
            and current == _branch_for_in_repo(
                workspace, previously_canonical, repo_name,
            )
        ):
            result = evac.evacuate_repo(
                workspace, previously_canonical, repo_name, repo_path,
                target_branch=target_branch,
            )
            per_repo_results.append(result)
            continue

        # Fallback: main is on something else (or not on previous_canonical).
        # Just stash + checkout.
        if git.is_dirty(repo_path):
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            current_label = current or "(detached)"
            git.stash_save(
                repo_path,
                f"[canopy {current_label} @ {ts}] auto-stash on switch",
                include_untracked=True,
            )
            stashed = True
        else:
            stashed = False
        git.checkout(repo_path, target_branch)
        per_repo_results.append({
            "repo": repo_name, "status": "checkout",
            "previous_branch": current,
            "target_branch": target_branch,
            "stashed": stashed,
        })

    out["mode"] = "wind_down" if release_current else "active_rotation"
    out["per_repo"] = per_repo_results
    out["per_repo_paths"] = new_canonical_paths

    # Persist the new canonical state. last_touched bumps both Y (now) and
    # the previously-canonical X (so its warm slot has fresh recency).
    touched: list[str] = []
    if previously_canonical:
        touched.append(previously_canonical)
    entry = af.write_active(
        workspace, feature_name, new_canonical_paths,
        touched_features=touched,
    )
    out["activated_at"] = entry.activated_at
    if entry.previous_feature:
        out["previous_feature_in_state"] = entry.previous_feature

    return out


def resolve_feature_safely(workspace: Workspace, feature: str) -> str:
    """Like ``resolve_feature`` but accepts a fresh feature name as a
    fallback. Switch is allowed to invent new feature lanes if the user
    types a name that doesn't exist yet."""
    try:
        return resolve_feature(workspace, feature)
    except BlockerError as e:
        if e.code in ("unknown_alias", "ambiguous_alias"):
            return feature
        raise


# ── eviction (warm → cold) ──────────────────────────────────────────────

def _evict_warm_to_cold(
    workspace: Workspace, feature: str,
) -> dict[str, Any]:
    """Park a warm feature back to cold. Auto-stash any dirty work first.

    For each repo whose warm worktree exists for this feature:
      1. If the worktree is dirty, stash with feature tag.
      2. ``git worktree remove`` the worktree dir.
      3. The branch stays — feature is now cold.

    Returns ``{feature, repos: [{repo, stashed, stash_ref?, removed}]}``.
    """
    repo_results: list[dict[str, Any]] = []
    for state in workspace.repos:
        repo_name = state.config.name
        wt_path = evac.warm_worktree_path(workspace, feature, repo_name)
        if not (wt_path.exists() and (wt_path / ".git").exists()):
            continue
        stash_ref: str | None = None
        if git.is_dirty(wt_path):
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            git.stash_save(
                wt_path,
                f"[canopy {feature} @ {ts}] auto-evicted",
                include_untracked=True,
            )
            stash_ref = "stash@{0}"
        git.worktree_remove(state.abs_path, wt_path)
        repo_results.append({
            "repo": repo_name,
            "stashed": stash_ref is not None,
            "stash_ref": stash_ref,
            "removed": True,
        })
    return {"feature": feature, "repos": repo_results}


# ── wind-down stash helper ──────────────────────────────────────────────

def _stash_for_winddown(
    workspace: Workspace, feature: str, repo_path: Path,
) -> str | None:
    """Stash dirty work in main for a feature being wound down (cold).

    Tag matches P12 so future ``switch(feature)`` (warming) auto-finds it.
    """
    if not git.is_dirty(repo_path):
        return None
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    git.stash_save(
        repo_path,
        f"[canopy {feature} @ {ts}] released to cold",
        include_untracked=True,
    )
    return "stash@{0}"


# ── helpers ─────────────────────────────────────────────────────────────

def _branch_for_in_repo(
    workspace: Workspace, feature: str, repo_name: str,
) -> str:
    """Return the branch name for ``feature`` in ``repo_name``.

    Honors the lane's ``branches`` map for per-repo branch overrides
    (e.g. doc-3010 in api vs DOC-3010-v2 in ui)."""
    from ..features.coordinator import FeatureCoordinator
    coord = FeatureCoordinator(workspace)
    try:
        lane = coord.status(feature)
    except Exception:
        return feature
    return lane.branch_for(repo_name)


def _create_missing_branches(
    workspace: Workspace, items: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Create each missing branch from the repo's default branch.

    Returns per-repo ``[{repo, branch, base, created_from_sha}]``.
    """
    out = []
    for repo_name, branch in items:
        try:
            state = workspace.get_repo(repo_name)
        except KeyError:
            continue
        base = state.config.default_branch
        base_sha = git.sha_of(state.abs_path, base) or ""
        # --no-track is the right call here (see git/repo.py:create_branch).
        git.create_branch(state.abs_path, branch, start_point=base)
        out.append({
            "repo": repo_name, "branch": branch,
            "base": base, "created_from_sha": base_sha,
        })
    return out


# ── lazy 2.9 migration ──────────────────────────────────────────────────

def _maybe_migrate(workspace: Workspace) -> dict[str, Any] | None:
    """First-touch migration for pre-2.9 workspaces.

    Detection: ``active_feature.json`` is missing OR the existing entry
    has no ``last_touched`` field (older schema). When detected, populate
    state from current filesystem reality WITHOUT forcing eviction —
    everything not currently canonical is left wherever it lives (warm
    if a worktree exists, cold otherwise). Returns a small report dict
    if migration ran, None otherwise.
    """
    current = af.read_active(workspace)
    if current is not None and current.last_touched:
        return None  # already on 2.9 schema

    # Identify the canonical feature: the branch currently checked out
    # in the main checkout of the first canopy-managed repo, IF any
    # known feature lane matches.
    from ..features.coordinator import FeatureCoordinator
    coord = FeatureCoordinator(workspace)
    try:
        lanes = coord.list_active()
    except Exception:
        lanes = []
    lane_names = {lane.name for lane in lanes}

    canonical: str | None = None
    if workspace.repos:
        try:
            head_branch = git.current_branch(workspace.repos[0].abs_path)
            if head_branch in lane_names:
                canonical = head_branch
        except git.GitError:
            pass

    # Initial last_touched: bump every active lane to lane.created_at if
    # available; canonical (if any) gets now.
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    last_touched: dict[str, str] = {}
    for lane in lanes:
        ts = lane.created_at or now
        last_touched[lane.name] = ts
    if canonical:
        last_touched[canonical] = now

    if canonical:
        per_repo_paths = {
            r.config.name: str(r.abs_path.resolve()) for r in workspace.repos
        }
        af.write_active(
            workspace, canonical, per_repo_paths,
            touched_features=list(last_touched.keys()),
        )
        return {
            "ran": True, "canonical_detected": canonical,
            "lanes_indexed": sorted(lane_names),
        }

    # No canonical detected — initialize empty active state but with the
    # last_touched map seeded so the next real switch has LRU data.
    if last_touched and current is None:
        # Write a placeholder entry where feature is empty? No — write_active
        # requires a feature. Just record the seed in a synthetic state so
        # future switches benefit.
        # For PR1, skip this case — first real switch will populate it.
        pass
    return {"ran": True, "canonical_detected": None, "lanes_indexed": sorted(lane_names)}
