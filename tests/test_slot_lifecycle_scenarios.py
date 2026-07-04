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


def test_preflight_aggregates_all_repo_issues_before_mutation(
        workspace_with_canonical_only):
    from canopy.actions.errors import BlockerError
    ws = workspace_with_canonical_only
    # Hold an index.lock in repo-b so preflight must fail — and assert NO
    # mutation happened (X still canonical, no in_flight).
    lock = ws.config.root / "repo-b" / ".git" / "index.lock"
    lock.write_text("")
    try:
        with pytest.raises(BlockerError) as e:
            switch(ws, "Y")
        assert "repo-b" in str(e.value.what) or "index_lock" in str(e.value.details)
        state = sm.read_state(ws)
        assert state.canonical.feature == "X"    # untouched
        assert state.in_flight is None
    finally:
        lock.unlink(missing_ok=True)


def test_cap_full_raises_choice_blocker(workspace_with_full_slots):
    import io
    from rich.console import Console
    from canopy.actions.errors import BlockerError
    from canopy.actions import prs_cache
    from canopy.cli.render import render_blocker
    ws = workspace_with_full_slots              # slots=2, both warm (A,B), X canonical
    # X vacates and wants warm (open PR), but both slots are occupied.
    # NOTE: promote the *cold* feature Y (not warm A/B) — promoting a warm
    # feature frees its slot, so the cap wouldn't fire. Y cold → X evacuates
    # warm while A+B stay warm → 3 > cap 2 → cap fires.
    prs_cache.write(ws, {"X": {"repos": {"repo-a": {"number": 9, "state": "open"}}}})
    with pytest.raises(BlockerError) as e:
        switch(ws, "Y")                         # promote cold feature Y; X must evacuate
    assert e.value.code == "worktree_cap_reached"

    # The three choices must render as RUNNABLE canopy commands.
    actions = {fa.action for fa in e.value.fix_actions}
    assert actions == {"config", "switch"}      # switch appears twice
    assert "warm_features" in (e.value.details or {})

    buf = io.StringIO()
    render_blocker(e.value, action="switch",
                   console=Console(file=buf, width=200, force_terminal=False))
    rendered = buf.getvalue()
    assert "canopy config slots 3" in rendered          # raise-cap choice
    assert "canopy switch Y --release-current" in rendered  # send-cold choice
    assert "canopy switch Y --evict " in rendered       # evict-LRU choice
    # No fix command may carry an underscore flag (real flags use dashes).
    for line in rendered.splitlines():
        if "canopy " in line:
            assert "--" not in line or "_" not in line.split("--", 1)[1].split()[0]


def test_cap_full_explicit_evict_proceeds(workspace_with_full_slots):
    from canopy.actions import prs_cache
    ws = workspace_with_full_slots
    prs_cache.write(ws, {"X": {"repos": {"repo-a": {"number": 9, "state": "open"}}}})
    # promote Y, explicitly evicting B to make room — must NOT raise
    result = switch(ws, "Y", evict="B")
    assert result["feature"] == "Y"
