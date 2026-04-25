"""Preflight for ``switch`` — predictable-failure detection without state mutation.

Catches the classes of failure that are knowable from the current
filesystem + git state alone:

  - target branch missing in any repo (and not creatable from default)
  - leftover warm-worktree directory from a previous failed run
  - git index lock currently held in any participating repo
  - cap reached + no fix path acceptable (active-rotation past warm cap)

Returns ``None`` when everything checks out; raises a structured
``BlockerError`` with all detected issues otherwise. Bundling per-repo
failures into one error means the user sees the full picture in one
shot instead of fixing one issue at a time.

Defense-in-depth: preflight catches ~80% of failures cheaply. The rest
(disk fills mid-op, network blip during fetch, IDE racing the checkout)
need the rollback walker — that's PR2.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..git import repo as git
from ..workspace.workspace import Workspace
from . import active_feature as af
from .errors import BlockerError, FixAction
from .evacuate import warm_features, warm_worktree_path


# Default cap when max_worktrees is unset (0 = legacy unlimited for the
# explicit worktree_create path; switch's canonical-slot logic interprets
# 0 as the new default of 2 for warm-slot management). See
# docs/concepts.md §4.
DEFAULT_WARM_SLOT_CAP = 2


def warm_slot_cap(workspace: Workspace) -> int:
    """Return the warm-slot cap honored by switch's canonical-slot logic."""
    raw = workspace.config.max_worktrees
    return raw if raw and raw > 0 else DEFAULT_WARM_SLOT_CAP


def preflight(
    workspace: Workspace,
    feature_to_activate: str,
    repo_branches: dict[str, str],
    *,
    release_current: bool = False,
    no_evict: bool = False,
) -> dict[str, Any]:
    """Pre-validate a ``switch`` call. Raises ``BlockerError`` on failure.

    Args:
        feature_to_activate: the feature being promoted to canonical (Y).
        repo_branches: per-repo branch map for Y, from ``repos_for_feature``.
        release_current: if True (wind-down mode), the cap-reached check
            is skipped (X goes cold, no warm slot consumed).
        no_evict: in active-rotation mode, refuse to evict an LRU warm
            worktree when the cap is full instead of asking the user.

    Returns a small fact dict the caller can use to make decisions:
    ``{branches_to_create: [(repo, branch)], cap_will_fire: bool,
       lru_eviction_candidate: <feature> | None,
       previously_canonical: <feature> | None}``.
    """
    # Per-repo branch + path checks
    branches_to_create: list[tuple[str, str]] = []
    issues: list[dict[str, Any]] = []

    for repo_name, branch in repo_branches.items():
        try:
            state = workspace.get_repo(repo_name)
        except KeyError:
            issues.append({
                "repo": repo_name,
                "kind": "repo_not_in_workspace",
                "what": f"repo '{repo_name}' not in canopy.toml",
            })
            continue
        repo_path = state.abs_path

        # Lock check — git refuses to operate while index.lock exists
        if (repo_path / ".git" / "index.lock").exists():
            issues.append({
                "repo": repo_name,
                "kind": "index_lock_held",
                "what": (
                    f".git/index.lock present in {repo_name} — another git"
                    " process may be running"
                ),
            })

        # Branch existence — we'll create from default if missing
        if not git.branch_exists(repo_path, branch):
            branches_to_create.append((repo_name, branch))

    # Warm-worktree leftover check for the previously-canonical feature
    # (only applies in active-rotation mode where we'd add a new worktree).
    current = af.read_active(workspace)
    previously_canonical = current.feature if current and current.feature != feature_to_activate else None

    if previously_canonical and not release_current:
        for repo_name in repo_branches:
            dest = warm_worktree_path(workspace, previously_canonical, repo_name)
            if dest.exists():
                issues.append({
                    "repo": repo_name,
                    "kind": "warm_worktree_path_occupied",
                    "what": (
                        f"warm worktree path already exists for"
                        f" {previously_canonical}/{repo_name}: {dest}"
                    ),
                    "path": str(dest),
                })

    # Cap-will-fire check (only active-rotation mode evacuates X to warm)
    cap_will_fire = False
    lru_eviction_candidate: str | None = None
    if previously_canonical and not release_current:
        cap = warm_slot_cap(workspace)
        already_warm = set(warm_features(workspace))
        # Y is becoming canonical, so if Y was warm it leaves the warm set;
        # X (previously_canonical) is joining the warm set.
        post_switch_warm = (already_warm - {feature_to_activate}) | {previously_canonical}
        if len(post_switch_warm) > cap:
            cap_will_fire = True
            lru_eviction_candidate = _pick_lru(
                current, candidates=post_switch_warm - {previously_canonical},
            )
            if no_evict or lru_eviction_candidate is None:
                issues.append({
                    "kind": "worktree_cap_reached",
                    "what": (
                        f"adding {previously_canonical} as warm would exceed"
                        f" warm_slot_cap={cap} (currently warm:"
                        f" {sorted(already_warm)})"
                    ),
                    "current_warm": sorted(already_warm),
                    "cap": cap,
                })

    if issues:
        cap_issue = next((i for i in issues if i.get("kind") == "worktree_cap_reached"), None)
        if cap_issue:
            raise BlockerError(
                code="worktree_cap_reached",
                what=cap_issue["what"],
                expected={"warm_slot_cap": cap_issue["cap"]},
                actual={"warm_now": cap_issue["current_warm"]},
                fix_actions=[
                    FixAction(
                        action="switch",
                        args={"feature": feature_to_activate, "release_current": True},
                        safe=False,
                        preview=(
                            f"wind-down mode: {previously_canonical} goes"
                            f" cold (with stash), no eviction needed"
                        ),
                    ),
                    FixAction(
                        action="switch",
                        args={
                            "feature": feature_to_activate,
                            "evict": lru_eviction_candidate,
                        } if lru_eviction_candidate else {"feature": feature_to_activate},
                        safe=False,
                        preview=(
                            f"evict LRU warm worktree"
                            f" '{lru_eviction_candidate}' to cold"
                            if lru_eviction_candidate
                            else "no LRU candidate found — set last_touched manually"
                        ),
                    ),
                    FixAction(
                        action="workspace_config",
                        args={"max_worktrees": cap_issue["cap"] + 1},
                        safe=True,
                        preview=f"raise warm_slot_cap to {cap_issue['cap'] + 1}",
                    ),
                ],
                details={"all_issues": issues},
            )
        # Non-cap blockers
        raise BlockerError(
            code="switch_preflight_failed",
            what=f"{len(issues)} issue(s) detected before switch could proceed",
            details={"issues": issues},
        )

    return {
        "branches_to_create": branches_to_create,
        "cap_will_fire": cap_will_fire,
        "lru_eviction_candidate": lru_eviction_candidate,
        "previously_canonical": previously_canonical,
    }


def _pick_lru(
    active: af.ActiveFeature | None,
    *,
    candidates: set[str],
) -> str | None:
    """Pick the least-recently-touched feature from ``candidates``.

    Reads ``active.last_touched``. Features not in the map are considered
    older than any feature with a recorded timestamp (lexicographically
    sorted as a tiebreaker for determinism).
    """
    if not candidates:
        return None
    if active is None or not active.last_touched:
        # No recency info — fall back to lexicographic order for determinism
        return sorted(candidates)[0]
    # Sort by (timestamp_or_empty, name)
    return sorted(candidates, key=lambda f: (active.last_touched.get(f, ""), f))[0]
