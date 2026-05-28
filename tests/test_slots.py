"""Tests for actions/slots.py — slot state read/write + staleness."""
from pathlib import Path

from canopy.actions import slots
from canopy.workspace.workspace import Workspace
from canopy.workspace.config import load_config


def test_read_returns_none_when_missing(canopy_toml):
    ws = Workspace(load_config(canopy_toml))
    assert slots.read_state(ws) is None


def test_write_then_read_roundtrip(canopy_toml):
    ws = Workspace(load_config(canopy_toml))
    # canopy_toml fixture creates repo-a and repo-b as real dirs on disk
    state = slots.SlotState(
        slot_count=2,
        canonical=slots.CanonicalEntry(
            feature="auth-flow",
            activated_at="2026-05-28T10:00:00Z",
            per_repo_paths={"repo-a": str(canopy_toml / "repo-a"),
                             "repo-b": str(canopy_toml / "repo-b")},
        ),
        previous_canonical=None,
        slots={"worktree-1": slots.SlotEntry(
            feature="doc-3010", occupied_at="2026-05-26T14:00:00Z")},
        last_touched={"auth-flow": "2026-05-28T10:00:00Z",
                       "doc-3010": "2026-05-26T14:00:00Z"},
    )
    # worktree-1 dir must exist for read_state to keep the slot
    (canopy_toml / ".canopy" / "worktrees" / "worktree-1").mkdir(parents=True, exist_ok=True)
    slots.write_state(ws, state)
    loaded = slots.read_state(ws)
    assert loaded is not None
    assert loaded.canonical.feature == "auth-flow"
    assert "worktree-1" in loaded.slots
    assert loaded.last_touched["doc-3010"] == "2026-05-26T14:00:00Z"


def test_read_returns_none_if_canonical_path_missing(canopy_toml, tmp_path):
    ws = Workspace(load_config(canopy_toml))
    state = slots.SlotState(
        slot_count=2,
        canonical=slots.CanonicalEntry(
            feature="x", activated_at="2026-05-28T10:00:00Z",
            per_repo_paths={"repo-a": str(tmp_path / "ghost")},
        ),
    )
    slots.write_state(ws, state)
    assert slots.read_state(ws) is None  # path missing → stale


def test_slot_worktree_path(canopy_toml):
    ws = Workspace(load_config(canopy_toml))
    p = slots.slot_worktree_path(ws, "worktree-1", "repo-a")
    assert p == ws.config.root / ".canopy/worktrees/worktree-1/repo-a"


def test_slot_for_feature_returns_warm_slot(canopy_toml):
    ws = Workspace(load_config(canopy_toml))
    # Slot dir must exist on disk for read_state to keep the entry
    (canopy_toml / ".canopy/worktrees/worktree-1").mkdir(parents=True, exist_ok=True)
    state = slots.SlotState(
        slot_count=2,
        slots={"worktree-1": slots.SlotEntry(feature="Y", occupied_at="2026-05-26T14:00:00Z")},
    )
    slots.write_state(ws, state)
    assert slots.slot_for_feature(ws, "Y") == "worktree-1"
    assert slots.slot_for_feature(ws, "Z") is None


def test_allocate_slot_finds_lowest_free_index():
    state = slots.SlotState(
        slot_count=3,
        slots={
            "worktree-1": slots.SlotEntry(feature="A", occupied_at="t1"),
            "worktree-3": slots.SlotEntry(feature="C", occupied_at="t3"),
        },
    )
    assert slots.allocate_slot(state) == "worktree-2"


def test_allocate_slot_returns_none_when_full():
    state = slots.SlotState(
        slot_count=2,
        slots={
            "worktree-1": slots.SlotEntry(feature="A", occupied_at="t"),
            "worktree-2": slots.SlotEntry(feature="B", occupied_at="t"),
        },
    )
    assert slots.allocate_slot(state) is None


def test_lru_evictee_picks_oldest_last_touched():
    state = slots.SlotState(
        slot_count=2,
        slots={
            "worktree-1": slots.SlotEntry(feature="A", occupied_at="t"),
            "worktree-2": slots.SlotEntry(feature="B", occupied_at="t"),
        },
        last_touched={"A": "2026-05-26T00:00:00Z", "B": "2026-05-20T00:00:00Z"},
    )
    assert slots.lru_evictee(state) == "B"


def test_lru_evictee_skips_pinned():
    """An explicit 'pin' set should exclude features from the candidate pool."""
    state = slots.SlotState(
        slot_count=2,
        slots={
            "worktree-1": slots.SlotEntry(feature="A", occupied_at="t"),
            "worktree-2": slots.SlotEntry(feature="B", occupied_at="t"),
        },
        last_touched={"A": "2026-05-26T00:00:00Z", "B": "2026-05-20T00:00:00Z"},
    )
    assert slots.lru_evictee(state, exclude={"B"}) == "A"
