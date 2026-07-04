"""Tests for observe-as-advisory (unregistered join candidates)."""
from __future__ import annotations

import json
import subprocess


def _ws(root):
    from canopy.workspace.workspace import Workspace
    from canopy.workspace.config import load_config
    return Workspace(load_config(root))


def _register(root, feature, repos):
    fp = root / ".canopy" / "features.json"
    fp.parent.mkdir(exist_ok=True)
    data = json.loads(fp.read_text()) if fp.exists() else {}
    data[feature] = {"repos": repos, "status": "active"}
    fp.write_text(json.dumps(data))


def test_advises_unregistered_repo_on_feature_branch(canopy_toml_for_workspace):
    from canopy.actions.advisories import compute_advisories
    root = canopy_toml_for_workspace
    # auth-flow registered for repo-a ONLY; repo-b is on branch auth-flow but unregistered
    _register(root, "auth-flow", ["repo-a"])
    subprocess.run(["git", "checkout", "auth-flow"], cwd=root / "repo-b",
                   check=True, capture_output=True)
    adv = compute_advisories(_ws(root), "auth-flow")
    codes = [a["code"] for a in adv]
    assert "unregistered_join_candidate" in codes
    assert any(a["repo"] == "repo-b" for a in adv)


def test_no_advisory_when_registered(canopy_toml_for_workspace):
    from canopy.actions.advisories import compute_advisories
    root = canopy_toml_for_workspace
    _register(root, "auth-flow", ["repo-a", "repo-b"])
    subprocess.run(["git", "checkout", "auth-flow"], cwd=root / "repo-b",
                   check=True, capture_output=True)
    adv = compute_advisories(_ws(root), "auth-flow")
    assert all(a["repo"] != "repo-b" for a in adv)


def test_no_active_feature_no_advisories(canopy_toml_for_workspace):
    from canopy.actions.advisories import compute_advisories
    assert compute_advisories(_ws(canopy_toml_for_workspace), None) == []


def test_reclaimable_dirty_folds_into_advisories(workspace_with_slots):
    from canopy.actions.advisories import compute_advisories
    from canopy.actions import prs_cache, slots as sm
    ws = workspace_with_slots
    prs_cache.write(ws, {"Y": {"repos": {"repo-a": {"number": 1, "state": "merged"}}}})
    wt = sm.slot_worktree_path(ws, "worktree-1", "repo-a")
    (wt / "wip.txt").write_text("dirty\n")
    adv = compute_advisories(ws, "X")     # active feature X; Y warm+merged+dirty
    assert any(a["code"] == "reclaimable_but_dirty" for a in adv)
