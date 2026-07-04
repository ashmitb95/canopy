"""Tests for the context registry read."""
from __future__ import annotations

import json


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


def test_local_tier_reports_workspace_and_repos(canopy_toml_for_workspace):
    from canopy.actions.registry import context
    root = canopy_toml_for_workspace
    _register(root, "auth-flow", ["repo-a", "repo-b"])
    ctx = context(_ws(root))
    assert ctx["workspace"]["name"]
    feat = ctx["features"]["auth-flow"]
    assert set(feat["repos"]) == {"repo-a", "repo-b"}
    assert feat["repos"]["repo-a"]["branch"] == "auth-flow"
    assert "path" in feat["repos"]["repo-a"]
    assert "dirty" in feat["repos"]["repo-a"]


def test_local_tier_makes_no_network_call(canopy_toml_for_workspace, monkeypatch):
    from canopy.actions import registry
    import canopy.actions.triage as triage
    monkeypatch.setattr(triage, "_fetch_open_prs",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network in tier 1")))
    registry.context(_ws(canopy_toml_for_workspace))  # must not raise


def test_detected_field_reports_cwd_position(canopy_toml_for_workspace):
    from canopy.actions.registry import context
    root = canopy_toml_for_workspace
    _register(root, "auth-flow", ["repo-a", "repo-b"])
    ctx = context(_ws(root), cwd=root / "repo-a")
    assert ctx["detected"]["repo"] == "repo-a"


def test_slots_reported(workspace_with_slots):
    from canopy.actions.registry import context
    ctx = context(workspace_with_slots)
    assert "worktree-1" in ctx["slots"]


def test_remote_false_has_no_pr_key(canopy_toml_for_workspace):
    from canopy.actions.registry import context
    root = canopy_toml_for_workspace
    _register(root, "auth-flow", ["repo-a", "repo-b"])
    ctx = context(_ws(root))
    assert ctx["features"]["auth-flow"]["repos"]["repo-a"].get("pr", "ABSENT") == "ABSENT"
