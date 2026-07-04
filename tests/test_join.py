"""Tests for canopy join (lazy repo join)."""
from __future__ import annotations

import json
import pytest


def _ws(root):
    from canopy.workspace.workspace import Workspace
    from canopy.workspace.config import load_config
    return Workspace(load_config(root))


def _seed_active(root, feature):
    (root / ".canopy" / "state").mkdir(parents=True, exist_ok=True)
    (root / ".canopy" / "state" / "active.json").write_text(json.dumps({"active_feature": feature}))
    fp = root / ".canopy" / "features.json"
    data = json.loads(fp.read_text()) if fp.exists() else {}
    data.setdefault(feature, {"repos": [], "status": "active"})
    fp.write_text(json.dumps(data))


def test_join_creates_branch_and_registers(canopy_toml_for_workspace):
    from canopy.actions.join import join
    from canopy.features.coordinator import FeatureCoordinator
    from canopy.git import repo as git
    root = canopy_toml_for_workspace
    _seed_active(root, "newfeat")
    ws = _ws(root)
    result = join(ws, "repo-a")
    assert result["repo"] == "repo-a"
    assert git.branch_exists(root / "repo-a", "newfeat")
    feats = FeatureCoordinator(ws)._load_features()
    assert "repo-a" in feats["newfeat"]["repos"]


def test_join_sets_canonical(canopy_toml_for_workspace):
    from canopy.actions.join import join
    from canopy.actions import slots as sm
    root = canopy_toml_for_workspace
    _seed_active(root, "newfeat")
    ws = _ws(root)
    join(ws, "repo-a")
    state = sm.read_state(ws)
    assert state.canonical.feature == "newfeat"


def test_join_no_active_feature_blocks(canopy_toml_for_workspace):
    from canopy.actions.join import join
    from canopy.actions.errors import BlockerError
    with pytest.raises(BlockerError) as e:
        join(_ws(canopy_toml_for_workspace), "repo-a")
    assert e.value.code == "no_active_feature"


def test_join_adopts_existing_branch(canopy_toml_for_workspace):
    import subprocess
    from canopy.actions.join import join
    from canopy.features.coordinator import FeatureCoordinator
    root = canopy_toml_for_workspace
    _seed_active(root, "auth-flow")   # branch auth-flow already exists in repo-a
    ws = _ws(root)
    result = join(ws, "repo-a")       # must adopt, not error
    assert result["repo"] == "repo-a"
    feats = FeatureCoordinator(ws)._load_features()
    assert "repo-a" in feats["auth-flow"]["repos"]


def test_join_idempotent(canopy_toml_for_workspace):
    from canopy.actions.join import join
    root = canopy_toml_for_workspace
    _seed_active(root, "newfeat")
    ws = _ws(root)
    join(ws, "repo-a")
    r2 = join(ws, "repo-a")           # no-op
    assert r2["status"] in ("already_joined", "joined")
