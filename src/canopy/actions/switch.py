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
from . import evacuate as evac
from . import slots as slots_mod
from . import switch_preflight as preflight
from .aliases import resolve_feature, repos_for_feature
from .errors import BlockerError, FixAction


# Precondition BlockerError codes raised by _do_repo_switch BEFORE any git
# mutation in the failing repo. When one fires with no prior repo completed,
# the workspace is NOT partially flipped, so no in_flight marker is warranted.
_PRE_MUTATION_CODES = frozenset({
    "no_free_slot",
    "unknown_slot",
    "evict_to_occupied",
    "warm_worktree_dirty_on_promote",
})


def switch(
    workspace: Workspace,
    feature: str | None = None,
    *,
    release_current: bool = False,
    no_evict: bool = False,
    evict: str | None = None,
    evict_to: str | None = None,
    to_slot: str | None = None,
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
        evict_to: pin which slot the previously-canonical feature evacuates
            to (overrides the LRU-coldest-free pick).
        to_slot: promote the feature currently in this slot to canonical.
            Sugar over ``switch(<feature-in-slot>)``.

    Returns ``{feature, mode, per_repo_paths, previously_canonical?,
    evacuation?, eviction?, branches_created?, migration?}``.
    """
    # to_slot: resolve the occupant and forward
    if to_slot is not None:
        if feature is not None:
            raise BlockerError(
                code="ambiguous_switch_args",
                what="pass `feature` OR `--to-slot`, not both",
            )
        occupant = slots_mod.feature_for_slot(workspace, to_slot)
        if occupant is None:
            raise BlockerError(
                code="slot_empty",
                what=f"slot '{to_slot}' is empty — nothing to promote",
                details={"slot": to_slot},
            )
        feature = occupant

    if feature is None:
        raise BlockerError(
            code="missing_feature",
            what="switch needs a feature name or --to-slot",
        )

    _ensure_post_migration(workspace)
    _ensure_consistent(workspace)
    feature_name = resolve_feature_safely(workspace, feature)

    repo_branches = repos_for_feature(workspace, feature_name)
    if not repo_branches:
        # Permit fresh feature names (will create branches from default)
        repo_branches = {r.config.name: feature_name for r in workspace.repos}

    pre = preflight.preflight(
        workspace, feature_name, repo_branches,
        release_current=release_current,
        no_evict=no_evict and (evict is None),
        evict_to=evict_to,
    )

    out: dict[str, Any] = {"feature": feature_name}
    previously_canonical = pre["previously_canonical"]
    if previously_canonical:
        out["previously_canonical"] = previously_canonical

    # Phase 4: the default now decides warm-vs-cold per the vacating
    # feature's PR/WIP state. release_current (explicit cold) and the
    # evict overrides still win. Only applies when a feature is vacating.
    effective_release = release_current
    if (not release_current and previously_canonical
            and evict is None and evict_to is None and not no_evict):
        from .slot_policy import warm_or_cold
        if warm_or_cold(workspace, previously_canonical) == "cold":
            effective_release = True
    out["vacate_decision"] = "cold" if effective_release else "warm"

    # Phase 4: when the warm-slot cap would fire and the vacating feature is
    # going warm, the default is to RAISE a structured choice — not silently
    # auto-evict the LRU warm feature. Only an explicit pick (evict /
    # evict_to) proceeds past this. The agent surfaces the three fix_actions
    # as a question; the user picks; canopy re-runs with the chosen override.
    if (pre["cap_will_fire"] and not effective_release
            and evict is None and evict_to is None):
        cap = preflight.warm_slot_cap(workspace)
        lru = pre.get("lru_eviction_candidate")
        raise BlockerError(
            code="worktree_cap_reached",
            what=(f"slot cap full ({cap}/{cap}) — choose how to make room "
                  f"for '{previously_canonical}'"),
            fix_actions=[
                FixAction(action="raise_cap", args={"slots": cap + 1}, safe=True,
                          preview="Raise the cap; keep everything warm"),
                FixAction(action="release_current",
                          args={"feature": previously_canonical}, safe=True,
                          preview=f"Send {previously_canonical} cold this time"),
                FixAction(action="evict", args={"feature": lru}, safe=False,
                          preview=f"Evict warm PR '{lru}' to cold to make room"),
            ],
            details={"warm_features": pre.get("warm_features", []),
                     "lru_candidate": lru, "vacating": previously_canonical},
        )

    # Step A: optional eviction (active-rotation cap fire) —
    # explicit ``evict=<feature>`` overrides preflight's LRU pick.
    # When ``evict_to`` is pinned to an occupied slot, evict that slot's
    # occupant first so X can land there.
    eviction_info: dict[str, Any] | None = None
    eviction_target: str | None = None
    if not effective_release:
        if evict:
            eviction_target = evict
        elif evict_to is not None:
            # Pinned destination — if it holds an occupant other than Y, evict it.
            cur_state = slots_mod.read_state(workspace)
            if cur_state is not None and evict_to in cur_state.slots:
                occ = cur_state.slots[evict_to].feature
                if occ and occ != feature_name:
                    eviction_target = occ
        # Note: a bare cap-fire (no explicit evict/evict_to) now RAISES
        # worktree_cap_reached above — it no longer auto-evicts the LRU.
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

        try:
            _do_repo_switch(
                workspace, feature_name, repo_name, target_branch,
                repo_path=repo_path,
                release_current=effective_release,
                previously_canonical=previously_canonical,
                per_repo_results=per_repo_results,
                new_canonical_paths=new_canonical_paths,
                evict_to=evict_to,
            )
        except BlockerError as e:
            # A structured precondition failure raised BEFORE any git
            # mutation (no_free_slot, dirty warm worktree, bad --evict-to)
            # leaves disk untouched in this repo. Only stamp in_flight when
            # something is actually half-flipped: an earlier repo already
            # completed (per_repo_results non-empty), OR this was a mid-op
            # failure (not one of the pre-mutation precondition codes).
            # Otherwise a clean no-op failure would brick every future
            # switch via slot_state_inconsistent.
            if per_repo_results or e.code not in _PRE_MUTATION_CODES:
                _persist_in_flight(
                    workspace, feature_name, previously_canonical,
                    failed_repo=repo_name, error_what=e.what or str(e),
                    completed_results=per_repo_results,
                )
            raise
        except Exception as e:
            # Mid-op failure with no rollback walker (yet). Surface enough
            # state for the user to recover manually instead of leaving
            # them with a generic exception. See GitHub issue #2.
            _persist_in_flight(
                workspace, feature_name, previously_canonical,
                failed_repo=repo_name, error_what=str(e),
                completed_results=per_repo_results,
            )
            raise _build_mid_op_error(
                workspace, feature_name, repo_name, target_branch,
                previously_canonical, e, per_repo_results,
            )

    _post_switch_persist(
        workspace, feature_name, new_canonical_paths, previously_canonical,
        out, release_current=effective_release, per_repo_results=per_repo_results,
    )

    # Phase 4: auto-bootstrap the freshly-created warm slot (never fails switch).
    if not effective_release and previously_canonical:
        _sid = slots_mod.slot_for_feature(workspace, previously_canonical)
        if _sid:
            try:
                from .slot_bootstrap import bootstrap_on_slot_create
                bootstrap_on_slot_create(workspace, previously_canonical, _sid)
            except Exception:
                pass

    # M4: include the new feature's persistent memory so the agent picks
    # up cross-session context immediately. Empty string when no memory
    # has been recorded yet — caller can ignore.
    from . import historian
    out["memory"] = historian.format_for_agent(
        workspace.config.root, feature_name,
    )

    return out


def _do_repo_switch(
    workspace: Workspace,
    feature_name: str,
    repo_name: str,
    target_branch: str,
    *,
    repo_path: Path,
    release_current: bool,
    previously_canonical: str | None,
    per_repo_results: list[dict[str, Any]],
    new_canonical_paths: dict[str, str],
    evict_to: str | None = None,
) -> None:
    """Per-repo switch body — extracted so the caller can wrap it in a
    structured mid-op error handler. Mutates the lists/dicts in place."""

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
        return

    # Mode A: wind-down — stash X dirty into a feature-tagged stash on
    # X's branch, then plain checkout Y in main. No worktree-add for X.
    if release_current and previously_canonical and current == _branch_for_in_repo(
        workspace, previously_canonical, repo_name,
    ):
        # If Y is warm in a slot, must free it from the slot before main
        # can adopt it (git one-checkout-per-branch rule).
        _free_warm_slot_if_holding(workspace, feature_name, repo_name)
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
        return

    # Mode B: active rotation
    if (
        previously_canonical
        and not release_current
        and current == _branch_for_in_repo(
            workspace, previously_canonical, repo_name,
        )
    ):
        # Fast-path: Y is already warm in some slot → 5-op swap
        y_slot = slots_mod.slot_for_feature(workspace, feature_name)
        if y_slot is not None:
            slot_dir = slots_mod.slot_worktree_path(
                workspace, y_slot, repo_name,
            )
            if (slot_dir / ".git").exists():
                default_branch = workspace.get_repo(
                    repo_name,
                ).config.default_branch
                result = evac.fastpath_swap_repo(
                    workspace,
                    x_feature=previously_canonical,
                    y_feature=target_branch,
                    repo_name=repo_name,
                    repo_path=repo_path,
                    slot_id=y_slot,
                    default_branch=default_branch,
                )
                per_repo_results.append(result)
                return
            # Fall through: Y's slot entry exists but this repo's slot
            # dir is missing (orphaned worktree / partial-scope drift).
            # Y is still being promoted to canonical, so it vacates its
            # slot regardless — X reclaims y_slot below instead of needing
            # a brand-new allocation. Allocating blindly here would count
            # Y's own about-to-be-freed slot against the cap and raise a
            # bogus no_free_slot (the canopy-test billing-export lock-out).

        # Cold-Y path: allocate (or reclaim) the slot X will occupy.
        state = slots_mod.read_state(workspace) or slots_mod.SlotState(
            slot_count=workspace.config.slots,
        )
        if evict_to is not None:
            # Validate the slot id is in range
            valid_slots = {f"worktree-{i}" for i in range(1, workspace.config.slots + 1)}
            if evict_to not in valid_slots:
                raise BlockerError(
                    code="unknown_slot",
                    what=f"--evict-to {evict_to} is out of range (cap={workspace.config.slots})",
                )
            if evict_to in state.slots:
                existing = state.slots[evict_to].feature
                if existing != feature_name:
                    raise BlockerError(
                        code="evict_to_occupied",
                        what=f"slot '{evict_to}' is already occupied by '{existing}'",
                        details={"slot": evict_to, "occupant": existing},
                    )
            x_slot = evict_to
        elif y_slot is not None:
            # Y already owns y_slot and is leaving it (becoming canonical);
            # X reclaims it. _post_switch_persist re-stamps the slot to X.
            x_slot = y_slot
        else:
            x_slot = slots_mod.allocate_slot(state)
        if x_slot is None:
            # Preflight should have caught this; defensive
            raise BlockerError(
                code="no_free_slot",
                what="no free slot for evacuation (preflight should have raised)",
            )
        result = evac.evacuate_repo(
            workspace, previously_canonical, repo_name, repo_path,
            slot_id=x_slot,
            target_branch=target_branch,
        )
        per_repo_results.append(result)
        return

    # Fallback: main is on something else (or not on previous_canonical).
    # Just stash + checkout. If Y happens to be warm somewhere, free it
    # first.
    _free_warm_slot_if_holding(workspace, feature_name, repo_name)
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


def _build_mid_op_error(
    workspace: Workspace,
    feature_name: str,
    failed_repo: str,
    target_branch: str,
    previously_canonical: str | None,
    underlying_error: Exception,
    completed_results: list[dict[str, Any]],
) -> BlockerError:
    """Build a structured ``BlockerError`` for a mid-op failure.

    Goal: tell the user exactly which repo failed at which step, what
    state the workspace is in NOW, and the precise commands to recover.
    Without this they get a generic git error and a half-flipped workspace.

    A real rollback walker is in GitHub issue #2; this is the interim.
    """
    completed_repos = [r["repo"] for r in completed_results]
    # Per-repo recovery hints for completed repos
    recovery_hints: list[str] = []
    for r in completed_results:
        if r.get("stashed"):
            recovery_hints.append(
                f"  {r['repo']}: stash exists ({r.get('stash_ref','stash@{0}')}) — "
                f"`git -C <{r['repo']}-path> stash list` to inspect"
            )
        if r.get("status") == "evacuated" and r.get("worktree_path"):
            recovery_hints.append(
                f"  {r['repo']}: warm worktree at {r['worktree_path']} (X={previously_canonical})"
            )

    return BlockerError(
        code="switch_mid_op_failed",
        what=(
            f"switch to '{feature_name}' failed in repo '{failed_repo}' — "
            f"workspace is partially flipped"
        ),
        expected={"feature": feature_name, "target_branch": target_branch},
        actual={
            "failed_repo": failed_repo,
            "completed_repos": completed_repos,
            "underlying_error": str(underlying_error),
            "underlying_error_type": type(underlying_error).__name__,
        },
        details={
            "previously_canonical": previously_canonical,
            "completed_results": completed_results,
            "recovery_hints": recovery_hints,
        },
        fix_actions=[
            FixAction(
                action="manual",
                args={"see": "details.recovery_hints"},
                safe=False,
                preview=(
                    "auto-rollback isn't implemented yet (GH #2). "
                    "Inspect per-repo state via `canopy state` + `git stash list` "
                    "in each repo, then re-run `canopy switch <feature>` once "
                    f"the underlying error ({type(underlying_error).__name__}) is resolved."
                ),
            ),
            FixAction(
                action="switch",
                args={"feature": previously_canonical} if previously_canonical else {"feature": feature_name},
                safe=False,
                preview=(
                    f"switch back to '{previously_canonical}' may un-flip"
                    f" some repos (depends on which step failed)"
                    if previously_canonical else "retry the switch"
                ),
            ),
        ],
    )


def _post_switch_persist(
    workspace: Workspace,
    feature_name: str,
    new_canonical_paths: dict[str, str],
    previously_canonical: str | None,
    out: dict[str, Any],
    *,
    release_current: bool,
    per_repo_results: list[dict[str, Any]],
) -> None:
    """Finalize the switch result: write ``slots.json`` + populate summary
    fields. Mutates ``out`` in place."""
    out["mode"] = "wind_down" if release_current else "active_rotation"
    out["per_repo"] = per_repo_results
    out["per_repo_paths"] = new_canonical_paths

    state = slots_mod.read_state(workspace) or slots_mod.SlotState(
        slot_count=workspace.config.slots,
    )
    now = slots_mod.now_iso()

    state.previous_canonical = (
        state.canonical.feature if state.canonical else None
    )
    state.canonical = slots_mod.CanonicalEntry(
        feature=feature_name,
        activated_at=now,
        per_repo_paths={k: str(v) for k, v in new_canonical_paths.items()},
    )

    # Apply per-repo slot mutations. fastpath swaps update the existing
    # slot entry; cold-Y evacuations occupy a freshly allocated slot.
    for r in per_repo_results:
        if r.get("status") == "fastpath_swapped":
            sid = r["slot_id"]
            state.slots[sid] = slots_mod.SlotEntry(
                feature=r["swapped_out"], occupied_at=now,
            )
        elif r.get("status") == "evacuated":
            sid = r["slot_id"]
            state.slots[sid] = slots_mod.SlotEntry(
                feature=previously_canonical or "",
                occupied_at=now,
            )

    state.last_touched[feature_name] = now
    if previously_canonical:
        state.last_touched[previously_canonical] = now

    # Drop any slot entries that still claim Y — Y is now canonical and
    # its slot dir (if it had one) was emptied by fastpath_swap_repo.
    for sid, entry in list(state.slots.items()):
        if entry.feature == feature_name:
            del state.slots[sid]

    # Clear any in_flight marker — this switch completed cleanly.
    state.in_flight = None

    # T14: capture prior anchor BEFORE the T13 bump so the summary's
    # "since when" window reflects what the user last saw, not this visit.
    from . import last_visit as lv
    _prior = lv.get_last_visit(workspace, feature_name)
    prior_iso: str | None = _prior["last_visit"] if _prior else None

    slots_mod.write_state(workspace, state)

    # T13: bump last_visit after slots.json is committed — every successful
    # switch into a feature counts as a "conscious look" per the plan.
    lv.mark_visited(workspace, feature_name)

    # T14: embed since-last-visit summary using the PRIOR anchor.
    try:
        from . import resume
        out["since_last_visit_summary"] = resume.resume_summary(
            workspace, feature_name, prior_iso=prior_iso,
        )
    except Exception:
        out["since_last_visit_summary"] = {
            "last_visit": prior_iso,
            "first_visit": prior_iso is None,
            "new_commit_count": 0,
            "new_thread_count": 0,
            "github_resolved_count": 0,
            "ci_changed": False,
            "draft_replies_pending": 0,
            "memory_present": False,
            "degraded": True,
        }

    out["activated_at"] = now
    if state.previous_canonical:
        out["previous_feature_in_state"] = state.previous_canonical


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

    Slot-aware: finds the slot currently holding ``feature`` and clears
    every repo subdir of that slot. The branch stays — feature is now
    cold. After clearing, removes the slot entry from ``slots.json``.

    Returns ``{feature, slot_id, repos: [{repo, stashed, stash_ref?,
    removed}]}``. Empty repos list if the feature wasn't actually warm.
    """
    slot_id = slots_mod.slot_for_feature(workspace, feature)
    if slot_id is None:
        return {"feature": feature, "slot_id": None, "repos": []}

    repo_results: list[dict[str, Any]] = []
    for state in workspace.repos:
        repo_name = state.config.name
        wt_path = slots_mod.slot_worktree_path(workspace, slot_id, repo_name)
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

    # Drop the slot entry from state so the slot becomes available.
    st = slots_mod.read_state(workspace)
    if st is not None and slot_id in st.slots:
        del st.slots[slot_id]
        slots_mod.write_state(workspace, st)
    return {"feature": feature, "slot_id": slot_id, "repos": repo_results}


def _free_warm_slot_if_holding(
    workspace: Workspace, feature: str, repo_name: str,
) -> None:
    """If ``feature`` is warm in some slot for ``repo_name``, remove that
    slot's worktree for this repo so main can adopt the branch.

    Raises ``BlockerError(warm_worktree_dirty_on_promote)`` if the slot
    is dirty — losing the user's work is never silent. Mirrors the
    pre-3.0 reverse-evacuation safety check, just keyed by slot id.
    """
    slot_id = slots_mod.slot_for_feature(workspace, feature)
    if slot_id is None:
        return
    wt_path = slots_mod.slot_worktree_path(workspace, slot_id, repo_name)
    if not (wt_path / ".git").exists():
        return
    if git.is_dirty(wt_path):
        raise BlockerError(
            code="warm_worktree_dirty_on_promote",
            what=(
                f"warm worktree {wt_path} has uncommitted changes;"
                f" can't promote {feature} to canonical without losing them"
            ),
            details={"feature": feature, "repo": repo_name,
                     "worktree_path": str(wt_path), "slot_id": slot_id},
            fix_actions=[
                FixAction(
                    action="commit",
                    args={"feature": feature},
                    safe=False,
                    preview=f"commit dirty changes in {wt_path}",
                ),
                FixAction(
                    action="stash_save_feature",
                    args={"feature": feature},
                    safe=True,
                    preview=f"stash dirty changes in {wt_path}",
                ),
            ],
        )
    repo_state = workspace.get_repo(repo_name)
    git.worktree_remove(repo_state.abs_path, wt_path)


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
    (e.g. auth-flow in api vs auth-flow-v2 in ui)."""
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


# ── partial-failure marker ──────────────────────────────────────────────

def _persist_in_flight(
    workspace: Workspace,
    feature_being_promoted: str,
    previously_canonical: str | None,
    *,
    failed_repo: str,
    error_what: str,
    completed_results: list[dict[str, Any]],
) -> None:
    """Stamp ``slots.json`` with an in_flight marker so the next switch
    refuses to run on a half-flipped workspace.

    Captures: what we were trying to do, what completed before the crash,
    which repo blew up, and the underlying error message. Cleared on the
    next successful switch via ``_post_switch_persist``.
    """
    state = slots_mod.read_state(workspace) or slots_mod.SlotState(
        slot_count=workspace.config.slots,
    )
    state.in_flight = {
        "feature_being_promoted": feature_being_promoted,
        "previously_canonical": previously_canonical,
        "started_at": slots_mod.now_iso(),
        "per_repo_completed": [
            {k: v for k, v in r.items()} for r in completed_results
        ],
        "failed_repo": failed_repo,
        "error_what": error_what,
    }
    slots_mod.write_state(workspace, state)


def _ensure_consistent(workspace: Workspace) -> None:
    """Refuse to switch when an in_flight marker is set.

    A prior switch left the workspace in a partial state (some repos
    flipped to Y, others still on X). Continuing would compound the
    inconsistency. Surface a structured blocker; T19 will extend doctor
    to actually repair this.
    """
    state = slots_mod.read_state(workspace)
    if state is None or state.in_flight is None:
        return
    inf = state.in_flight
    raise BlockerError(
        code="slot_state_inconsistent",
        what=(
            f"a prior switch to '{inf.get('feature_being_promoted')}' failed in "
            f"repo '{inf.get('failed_repo')}' — workspace is partially flipped"
        ),
        details={"in_flight": dict(inf)},
        fix_actions=[
            FixAction(
                action="doctor",
                args={},
                safe=True,
                preview=(
                    "run `canopy doctor` to inspect slots.json and the "
                    "completed-vs-failed per-repo work; resolve manually, "
                    "then clear the in_flight marker"
                ),
            ),
        ],
    )


# ── pre-3.0 migration gate ──────────────────────────────────────────────

def _ensure_post_migration(workspace: Workspace) -> None:
    """Refuse to switch on a workspace still on the pre-3.0 layout.

    If ``.canopy/state/active_feature.json`` exists, the workspace hasn't
    been migrated to the slot model yet. Surface a structured blocker
    pointing at ``canopy migrate-slots`` instead of silently writing the
    new ``slots.json`` alongside (which would leave two sources of truth).
    """
    old = workspace.config.root / ".canopy/state/active_feature.json"
    if old.exists():
        raise BlockerError(
            code="pre_migration",
            what="this workspace is on the pre-3.0 layout — run `canopy migrate-slots`",
            details={"old_state_file": str(old)},
            fix_actions=[
                FixAction(
                    action="migrate_slots",
                    args={},
                    safe=True,
                    preview="canopy migrate-slots — one-shot rewrite to slot layout",
                ),
            ],
        )
