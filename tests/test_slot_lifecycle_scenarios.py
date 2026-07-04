"""Table-driven slot-lifecycle regression net.

Each scenario drives a real switch/slot transition against the live
fixtures and asserts the resulting slots.json + on-disk state. The two
historical bricking bugs are locked in as the first rows: they are GREEN
now (fixed in 3.1.2) and must never regress. Later phase-4 tasks append
warm-vs-cold / reclaim / cap scenarios.
"""
from __future__ import annotations

import subprocess

import pytest

from canopy.actions.switch import switch
from canopy.actions import slots as sm
from canopy.actions.errors import BlockerError


def test_cold_y_no_free_slot_false_fire_regression(workspace_with_canonical_only):
    """Historical brick #1: cold-Y fall-through must NOT raise no_free_slot
    when the vacating feature's own slot is what X reclaims."""
    from canopy.actions import prs_cache
    ws = workspace_with_canonical_only          # X canonical, Y cold, slots=2
    # X needs an open PR to stay warm under the Phase-4 default (a clean,
    # PR-less X would go cold); the regression here is the evacuation path.
    prs_cache.write(ws, {"X": {"repos": {"repo-a": {"number": 1, "state": "open"}}}})
    result = switch(ws, "Y")                    # must succeed, X → warm slot-1
    assert result["feature"] == "Y"
    state = sm.read_state(ws)
    assert state.canonical.feature == "Y"
    assert any(e.feature == "X" for e in state.slots.values())


def test_clean_noop_failure_does_not_stamp_in_flight_regression(
        workspace_with_canonical_only):
    """Historical brick #2: a precondition failure with nothing mutated must
    NOT leave an in_flight marker (which would brick every later switch)."""
    ws = workspace_with_canonical_only
    with pytest.raises(BlockerError):
        switch(ws, to_slot="worktree-99")       # slot_empty / unknown, pre-mutation
    state = sm.read_state(ws)
    assert state.in_flight is None               # NOT bricked
    # A subsequent legitimate switch still works.
    assert switch(ws, "Y")["feature"] == "Y"


def test_vacating_with_open_pr_goes_warm(workspace_with_canonical_only):
    from canopy.actions import prs_cache
    ws = workspace_with_canonical_only          # X canonical, Y cold
    prs_cache.write(ws, {"X": {"repos": {"repo-a": {"number": 1, "state": "open"}}}})
    switch(ws, "Y")                             # X vacates; has open PR → warm
    state = sm.read_state(ws)
    assert any(e.feature == "X" for e in state.slots.values())   # X is warm


def test_vacating_clean_no_pr_goes_cold(workspace_with_canonical_only):
    ws = workspace_with_canonical_only          # X clean, no PR
    switch(ws, "Y")                             # X vacates → cold (no warm slot)
    state = sm.read_state(ws)
    assert all(e.feature != "X" for e in state.slots.values())   # X NOT warm


def test_release_current_still_forces_cold(workspace_with_canonical_only):
    from canopy.actions import prs_cache
    ws = workspace_with_canonical_only
    prs_cache.write(ws, {"X": {"repos": {"repo-a": {"number": 1, "state": "open"}}}})
    switch(ws, "Y", release_current=True)       # explicit cold overrides policy
    state = sm.read_state(ws)
    assert all(e.feature != "X" for e in state.slots.values())
