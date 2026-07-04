"""Tests for the warm-vs-cold slot policy."""
from __future__ import annotations

import json


def _ws(root):
    from canopy.workspace.workspace import Workspace
    from canopy.workspace.config import load_config
    return Workspace(load_config(root))


def _write_prs(root, feature, repo, state):
    from canopy.workspace.workspace import Workspace
    from canopy.workspace.config import load_config
    from canopy.actions import prs_cache
    ws = Workspace(load_config(root))
    prs_cache.write(ws, {feature: {"repos": {repo: {"number": 1, "state": state}}}})


def test_open_pr_means_warm(canopy_toml_for_workspace):
    from canopy.actions.slot_policy import warm_or_cold
    root = canopy_toml_for_workspace
    _write_prs(root, "auth-flow", "repo-a", "open")
    assert warm_or_cold(_ws(root), "auth-flow") == "warm"


def test_merged_pr_no_wip_means_cold(canopy_toml_for_workspace):
    from canopy.actions.slot_policy import warm_or_cold
    root = canopy_toml_for_workspace
    _write_prs(root, "auth-flow", "repo-a", "merged")
    assert warm_or_cold(_ws(root), "auth-flow") == "cold"


def test_dirty_wip_means_warm_even_without_pr(canopy_toml_for_workspace):
    from canopy.actions.slot_policy import warm_or_cold
    import subprocess
    root = canopy_toml_for_workspace
    subprocess.run(["git", "checkout", "auth-flow"], cwd=root / "repo-a",
                   check=True, capture_output=True)
    (root / "repo-a" / "wip.txt").write_text("uncommitted\n")
    assert warm_or_cold(_ws(root), "auth-flow") == "warm"


def test_clean_no_pr_means_cold(canopy_toml_for_workspace):
    from canopy.actions.slot_policy import warm_or_cold
    root = canopy_toml_for_workspace
    assert warm_or_cold(_ws(root), "auth-flow") == "cold"
