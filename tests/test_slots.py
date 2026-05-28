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
