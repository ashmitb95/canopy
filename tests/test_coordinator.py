"""Tests for features.coordinator module."""
import json
import pytest
from pathlib import Path

from canopy.workspace.config import load_config
from canopy.workspace.workspace import Workspace
from canopy.features.coordinator import FeatureCoordinator, FeatureLane
from canopy.git.repo import branches, current_branch, branch_exists


def test_create_feature(canopy_toml):
    config = load_config(canopy_toml)
    ws = Workspace(config)
    coord = FeatureCoordinator(ws)

    lane = coord.create("new-feature")

    assert lane.name == "new-feature"
    assert "api" in lane.repos
    assert "ui" in lane.repos
    assert lane.status == "active"
    assert lane.created_at

    # Branches should exist in both repos
    api = ws.get_repo("api")
    ui = ws.get_repo("ui")
    assert branch_exists(api.abs_path, "new-feature")
    assert branch_exists(ui.abs_path, "new-feature")


def test_create_feature_subset(canopy_toml):
    config = load_config(canopy_toml)
    ws = Workspace(config)
    coord = FeatureCoordinator(ws)

    lane = coord.create("api-only", repos=["api"])

    assert lane.repos == ["api"]
    api = ws.get_repo("api")
    ui = ws.get_repo("ui")
    assert branch_exists(api.abs_path, "api-only")
    assert not branch_exists(ui.abs_path, "api-only")


def test_create_feature_unknown_repo(canopy_toml):
    config = load_config(canopy_toml)
    ws = Workspace(config)
    coord = FeatureCoordinator(ws)

    with pytest.raises(ValueError, match="Unknown repos"):
        coord.create("bad", repos=["nonexistent"])


def test_list_active(canopy_toml):
    config = load_config(canopy_toml)
    ws = Workspace(config)
    coord = FeatureCoordinator(ws)

    coord.create("feat-a")
    coord.create("feat-b")

    lanes = coord.list_active()
    names = {l.name for l in lanes}
    assert "feat-a" in names
    assert "feat-b" in names


def test_switch_feature(canopy_toml):
    config = load_config(canopy_toml)
    ws = Workspace(config)
    coord = FeatureCoordinator(ws)

    coord.create("switch-test")
    result = coord.switch("switch-test")

    assert result["feature"] == "switch-test"
    assert result["repos"]["api"]["ok"] is True
    assert result["repos"]["ui"]["ok"] is True
    assert result["repos"]["api"]["branch"] == "switch-test"
    assert isinstance(result["repos"]["api"]["path"], str)
    assert isinstance(result["repos"]["api"]["dirty_count"], int)

    # Verify branches are checked out
    ws.refresh()
    api = ws.get_repo("api")
    ui = ws.get_repo("ui")
    assert api.current_branch == "switch-test"
    assert ui.current_branch == "switch-test"


def test_switch_nonexistent(canopy_toml):
    config = load_config(canopy_toml)
    ws = Workspace(config)
    coord = FeatureCoordinator(ws)

    with pytest.raises(ValueError, match="not found"):
        coord.switch("nonexistent")


def test_feature_status(canopy_toml, workspace_with_feature):
    config = load_config(workspace_with_feature)
    ws = Workspace(config)
    coord = FeatureCoordinator(ws)

    lane = coord.status("auth-flow")

    assert lane.name == "auth-flow"
    assert "api" in lane.repo_states
    assert "ui" in lane.repo_states

    # Both repos should show the branch exists
    assert lane.repo_states["api"]["has_branch"] is True
    assert lane.repo_states["ui"]["has_branch"] is True

    # Both should be ahead of main
    assert lane.repo_states["api"]["ahead"] >= 1
    assert lane.repo_states["ui"]["ahead"] >= 1


def test_feature_diff(canopy_toml, workspace_with_feature):
    config = load_config(workspace_with_feature)
    ws = Workspace(config)
    coord = FeatureCoordinator(ws)

    diff = coord.diff("auth-flow")

    assert diff["feature"] == "auth-flow"
    assert diff["summary"]["participating_repos"] == 2
    assert diff["summary"]["total_files_changed"] > 0

    # api should have changed files
    api_diff = diff["repos"]["api"]
    assert api_diff["has_branch"] is True
    assert len(api_diff["changed_files"]) >= 1


def test_feature_diff_type_overlaps(canopy_toml, workspace_with_feature):
    config = load_config(workspace_with_feature)
    ws = Workspace(config)
    coord = FeatureCoordinator(ws)

    diff = coord.diff("auth-flow")

    # Both api/src/models.py and ui/src/types.ts were modified,
    # but they have different basenames so no overlap.
    # However, types.ts has basename "types" and models.py has "models" — no match.
    # This test verifies the overlap detection runs without error.
    assert isinstance(diff["type_overlaps"], list)


def test_merge_readiness(canopy_toml, workspace_with_feature):
    config = load_config(workspace_with_feature)
    ws = Workspace(config)
    coord = FeatureCoordinator(ws)

    readiness = coord.merge_readiness("auth-flow")

    assert readiness["feature"] == "auth-flow"
    assert isinstance(readiness["ready"], bool)
    assert isinstance(readiness["issues"], list)


def test_features_persisted(canopy_toml):
    config = load_config(canopy_toml)
    ws = Workspace(config)
    coord = FeatureCoordinator(ws)

    coord.create("persist-test")

    # Load features.json directly
    features_path = canopy_toml / ".canopy" / "features.json"
    assert features_path.exists()

    data = json.loads(features_path.read_text())
    assert "persist-test" in data
    assert data["persist-test"]["status"] == "active"


def test_feature_to_dict(canopy_toml):
    config = load_config(canopy_toml)
    ws = Workspace(config)
    coord = FeatureCoordinator(ws)

    coord.create("dict-test")
    lane = coord.status("dict-test")
    d = lane.to_dict()

    assert d["name"] == "dict-test"
    assert "repos" in d
    assert "repo_states" in d
    assert "status" in d


# ── Alias resolution ──────────────────────────────────────────────────

class TestResolveAlias:
    def test_exact_match(self, canopy_toml):
        config = load_config(canopy_toml)
        ws = Workspace(config)
        coord = FeatureCoordinator(ws)
        coord.create("ENG-100-exact-match")
        assert coord._resolve_name("ENG-100-exact-match") == "ENG-100-exact-match"

    def test_prefix_match(self, canopy_toml):
        config = load_config(canopy_toml)
        ws = Workspace(config)
        coord = FeatureCoordinator(ws)
        coord.create("ENG-200-add-login")
        assert coord._resolve_name("ENG-200") == "ENG-200-add-login"

    def test_linear_issue_match(self, canopy_toml):
        config = load_config(canopy_toml)
        ws = Workspace(config)
        coord = FeatureCoordinator(ws)
        coord.create("ENG-300-payment", linear_issue="ENG-300", linear_title="Payment")
        assert coord._resolve_name("ENG-300") == "ENG-300-payment"

    def test_linear_issue_case_insensitive(self, canopy_toml):
        config = load_config(canopy_toml)
        ws = Workspace(config)
        coord = FeatureCoordinator(ws)
        coord.create("eng-400-auth", linear_issue="ENG-400", linear_title="Auth")
        assert coord._resolve_name("eng-400") == "eng-400-auth"

    def test_ambiguous_prefix_raises(self, canopy_toml):
        config = load_config(canopy_toml)
        ws = Workspace(config)
        coord = FeatureCoordinator(ws)
        coord.create("shared-prefix-a")
        coord.create("shared-prefix-b")
        with pytest.raises(ValueError, match="Ambiguous"):
            coord._resolve_name("shared-prefix")

    def test_no_match_returns_as_is(self, canopy_toml):
        config = load_config(canopy_toml)
        ws = Workspace(config)
        coord = FeatureCoordinator(ws)
        assert coord._resolve_name("nonexistent") == "nonexistent"

    def test_switch_with_alias(self, canopy_toml):
        """End-to-end: canopy switch works with a Linear ID alias."""
        config = load_config(canopy_toml)
        ws = Workspace(config)
        coord = FeatureCoordinator(ws)
        coord.create("ENG-500-refactor-api", linear_issue="ENG-500")
        result = coord.switch("ENG-500")
        assert result["feature"] == "ENG-500-refactor-api"
        assert result["alias"] == "ENG-500"
        assert result["repos"]["api"]["ok"] is True
        assert result["repos"]["api"]["branch"] == "ENG-500-refactor-api"

    def test_done_with_alias(self, workspace_with_feature, canopy_toml):
        """End-to-end: canopy done works with a prefix alias."""
        config = load_config(canopy_toml)
        ws = Workspace(config)
        coord = FeatureCoordinator(ws)
        coord.create("ENG-600-cleanup", use_worktrees=True)
        result = coord.done("ENG-600", force=True)
        assert result["feature"] == "ENG-600-cleanup"
