"""Tests for wave3 slot-aware switch preflight.

Coverage:
  - cap fires + no_evict=True → BlockerError(worktree_cap_reached)
  - LRU eviction candidate is derived from slots last_touched (oldest wins)

Fixtures (workspace_with_canonical_only, workspace_with_full_slots,
workspace_with_two_warm) live in conftest.py.
"""
from __future__ import annotations

import subprocess

import pytest


# ── tests ───────────────────────────────────────────────────────────────────

def test_preflight_cap_uses_workspace_slots_value(workspace_with_two_warm):
    """When slots=2 and 2 are already warm, switching a fresh feature fires cap."""
    ws = workspace_with_two_warm  # slots=2, both filled by A and B
    from canopy.actions.switch_preflight import preflight
    from canopy.actions.errors import BlockerError

    # Create branch C so preflight doesn't trip on missing-branch for wrong reason
    for repo in ("repo-a", "repo-b"):
        subprocess.run(["git", "branch", "C"],
                       cwd=ws.config.root / repo, check=True)

    repo_branches = {"repo-a": "C", "repo-b": "C"}
    with pytest.raises(BlockerError) as exc_info:
        preflight(ws, "C", repo_branches, no_evict=True)
    assert exc_info.value.code == "worktree_cap_reached"


def test_preflight_lru_candidate_from_slots_last_touched(workspace_with_two_warm):
    """preflight returns lru_eviction_candidate == 'B' (the older slot occupant)."""
    ws = workspace_with_two_warm  # last_touched: A newer, B older
    from canopy.actions.switch_preflight import preflight

    for repo in ("repo-a", "repo-b"):
        subprocess.run(["git", "branch", "C"],
                       cwd=ws.config.root / repo, check=True)

    info = preflight(ws, "C", {"repo-a": "C", "repo-b": "C"})
    assert info["cap_will_fire"] is True
    assert info["lru_eviction_candidate"] == "B"
