"""summarize_worktree_dirs — slot-aware worktree reporting for init/reinit.

Wave 3.0 worktree dirs are generic slots (worktree-N); their occupant
feature lives in slots.json. The summary must resolve slot → feature, not
report the slot id as if it were a feature name (the Axis-1 bug).
"""
from __future__ import annotations

import json

from canopy.workspace.discovery import summarize_worktree_dirs


def test_summarize_resolves_slot_id_to_feature(workspace_with_slots):
    """A 3.0 slot dir is keyed by its occupant feature, not the slot id."""
    root = workspace_with_slots.config.root
    summary = summarize_worktree_dirs(root)
    # Y occupies worktree-1 → keyed by "Y", NOT "worktree-1".
    assert "Y" in summary
    assert "worktree-1" not in summary
    assert set(summary["Y"]) == {"repo-a", "repo-b"}


def test_summarize_orphan_slot_falls_back_to_slot_id(workspace_with_slots):
    """A slot dir with no occupant in slots.json keys by the slot id."""
    import shutil
    from canopy.actions import slots as sm

    root = workspace_with_slots.config.root
    # Drop Y's slot entry from slots.json but leave the dir → orphan slot.
    state = sm.read_state(workspace_with_slots)
    state.slots.clear()
    sm.write_state(workspace_with_slots, state)

    summary = summarize_worktree_dirs(root)
    assert "worktree-1" in summary  # no feature to resolve → slot id key
    assert "Y" not in summary


def test_summarize_legacy_feature_named_dirs(tmp_path):
    """Pre-3.0 feature-named dirs (no slots.json) map directly."""
    wt = tmp_path / ".canopy" / "worktrees" / "auth-flow"
    (wt / "repo-a").mkdir(parents=True)
    (wt / "repo-b").mkdir(parents=True)
    summary = summarize_worktree_dirs(tmp_path)
    assert summary == {"auth-flow": ["repo-a", "repo-b"]}


def test_summarize_empty_when_no_worktrees(tmp_path):
    assert summarize_worktree_dirs(tmp_path) == {}
