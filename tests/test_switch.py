"""Tests for Wave 3.0 slot-model switch behavior.

Coverage:
  - fast-path swap when Y is warm in some slot (no worktree add)
  - cold-Y allocates the lowest free slot for X
  - cap-reached + ``no_evict=True`` raises ``BlockerError(worktree_cap_reached)``

Slot-model fixtures (workspace_with_canonical_only / workspace_with_slots /
workspace_with_full_slots) live in conftest.py.
"""
from __future__ import annotations

import subprocess

import pytest


# ── tests ───────────────────────────────────────────────────────────────

def test_switch_fastpath_when_y_warm(workspace_with_slots):
    """X canonical, Y warm in slot-1, switch(Y) uses fast-path (no worktree add)."""
    ws = workspace_with_slots
    from canopy.actions.switch import switch
    from canopy.actions import slots as sm
    from canopy.actions import prs_cache

    # X (the vacating feature) needs an open PR to stay warm under the
    # Phase-4 default; otherwise a clean, PR-less X goes cold (wind_down).
    prs_cache.write(ws, {"X": {"repos": {"repo-a": {"number": 1, "state": "open"}}}})
    result = switch(ws, "Y")

    assert result["mode"] == "active_rotation"
    per_repo = {r["repo"]: r for r in result["per_repo"]}
    assert per_repo["repo-a"]["status"] == "fastpath_swapped"
    assert per_repo["repo-b"]["status"] == "fastpath_swapped"

    state = sm.read_state(ws)
    assert state is not None
    assert state.canonical is not None
    assert state.canonical.feature == "Y"
    assert "worktree-1" in state.slots
    assert state.slots["worktree-1"].feature == "X"


def test_switch_cold_y_allocates_lowest_free_slot(workspace_with_canonical_only):
    """X canonical alone, switch(Y) where Y is cold — slot-1 gets X."""
    ws = workspace_with_canonical_only
    from canopy.actions.switch import switch
    from canopy.actions import slots as sm
    from canopy.actions import prs_cache

    # X (vacating) needs an open PR to evacuate warm under the Phase-4
    # default; a clean, PR-less X would go cold instead.
    prs_cache.write(ws, {"X": {"repos": {"repo-a": {"number": 1, "state": "open"}}}})
    result = switch(ws, "Y")

    assert result["mode"] == "active_rotation"
    per_repo = {r["repo"]: r for r in result["per_repo"]}
    assert per_repo["repo-a"]["status"] == "evacuated"
    assert per_repo["repo-a"]["slot_id"] == "worktree-1"

    state = sm.read_state(ws)
    assert state is not None
    assert state.canonical is not None
    assert state.canonical.feature == "Y"
    assert "worktree-1" in state.slots
    assert state.slots["worktree-1"].feature == "X"
    # Successful switch must explicitly clear any in_flight marker.
    assert state.in_flight is None


def test_switch_cap_reached_with_no_evict_raises(workspace_with_full_slots):
    """All slots full + switch new feature → BlockerError(worktree_cap_reached)."""
    ws = workspace_with_full_slots
    from canopy.actions.switch import switch
    from canopy.actions.errors import BlockerError

    # Create a new branch NEW so switch can resolve it
    for repo in ("repo-a", "repo-b"):
        subprocess.run(["git", "branch", "NEW"],
                       cwd=ws.config.root / repo, check=True)

    with pytest.raises(BlockerError) as e:
        switch(ws, "NEW", no_evict=True)
    assert e.value.code == "worktree_cap_reached"


def test_partial_switch_failure_marks_in_flight(
    workspace_with_canonical_only, monkeypatch,
):
    """If repo-b fails mid-switch, slots.json gets an in_flight marker."""
    ws = workspace_with_canonical_only
    from canopy.actions import evacuate as evac
    from canopy.actions import slots as sm
    from canopy.actions import prs_cache
    from canopy.actions.switch import switch

    # X (vacating) needs an open PR to take the warm evacuation path this
    # test exercises; otherwise the Phase-4 default sends X cold (no evac).
    prs_cache.write(ws, {"X": {"repos": {"repo-a": {"number": 1, "state": "open"}}}})
    real_evacuate = evac.evacuate_repo
    call_count = {"n": 0}

    def flaky_evacuate(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return real_evacuate(*args, **kwargs)
        raise RuntimeError("simulated git failure in repo-b")

    monkeypatch.setattr(
        "canopy.actions.switch.evac.evacuate_repo", flaky_evacuate,
    )

    # First repo succeeds (slot allocated, X evacuated), second blows up.
    with pytest.raises(Exception):
        switch(ws, "Y")

    state = sm.read_state(ws)
    assert state is not None
    assert state.in_flight is not None
    assert state.in_flight["feature_being_promoted"] == "Y"
    assert state.in_flight["failed_repo"] == "repo-b"
    assert state.in_flight["previously_canonical"] == "X"
    assert len(state.in_flight["per_repo_completed"]) == 1
    assert state.in_flight["per_repo_completed"][0]["repo"] == "repo-a"
    assert "simulated git failure" in state.in_flight["error_what"]


def test_switch_evict_to_pins_destination_slot(workspace_with_canonical_only):
    """switch(Y, evict_to='worktree-2') → X lands in slot-2 (not LRU pick)."""
    ws = workspace_with_canonical_only
    from canopy.actions.switch import switch
    from canopy.actions import slots as sm

    result = switch(ws, "Y", evict_to="worktree-2")

    state = sm.read_state(ws)
    assert state is not None
    assert state.canonical is not None
    assert state.canonical.feature == "Y"
    assert state.slots["worktree-2"].feature == "X"
    assert "worktree-1" not in state.slots


def test_switch_evict_to_occupied_slot_evicts_and_replaces(workspace_with_full_slots):
    """With all slots full, switch(NEW, evict_to=<slot-1>) evicts slot-1's
    occupant and pins X (the previously-canonical feature) there — no
    cap-reached blocker fires when the destination is pinned."""
    import subprocess
    ws = workspace_with_full_slots
    # Create NEW branch in both repos
    for repo in ("repo-a", "repo-b"):
        subprocess.run(["git", "branch", "NEW"], cwd=ws.config.root / repo, check=True)
    from canopy.actions.switch import switch
    from canopy.actions import slots as sm
    result = switch(ws, "NEW", evict_to="worktree-1")
    assert result["feature"] == "NEW"
    state = sm.read_state(ws)
    assert state.canonical is not None
    assert state.canonical.feature == "NEW"
    # X (previously canonical) landed in the pinned slot
    assert state.slots["worktree-1"].feature == "X"


def test_switch_to_slot_promotes_occupant(workspace_with_slots):
    """slot-1 has Y; switch(to_slot='worktree-1') → Y becomes canonical."""
    ws = workspace_with_slots
    from canopy.actions.switch import switch
    from canopy.actions import slots as sm

    result = switch(ws, feature=None, to_slot="worktree-1")

    assert result["feature"] == "Y"
    state = sm.read_state(ws)
    assert state is not None
    assert state.canonical is not None
    assert state.canonical.feature == "Y"


def test_switch_blocked_when_in_flight_set(workspace_with_canonical_only):
    """Pre-seeded in_flight marker → switch refuses with slot_state_inconsistent."""
    ws = workspace_with_canonical_only
    from canopy.actions import slots as sm
    from canopy.actions.errors import BlockerError
    from canopy.actions.switch import switch

    state = sm.read_state(ws)
    assert state is not None
    state.in_flight = {
        "feature_being_promoted": "Y",
        "previously_canonical": "X",
        "started_at": sm.now_iso(),
        "per_repo_completed": [],
        "failed_repo": "repo-b",
        "error_what": "previous failure",
    }
    sm.write_state(ws, state)

    with pytest.raises(BlockerError) as e:
        switch(ws, "Y")
    assert e.value.code == "slot_state_inconsistent"


# ── T13: last_visit bumping ────────────────────────────────────────────────


def test_switch_bumps_last_visit(workspace_with_canonical_only):
    """Successful switch advances last_visit for the target feature."""
    ws = workspace_with_canonical_only
    from canopy.actions.switch import switch
    from canopy.actions import last_visit as lv

    # Pre-condition: no anchor for Y
    assert lv.get_last_visit(ws, "Y") is None

    # Switch to Y
    result = switch(ws, "Y")

    # Verify switch succeeded
    assert result["feature"] == "Y"

    # Verify last_visit was bumped
    visit = lv.get_last_visit(ws, "Y")
    assert visit is not None
    assert "last_visit" in visit
    assert visit["last_visit"] is not None


def test_switch_bumps_previous_visit_on_reswitch(workspace_with_canonical_only):
    """Subsequent switches roll the prior anchor into previous_visit."""
    import time
    ws = workspace_with_canonical_only
    from canopy.actions.switch import switch
    from canopy.actions import last_visit as lv

    # First switch to Y
    switch(ws, "Y")
    ts1 = lv.get_last_visit(ws, "Y")["last_visit"]

    # Wait to ensure timestamp advances
    time.sleep(1.1)

    # Re-switch to Y (no-op on branches, but anchor still bumps)
    switch(ws, "Y")

    # Verify last_visit advanced and previous_visit holds the old value
    after = lv.get_last_visit(ws, "Y")
    assert after["last_visit"] > ts1, "last_visit must have advanced"
    assert after["previous_visit"] == ts1, "previous_visit must hold the old anchor"


# ── T14: since_last_visit_summary embedded in switch return ───────────────


_SUMMARY_KEYS = (
    "last_visit", "first_visit", "new_commit_count", "new_thread_count",
    "github_resolved_count", "ci_changed", "draft_replies_pending",
    "memory_present", "degraded",
)


def test_switch_result_includes_since_last_visit_summary(workspace_with_canonical_only):
    """switch return carries since_last_visit_summary with all required keys."""
    ws = workspace_with_canonical_only
    from canopy.actions.switch import switch

    result = switch(ws, "Y")

    assert "since_last_visit_summary" in result, (
        "switch must embed since_last_visit_summary in its return dict"
    )
    s = result["since_last_visit_summary"]
    for key in _SUMMARY_KEYS:
        assert key in s, f"since_last_visit_summary missing key: {key}"


def test_switch_summary_first_visit_when_no_prior_anchor(workspace_with_canonical_only):
    """No prior anchor for target feature → first_visit=True, counts zero."""
    ws = workspace_with_canonical_only
    from canopy.actions.switch import switch
    from canopy.actions import last_visit as lv

    # Confirm no anchor for Y before the switch.
    assert lv.get_last_visit(ws, "Y") is None

    result = switch(ws, "Y")

    s = result["since_last_visit_summary"]
    assert s["first_visit"] is True
    assert s["last_visit"] is None
    assert s["new_commit_count"] == 0
    assert s["new_thread_count"] == 0
    assert s["degraded"] is False


def test_switch_summary_uses_prior_anchor(workspace_with_canonical_only):
    """summary's last_visit reflects the value BEFORE this switch's bump."""
    import time
    ws = workspace_with_canonical_only
    from canopy.actions.switch import switch
    from canopy.actions import last_visit as lv

    # First switch to Y: establishes an anchor.
    switch(ws, "Y")
    ts1 = lv.get_last_visit(ws, "Y")["last_visit"]

    # Wait so the next bump has a strictly later timestamp.
    time.sleep(1.1)

    # Re-switch to Y — the summary should anchor to ts1 (the PRIOR value).
    result = switch(ws, "Y")

    s = result["since_last_visit_summary"]
    assert s["first_visit"] is False, "second switch should not be first_visit"
    assert s["last_visit"] == ts1, (
        "summary's last_visit must equal the anchor captured BEFORE this switch bumped it"
    )

    # And the live anchor must have advanced past ts1.
    assert lv.get_last_visit(ws, "Y")["last_visit"] > ts1


def test_switch_summary_degraded_when_threads_fail(
    workspace_with_canonical_only, monkeypatch
):
    """GH unreachable → degraded=True, thread counts zero, switch still succeeds."""
    ws = workspace_with_canonical_only
    from canopy.actions import last_visit as lv
    from canopy.actions.switch import switch

    # Pre-seed an anchor so we're not in first_visit territory.
    lv.mark_visited(ws, "Y")

    def boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr("canopy.actions.resume._threads_delta", boom)

    result = switch(ws, "Y")

    s = result["since_last_visit_summary"]
    assert s["degraded"] is True
    assert s["new_thread_count"] == 0
    # Switch itself must not have failed.
    assert result["feature"] == "Y"


# ── orphaned-warm-worktree regression (canopy-test billing-export lock-out) ──


def _orphan_repo_worktree(ws, feature, repo):
    """Simulate a slot whose per-repo worktree dir vanished while the slot
    entry survives in slots.json — the divergence that bricked canopy-test.

    Deletes the repo subdir of ``feature``'s slot and prunes git's worktree
    registration (matching the real state: `git worktree list` showed none),
    but leaves the slot's top dir + other repo subdirs so read_state keeps
    the slot entry.
    """
    import shutil
    from canopy.actions import slots as sm

    sid = sm.slot_for_feature(ws, feature)
    assert sid is not None, f"{feature!r} must be warm to orphan it"
    wt_repo = sm.slot_worktree_path(ws, sid, repo)
    assert wt_repo.exists()
    shutil.rmtree(wt_repo)
    subprocess.run(
        ["git", "worktree", "prune"], cwd=ws.config.root / repo, check=True,
    )
    return sid


def test_switch_to_warm_feature_with_orphaned_repo_worktree_reclaims_slot(
    workspace_with_full_slots,
):
    """Regression: Y is warm but one repo's worktree dir is missing.

    switch(Y) must reclaim Y's vacated slot for the outgoing canonical X
    rather than raising no_free_slot. Exactly the canopy-test failure where
    `billing-export` was warm in worktree-1 but worktree-1/canopy-test-api
    had no .git, so cold-Y allocation found both slots full.
    """
    ws = workspace_with_full_slots  # X canonical; A in wt-1, B in wt-2
    from canopy.actions import slots as sm
    from canopy.actions import prs_cache
    from canopy.actions.switch import switch

    # X (vacating on switch to A) needs an open PR to reclaim A's slot warm
    # under the Phase-4 default; else a clean, PR-less X goes cold.
    prs_cache.write(ws, {"X": {"repos": {"repo-a": {"number": 1, "state": "open"}}}})
    sid = _orphan_repo_worktree(ws, "A", "repo-a")

    # Must NOT raise no_free_slot.
    result = switch(ws, "A")

    assert result["feature"] == "A"
    state = sm.read_state(ws)
    assert state is not None
    assert state.canonical is not None
    assert state.canonical.feature == "A"
    # X reclaimed A's vacated slot; both repo worktrees exist there again.
    assert state.slots[sid].feature == "X"
    assert (sm.slot_worktree_path(ws, sid, "repo-a") / ".git").exists()
    assert (sm.slot_worktree_path(ws, sid, "repo-b") / ".git").exists()
    # B is still warm in its (other) slot — untouched by the A↔X rotation.
    warm = {e.feature: s for s, e in state.slots.items()}
    assert "B" in warm and warm["B"] != sid
    # Clean completion clears any in_flight.
    assert state.in_flight is None


def test_no_free_slot_on_first_repo_does_not_stamp_in_flight(
    workspace_with_canonical_only, monkeypatch,
):
    """A pre-mutation no_free_slot on the first repo must NOT brick the
    workspace with a false in_flight marker.

    The failure happens before any git mutation (allocate_slot is pure), so
    per_repo_completed would be empty — nothing is partially flipped. Stamping
    in_flight there permanently locks out switching via slot_state_inconsistent.
    """
    ws = workspace_with_canonical_only  # X canonical, Y cold
    from canopy.actions import slots as sm
    from canopy.actions import prs_cache
    from canopy.actions.errors import BlockerError
    from canopy.actions.switch import switch

    # X (vacating) needs an open PR so the switch takes the warm cold-Y
    # allocation path (which the patched allocator fails); a clean, PR-less
    # X would go cold under the Phase-4 default and never reach allocate.
    prs_cache.write(ws, {"X": {"repos": {"repo-a": {"number": 1, "state": "open"}}}})

    # Force the cold-Y allocator to fail on the first repo.
    monkeypatch.setattr(
        "canopy.actions.switch.slots_mod.allocate_slot", lambda state: None,
    )

    with pytest.raises(BlockerError) as e:
        switch(ws, "Y")
    assert e.value.code == "no_free_slot"

    state = sm.read_state(ws)
    assert state is not None
    assert state.in_flight is None, (
        "pre-mutation failure on the first repo must not stamp in_flight"
    )
