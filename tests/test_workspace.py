"""Tests for workspace.workspace and workspace.discovery modules."""
import pytest
from pathlib import Path

from canopy.workspace.config import load_config
from canopy.workspace.workspace import Workspace
from canopy.workspace.discovery import discover_repos, generate_toml


# ── Discovery tests ───────────────────────────────────────────────────────

def test_discover_repos(workspace_dir):
    repos = discover_repos(workspace_dir)

    assert len(repos) == 2
    names = {r.name for r in repos}
    assert "repo-a" in names
    assert "repo-b" in names


def test_discover_repos_detects_language(workspace_dir):
    repos = discover_repos(workspace_dir)
    repo_map = {r.name: r for r in repos}

    assert repo_map["repo-a"].lang == "python"
    # ui has .tsx and .ts files
    assert repo_map["repo-b"].lang in ("typescript", "javascript")


def test_discover_repos_detects_role(workspace_dir):
    repos = discover_repos(workspace_dir)
    repo_map = {r.name: r for r in repos}

    assert repo_map["repo-a"].role == "backend"
    assert repo_map["repo-b"].role == "frontend"


def test_generate_toml(workspace_dir):
    toml_str = generate_toml(workspace_dir, workspace_name="my-project")

    assert '[workspace]' in toml_str
    assert 'name = "my-project"' in toml_str
    assert '[[repos]]' in toml_str
    assert 'name = "repo-a"' in toml_str
    assert 'name = "repo-b"' in toml_str


def test_discover_empty_dir(tmp_path):
    repos = discover_repos(tmp_path)
    assert repos == []


# ── Workspace tests ───────────────────────────────────────────────────────

def test_workspace_basic(canopy_toml):
    config = load_config(canopy_toml)
    ws = Workspace(config)

    assert len(ws.repos) == 2
    assert ws.repos[0].config.name == "repo-a"
    assert ws.repos[0].current_branch == "main"
    assert ws.repos[0].head_sha  # should have a sha


def test_workspace_get_repo(canopy_toml):
    config = load_config(canopy_toml)
    ws = Workspace(config)

    api = ws.get_repo("repo-a")
    assert api.config.name == "repo-a"

    with pytest.raises(KeyError):
        ws.get_repo("nonexistent")


def test_workspace_to_dict(canopy_toml):
    config = load_config(canopy_toml)
    ws = Workspace(config)

    d = ws.to_dict()
    assert d["name"] == "test-workspace"
    assert len(d["repos"]) == 2
    assert "active_features" in d


def test_workspace_active_features_none(canopy_toml):
    """No active features when all repos are on main."""
    config = load_config(canopy_toml)
    ws = Workspace(config)

    features = ws.active_features()
    assert features == []


def test_workspace_active_features(canopy_toml, workspace_with_feature):
    """Detect auth-flow as active feature when both repos have it."""
    config = load_config(workspace_with_feature)
    ws = Workspace(config)

    features = ws.active_features()
    assert "auth-flow" in features


def test_workspace_refresh_enriches(canopy_toml, workspace_with_feature):
    """After refresh, repos on feature branches show divergence."""
    config = load_config(workspace_with_feature)
    ws = Workspace(config)
    ws.refresh()

    api = ws.get_repo("repo-a")
    # api is on auth-flow branch with commits ahead of main
    assert api.current_branch == "auth-flow"
    assert api.ahead_of_default >= 1
