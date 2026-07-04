"""Tests for the SessionStart context brief."""
from __future__ import annotations


def test_brief_lists_repos_and_branches(workspace_with_canonical_only):
    from canopy.actions.hook_context import context_brief
    from canopy.workspace.workspace import Workspace
    from canopy.workspace.config import load_config
    # Reload workspace to reflect git state from fixture setup
    ws = Workspace(load_config(workspace_with_canonical_only.config.root))
    brief = context_brief(ws)
    assert "repo-a → X" in brief
    assert "repo-b → X" in brief
    assert "canonical feature: X" in brief


def test_brief_shows_dirty_counts(workspace_with_canonical_only):
    from canopy.actions.hook_context import context_brief
    ws = workspace_with_canonical_only
    (ws.config.root / "repo-a" / "scratch.txt").write_text("dirty\n")
    # Workspace caches repo state at construction — rebuild for live state
    from canopy.workspace.workspace import Workspace
    from canopy.workspace.config import load_config
    brief = context_brief(Workspace(load_config(ws.config.root)))
    assert "1 dirty" in brief


def test_brief_shows_warm_slots(workspace_with_slots):
    from canopy.actions.hook_context import context_brief
    brief = context_brief(workspace_with_slots)
    assert "worktree-1 → Y" in brief


def test_brief_mentions_switch_hint(workspace_with_canonical_only):
    from canopy.actions.hook_context import context_brief
    brief = context_brief(workspace_with_canonical_only)
    assert "canopy switch" in brief


def test_slot_sort_key_orders_numerically():
    from canopy.actions.hook_context import _slot_sort_key
    ids = ["worktree-10", "worktree-2", "worktree-1", "custom-slot"]
    assert sorted(ids, key=_slot_sort_key) == [
        "worktree-1", "worktree-2", "worktree-10", "custom-slot",
    ]
