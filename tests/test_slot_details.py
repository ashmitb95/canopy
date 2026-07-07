"""T15: rich `slots` shape — single MCP call powers the dashboard."""
from __future__ import annotations


def test_rich_shape_includes_branch_and_dirty(workspace_with_slots):
    from canopy.management.slot_details import rich_slots
    data = rich_slots(workspace_with_slots)
    slot1 = data["slots"]["worktree-1"]
    assert slot1["feature"] == "Y"
    assert "repo-a" in slot1["repos"]
    assert "branch" in slot1["repos"]["repo-a"]
    assert "dirty" in slot1["repos"]["repo-a"]
    assert "ahead" in slot1["repos"]["repo-a"]


def test_rich_shape_empty_slots_are_null(workspace_with_canonical_only):
    from canopy.management.slot_details import rich_slots
    data = rich_slots(workspace_with_canonical_only)
    assert data["slots"]["worktree-1"] is None
    assert data["slots"]["worktree-2"] is None


def test_rich_shape_canonical_carries_repos(workspace_with_slots):
    from canopy.management.slot_details import rich_slots
    data = rich_slots(workspace_with_slots)
    canonical = data["canonical"]
    assert canonical is not None
    assert "repos" in canonical
    assert "feature_state" in canonical
    assert canonical["slot_id"] == "canonical"
    assert canonical["feature"] == "X"


def test_rich_slots_records_errors_from_failed_sources(workspace_with_slots, monkeypatch):
    """When feature_state raises, rich_slots returns the slot with errors populated."""
    from canopy.management import slot_details

    def boom(*a, **k):
        raise RuntimeError("simulated fs crash")

    monkeypatch.setattr("canopy.management.feature_state.feature_state", boom)
    data = slot_details.rich_slots(workspace_with_slots)
    slot1 = data["slots"]["worktree-1"]
    assert isinstance(slot1.get("errors"), list)
    assert any("feature_state" in e.get("source", "") for e in slot1["errors"])
