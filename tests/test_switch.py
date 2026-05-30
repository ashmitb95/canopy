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
    from canopy.actions.switch import switch

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
