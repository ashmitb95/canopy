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


def test_remote_overlay_merges_pr(canopy_toml_for_workspace, monkeypatch):
    from canopy.actions import registry
    root = canopy_toml_for_workspace
    _register(root, "auth-flow", ["repo-a", "repo-b"])
    import canopy.actions.triage as triage
    monkeypatch.setattr(triage, "_fetch_open_prs", lambda ws, repos, author: {
        "repo-a": [{"head_branch": "auth-flow", "number": 7, "url": "u",
                    "state": "open", "review_decision": "APPROVED"}],
        "repo-b": [],
    })
    ctx = registry.context(_ws(root), remote=True)
    pr = ctx["features"]["auth-flow"]["repos"]["repo-a"]["pr"]
    assert pr["number"] == 7 and pr["review_decision"] == "APPROVED"


def test_remote_overlay_adds_checks_summary(canopy_toml_for_workspace, monkeypatch):
    from canopy.actions import registry
    root = canopy_toml_for_workspace
    _register(root, "auth-flow", ["repo-a", "repo-b"])
    import canopy.actions.triage as triage
    monkeypatch.setattr(triage, "_fetch_open_prs", lambda ws, repos, author: {
        "repo-a": [{"head_branch": "auth-flow", "number": 7, "url": "u",
                    "state": "open", "review_decision": "APPROVED"}],
        "repo-b": [],
    })
    import canopy.actions.aliases as aliases
    monkeypatch.setattr(aliases, "_resolve_owner_slug", lambda ws, repo: ("acme", repo))
    import canopy.integrations.github as gh
    monkeypatch.setattr(gh, "get_pr_checks", lambda root, owner, slug, num: (
        {"status": "passing", "passed": 3, "failing": 0, "pending": 0}, []))
    ctx = registry.context(_ws(root), remote=True)
    pr = ctx["features"]["auth-flow"]["repos"]["repo-a"]["pr"]
    assert pr["checks_summary"]["status"] == "passing"


def test_remote_overlay_falls_back_to_cache_when_offline(canopy_toml_for_workspace, monkeypatch):
    from canopy.actions import registry, prs_cache
    root = canopy_toml_for_workspace
    _register(root, "auth-flow", ["repo-a", "repo-b"])
    ws = _ws(root)
    prs_cache.write(ws, {"auth-flow": {"repos": {"repo-a": {"number": 9, "state": "open"}}}})
    import canopy.actions.triage as triage
    monkeypatch.setattr(triage, "_fetch_open_prs",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    ctx = registry.context(ws, remote=True)
    assert ctx["remote"]["stale"] is True
    assert ctx["features"]["auth-flow"]["repos"]["repo-a"]["pr"]["number"] == 9
    assert ctx["remote"]["fetched_at"]  # non-empty string stamped by prs_cache.write
