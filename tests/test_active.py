"""Tests for the active-feature pointer (active.json)."""
from __future__ import annotations


def _ws(root):
    from canopy.workspace.workspace import Workspace
    from canopy.workspace.config import load_config
    return Workspace(load_config(root))


def test_default_is_none(canopy_toml):
    from canopy.actions import active
    assert active.get_active(_ws(canopy_toml)) is None


def test_set_then_get(canopy_toml):
    from canopy.actions import active
    ws = _ws(canopy_toml)
    active.set_active(ws, "DOC-3029")
    assert active.get_active(ws) == "DOC-3029"


def test_clear(canopy_toml):
    from canopy.actions import active
    ws = _ws(canopy_toml)
    active.set_active(ws, "DOC-3029")
    active.clear_active(ws)
    assert active.get_active(ws) is None
