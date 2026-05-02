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
    assert "repo-a" in lane.repos
    assert "repo-b" in lane.repos
    assert lane.status == "active"
    assert lane.created_at

    # Branches should exist in both repos
    api = ws.get_repo("repo-a")
    ui = ws.get_repo("repo-b")
    assert branch_exists(api.abs_path, "new-feature")
    assert branch_exists(ui.abs_path, "new-feature")


def test_create_feature_subset(canopy_toml):
    config = load_config(canopy_toml)
    ws = Workspace(config)
    coord = FeatureCoordinator(ws)

    lane = coord.create("api-only", repos=["repo-a"])

    assert lane.repos == ["repo-a"]
    api = ws.get_repo("repo-a")
    ui = ws.get_repo("repo-b")
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


def test_feature_status(canopy_toml, workspace_with_feature):
    config = load_config(workspace_with_feature)
    ws = Workspace(config)
    coord = FeatureCoordinator(ws)

    lane = coord.status("auth-flow")

    assert lane.name == "auth-flow"
    assert "repo-a" in lane.repo_states
    assert "repo-b" in lane.repo_states

    # Both repos should show the branch exists
    assert lane.repo_states["repo-a"]["has_branch"] is True
    assert lane.repo_states["repo-b"]["has_branch"] is True

    # Both should be ahead of main
    assert lane.repo_states["repo-a"]["ahead"] >= 1
    assert lane.repo_states["repo-b"]["ahead"] >= 1


def test_feature_diff(canopy_toml, workspace_with_feature):
    config = load_config(workspace_with_feature)
    ws = Workspace(config)
    coord = FeatureCoordinator(ws)

    diff = coord.diff("auth-flow")

    assert diff["feature"] == "auth-flow"
    assert diff["summary"]["participating_repos"] == 2
    assert diff["summary"]["total_files_changed"] > 0

    # api should have changed files
    api_diff = diff["repos"]["repo-a"]
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


def test_feature_changes(canopy_toml, workspace_with_feature):
    config = load_config(workspace_with_feature)
    ws = Workspace(config)
    coord = FeatureCoordinator(ws)

    result = coord.feature_changes("auth-flow")

    assert result["feature"] == "auth-flow"
    assert "repo-a" in result["repos"]
    assert "repo-b" in result["repos"]

    api = result["repos"]["repo-a"]
    assert api["has_branch"] is True
    api_paths = {c["path"]: c["status"] for c in api["changes"]}
    assert "src/auth.py" in api_paths and api_paths["src/auth.py"] == "A"
    assert "src/models.py" in api_paths and api_paths["src/models.py"] == "M"

    ui = result["repos"]["repo-b"]
    ui_paths = {c["path"]: c["status"] for c in ui["changes"]}
    assert "src/Login.tsx" in ui_paths and ui_paths["src/Login.tsx"] == "A"
    assert "src/types.ts" in ui_paths and ui_paths["src/types.ts"] == "M"


def test_feature_changes_includes_uncommitted(canopy_toml, workspace_with_feature):
    """Uncommitted edits in a worktree should appear in feature_changes."""
    config = load_config(workspace_with_feature)
    ws = Workspace(config)
    coord = FeatureCoordinator(ws)

    api = ws.get_repo("repo-a")
    # workspace_with_feature leaves api on auth-flow with a clean tree;
    # add an uncommitted edit + an untracked file.
    (api.abs_path / "src" / "models.py").write_text(
        "class User:\n    name: str\n    email: str\n    token: str\n    role: str\n"
    )
    (api.abs_path / "src" / "scratch.py").write_text("# wip\n")

    result = coord.feature_changes("auth-flow")
    api_paths = {c["path"]: c["status"] for c in result["repos"]["repo-a"]["changes"]}
    # Path must be preserved exactly — porcelain output has leading spaces
    # that `.strip()` would clobber (reported paths like "rc/scratch.py").
    assert "src/scratch.py" in api_paths and api_paths["src/scratch.py"] == "?"
    assert api_paths.get("src/models.py") in {"M"}


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
        coord.create("SIN-100-exact-match")
        assert coord._resolve_name("SIN-100-exact-match") == "SIN-100-exact-match"

    def test_prefix_match(self, canopy_toml):
        config = load_config(canopy_toml)
        ws = Workspace(config)
        coord = FeatureCoordinator(ws)
        coord.create("SIN-200-add-login")
        assert coord._resolve_name("SIN-200") == "SIN-200-add-login"

    def test_linear_issue_match(self, canopy_toml):
        config = load_config(canopy_toml)
        ws = Workspace(config)
        coord = FeatureCoordinator(ws)
        coord.create("SIN-300-payment", linear_issue="SIN-300", linear_title="Payment")
        assert coord._resolve_name("SIN-300") == "SIN-300-payment"

    def test_linear_issue_case_insensitive(self, canopy_toml):
        config = load_config(canopy_toml)
        ws = Workspace(config)
        coord = FeatureCoordinator(ws)
        coord.create("sin-400-auth", linear_issue="SIN-400", linear_title="Auth")
        assert coord._resolve_name("sin-400") == "sin-400-auth"

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

    def test_done_with_alias(self, workspace_with_feature, canopy_toml):
        """End-to-end: canopy done works with a prefix alias."""
        config = load_config(canopy_toml)
        ws = Workspace(config)
        coord = FeatureCoordinator(ws)
        coord.create("SIN-600-cleanup", use_worktrees=True)
        result = coord.done("SIN-600", force=True)
        assert result["feature"] == "SIN-600-cleanup"


class TestLinkLinearIssue:
    """Tests for coordinator.link_linear_issue — attaches an issue from
    the workspace's configured provider to an existing lane.

    After M5 the method routes through the provider registry; tests mock
    ``canopy.providers.get_issue_provider`` and pass back canonical
    ``Issue`` instances rather than raw Linear dicts."""

    def _patch_provider(self, monkeypatch, fake_issue):
        from unittest.mock import MagicMock
        provider = MagicMock()
        provider.get_issue.return_value = fake_issue
        monkeypatch.setattr(
            "canopy.features.coordinator.get_issue_provider",
            lambda _ws: provider,
        )
        return provider

    def test_happy_path(self, canopy_toml, monkeypatch):
        from canopy.providers.types import Issue

        config = load_config(canopy_toml)
        ws = Workspace(config)
        coord = FeatureCoordinator(ws)
        coord.create("payment-flow")

        fake_issue = Issue(
            id="SIN-777", identifier="SIN-777",
            title="Add Stripe webhook", state="todo",
            url="https://linear.app/x/SIN-777",
        )
        self._patch_provider(monkeypatch, fake_issue)

        lane = coord.link_linear_issue("payment-flow", "SIN-777")
        assert lane.linear_issue == "SIN-777"
        assert lane.linear_title == "Add Stripe webhook"
        assert lane.linear_url == "https://linear.app/x/SIN-777"

        features_path = canopy_toml / ".canopy" / "features.json"
        persisted = json.loads(features_path.read_text())
        assert persisted["payment-flow"]["linear_issue"] == "SIN-777"
        assert persisted["payment-flow"]["linear_title"] == "Add Stripe webhook"

    def test_unknown_feature_raises(self, canopy_toml, monkeypatch):
        from canopy.providers.types import Issue

        config = load_config(canopy_toml)
        ws = Workspace(config)
        coord = FeatureCoordinator(ws)

        self._patch_provider(monkeypatch, Issue(id="x", identifier="x", title="x"))

        with pytest.raises(ValueError, match="not found in features.json"):
            coord.link_linear_issue("nonexistent-feature", "SIN-123")

    def test_linear_not_configured_propagates(self, canopy_toml):
        from canopy.providers.types import ProviderNotConfigured

        config = load_config(canopy_toml)
        ws = Workspace(config)
        coord = FeatureCoordinator(ws)
        coord.create("needs-linking")

        # No mcps.json → provider raises ProviderNotConfigured, which
        # should bubble up so the caller can surface a helpful message.
        with pytest.raises(ProviderNotConfigured):
            coord.link_linear_issue("needs-linking", "SIN-123")

    def test_alias_resolution(self, canopy_toml, monkeypatch):
        """Linking with a prefix alias resolves to the full feature name."""
        from canopy.providers.types import Issue

        config = load_config(canopy_toml)
        ws = Workspace(config)
        coord = FeatureCoordinator(ws)
        coord.create("SIN-900-long-name")

        fake_issue = Issue(
            id="SIN-900", identifier="SIN-900",
            title="Linked later", state="in_progress",
            url="https://linear.app/x/SIN-900",
        )
        self._patch_provider(monkeypatch, fake_issue)

        lane = coord.link_linear_issue("SIN-900", "SIN-900")
        assert lane.name == "SIN-900-long-name"
        assert lane.linear_issue == "SIN-900"
