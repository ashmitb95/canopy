"""Tests for reclaim-as-vacate (slot freed on PR merge)."""
from __future__ import annotations


def _ws(root):
    from canopy.workspace.workspace import Workspace
    from canopy.workspace.config import load_config
    return Workspace(load_config(root))


def test_clean_merged_slot_is_vacated(workspace_with_slots):
    from canopy.actions import reclaim, slots as sm, prs_cache
    from canopy.git import repo as git
    ws = workspace_with_slots                 # Y warm in worktree-1
    prs_cache.write(ws, {"Y": {"repos": {"repo-a": {"number": 1, "state": "merged"},
                                         "repo-b": {"number": 2, "state": "merged"}}}})
    result = reclaim.reclaim_merged(ws)
    assert "Y" in result["freed"]
    state = sm.read_state(ws)
    assert all(e.feature != "Y" for e in state.slots.values())   # slot freed
    wt = sm.slot_worktree_path(ws, "worktree-1", "repo-a")
    assert git.current_branch(wt) == ws.get_repo("repo-a").config.default_branch


def test_dirty_merged_slot_is_advised_not_vacated(workspace_with_slots):
    from canopy.actions import reclaim, slots as sm, prs_cache
    ws = workspace_with_slots
    prs_cache.write(ws, {"Y": {"repos": {"repo-a": {"number": 1, "state": "merged"}}}})
    wt = sm.slot_worktree_path(ws, "worktree-1", "repo-a")
    (wt / "wip.txt").write_text("uncommitted\n")
    result = reclaim.reclaim_merged(ws)
    assert "Y" not in result["freed"]
    assert any(a["feature"] == "Y" for a in result["advisories"])
    assert any(e.feature == "Y" for e in sm.read_state(ws).slots.values())  # still warm


def test_open_pr_not_reclaimed(workspace_with_slots):
    from canopy.actions import reclaim, prs_cache
    ws = workspace_with_slots
    prs_cache.write(ws, {"Y": {"repos": {"repo-a": {"number": 1, "state": "open"}}}})
    result = reclaim.reclaim_merged(ws)
    assert result["freed"] == []


def test_reclaimable_advisories_read_only(workspace_with_slots):
    """The advisory-only variant detects dirty-merged without side effects."""
    from canopy.actions import reclaim, slots as sm, prs_cache
    ws = workspace_with_slots
    prs_cache.write(ws, {"Y": {"repos": {"repo-a": {"number": 1, "state": "merged"}}}})
    wt = sm.slot_worktree_path(ws, "worktree-1", "repo-a")
    (wt / "wip.txt").write_text("dirty\n")
    adv = reclaim.reclaimable_advisories(ws)
    assert any(a["code"] == "reclaimable_but_dirty" and a["feature"] == "Y" for a in adv)
    # no mutation
    assert any(e.feature == "Y" for e in sm.read_state(ws).slots.values())
