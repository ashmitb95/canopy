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
from . import slots as slots_mod
from .errors import BlockerError, FixAction


# Default cap when slots is unset. The config parser already defaults
# `slots` to 2, so this is purely defensive.
DEFAULT_WARM_SLOT_CAP = 2


def warm_slot_cap(workspace: Workspace) -> int:
    """Return the warm-slot cap honored by switch's canonical-slot logic."""
    raw = workspace.config.slots
    return raw if raw and raw > 0 else DEFAULT_WARM_SLOT_CAP


def preflight(
    workspace: Workspace,
    feature_to_activate: str,
    repo_branches: dict[str, str],
    *,
    release_current: bool = False,
    no_evict: bool = False,
    evict_to: str | None = None,
) -> dict[str, Any]:
    """Pre-validate a ``switch`` call. Raises ``BlockerError`` on failure.

    Args:
        feature_to_activate: the feature being promoted to canonical (Y).
        repo_branches: per-repo branch map for Y, from ``repos_for_feature``.
        release_current: if True (wind-down mode), the cap-reached check
            is skipped (X goes cold, no warm slot consumed).
        no_evict: in active-rotation mode, refuse to evict an LRU warm
            worktree when the cap is full instead of asking the user.
        evict_to: if set, the user has pinned a destination slot for X.
            Skip the cap-fire check — the explicit-slot path (in switch)
            handles validation + eviction of any occupant.

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

    # Validate-all-then-execute: aggregate every per-repo problem and raise
    # BEFORE any slot-state read or mutation. A bad precondition must leave
    # disk untouched (both historical bricking bugs were partial mutations
    # where a precondition failed AFTER some repos had already changed).
    if issues:
        raise BlockerError(
            code="switch_preflight_failed",
            what="switch blocked — resolve these before switching: "
                 + "; ".join(f"{i['repo']}: {i['what']}" for i in issues),
            details={"issues": issues},
        )

    # Read the slot state (3.0 layout). previously_canonical is the
    # canonical feature, if any, that differs from Y.
    state = slots_mod.read_state(workspace)
    previously_canonical: str | None = None
    if state and state.canonical and state.canonical.feature != feature_to_activate:
        previously_canonical = state.canonical.feature

    already_warm: set[str] = (
        {e.feature for e in state.slots.values()} if state else set()
    )

    # Cap-will-fire check (only active-rotation mode evacuates X to warm).
    # When the user pinned a destination via ``--evict-to``, the
    # explicit-slot path in switch handles validation + occupant
    # eviction, so skip the cap-fire surface here.
    cap_will_fire = False
    lru_eviction_candidate: str | None = None
    if previously_canonical and not release_current and evict_to is None:
        cap = warm_slot_cap(workspace)
        # Y is becoming canonical, so if Y was warm it leaves the warm set;
        # X (previously_canonical) is joining the warm set.
        post_switch_warm = (already_warm - {feature_to_activate}) | {previously_canonical}
        if len(post_switch_warm) > cap:
            cap_will_fire = True
            lru_eviction_candidate = slots_mod.lru_evictee(
                state, exclude={feature_to_activate},
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
                        action="config",
                        args={"slots": cap_issue["cap"] + 1},
                        safe=True,
                        preview=f"raise warm_slot_cap to {cap_issue['cap'] + 1}",
                    ),
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
                ],
                details={"all_issues": issues},
            )

    return {
        "branches_to_create": branches_to_create,
        "cap_will_fire": cap_will_fire,
        "lru_eviction_candidate": lru_eviction_candidate,
        "previously_canonical": previously_canonical,
        "warm_features": sorted(already_warm),
    }
