"""Tests for actions/last_visit.py."""
import time

from canopy.management.last_visit import (
    get_last_visit,
    mark_visited,
    reset_anchor,
)
from canopy.workspace.config import load_config
from canopy.workspace.workspace import Workspace


def _load_workspace(canopy_toml):
    """Load a workspace from the canopy.toml fixture root."""
    return Workspace(load_config(canopy_toml))


def test_get_last_visit_returns_none_when_missing(canopy_toml):
    """get_last_visit returns None for a feature that hasn't been visited."""
    ws = _load_workspace(canopy_toml)
    assert get_last_visit(ws, "auth-flow") is None


def test_mark_visited_roundtrip(canopy_toml):
    """mark_visited stores and retrieves a visit entry."""
    ws = _load_workspace(canopy_toml)
    ts = mark_visited(ws, "auth-flow")
    got = get_last_visit(ws, "auth-flow")
    assert got["last_visit"] == ts
    assert got["previous_visit"] is None


def test_mark_visited_bumps_previous(canopy_toml):
    """mark_visited carries previous last_visit to previous_visit."""
    ws = _load_workspace(canopy_toml)
    ts1 = mark_visited(ws, "auth-flow")
    ts2 = mark_visited(ws, "auth-flow")
    got = get_last_visit(ws, "auth-flow")
    assert got["last_visit"] == ts2
    assert got["previous_visit"] == ts1


def test_reset_anchor(canopy_toml):
    """reset_anchor removes a feature entry and returns True if it existed."""
    ws = _load_workspace(canopy_toml)
    mark_visited(ws, "auth-flow")
    result = reset_anchor(ws, "auth-flow")
    assert result is True
    assert get_last_visit(ws, "auth-flow") is None


def test_reset_anchor_returns_false_when_missing(canopy_toml):
    """reset_anchor returns False if the feature doesn't exist."""
    ws = _load_workspace(canopy_toml)
    result = reset_anchor(ws, "nonexistent")
    assert result is False


def test_mark_visited_increases_monotonically(canopy_toml):
    """Two consecutive mark_visited calls produce strictly increasing timestamps."""
    ws = _load_workspace(canopy_toml)
    ts1 = mark_visited(ws, "auth-flow")
    time.sleep(1.1)  # Sleep 1.1s to ensure second boundary crossed
    ts2 = mark_visited(ws, "auth-flow")
    assert ts1 < ts2
    got = get_last_visit(ws, "auth-flow")
    assert got["last_visit"] == ts2
    assert got["previous_visit"] == ts1
