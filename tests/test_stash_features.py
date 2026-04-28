"""Tests for canopy.actions.stash — feature-tagged stashes."""
import json
import os
import subprocess

import pytest

from canopy.actions.errors import BlockerError
from canopy.actions.stash import (
    list_grouped, parse_message, pop_feature, save_for_feature,
)
from canopy.workspace.config import RepoConfig, WorkspaceConfig
from canopy.workspace.workspace import Workspace


def _make_workspace(workspace_dir, repos=("repo-a", "repo-b")) -> Workspace:
    config = WorkspaceConfig(
        name="test",
        repos=[
            RepoConfig(name=name, path=f"./{name}", role="x", lang="x")
            for name in repos
        ],
        root=workspace_dir,
    )
    return Workspace(config)


def _features_file(workspace_dir, payload):
    canopy_dir = workspace_dir / ".canopy"
    canopy_dir.mkdir(exist_ok=True)
    (canopy_dir / "features.json").write_text(json.dumps(payload))


def _make_dirty(repo_path, filename="dirty.txt", content="dirty"):
    (repo_path / filename).write_text(content)


def _git(args, cwd):
    subprocess.run(
        ["git"] + args, cwd=cwd, check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )


# ── parse_message ────────────────────────────────────────────────────────

def test_parse_tagged_message():
    feature, ts, msg = parse_message("[canopy sin-3029 @ 2026-04-25T12:34:56Z] WIP fix")
    assert feature == "sin-3029"
    assert ts == "2026-04-25T12:34:56Z"
    assert msg == "WIP fix"


def test_parse_untagged_message():
    feature, ts, msg = parse_message("WIP on dev: 1234567 something")
    assert feature is None
    assert ts is None
    assert msg == "WIP on dev: 1234567 something"


def test_parse_tag_with_no_user_message():
    feature, ts, msg = parse_message("[canopy sin-3029 @ 2026-04-25T12:34:56Z]")
    assert feature == "sin-3029"
    assert msg == ""


# ── save_for_feature ─────────────────────────────────────────────────────

def test_save_for_feature_writes_tag(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    _make_dirty(workspace_with_feature / "repo-a")
    _make_dirty(workspace_with_feature / "repo-b")

    result = save_for_feature(ws, "auth-flow", "WIP fixes")
    assert result["feature"] == "auth-flow"
    assert "[canopy auth-flow @ " in result["message"]
    assert " WIP fixes" in result["message"]
    assert result["repos"]["repo-a"] == "stashed"
    assert result["repos"]["repo-b"] == "stashed"


def test_save_for_feature_skips_clean_repos(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    _make_dirty(workspace_with_feature / "repo-a")
    # ui stays clean

    result = save_for_feature(ws, "auth-flow", "ui-clean test")
    assert result["repos"]["repo-a"] == "stashed"
    assert result["repos"]["repo-b"] == "clean"


def test_save_for_feature_only_targets_lane_repos(workspace_with_feature):
    """ui-only feature -> stash only ui, not api."""
    _features_file(workspace_with_feature, {
        "ui-only": {"repos": ["repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    _make_dirty(workspace_with_feature / "repo-a")
    _make_dirty(workspace_with_feature / "repo-b")

    result = save_for_feature(ws, "ui-only", "WIP")
    assert "repo-b" in result["repos"]
    assert "repo-a" not in result["repos"]
    assert result["repos"]["repo-b"] == "stashed"


def test_save_with_explicit_repos_override(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    _make_dirty(workspace_with_feature / "repo-a")

    result = save_for_feature(ws, "auth-flow", "api only", repos=["repo-a"])
    assert list(result["repos"].keys()) == ["repo-a"]


def test_save_with_unknown_repo_raises(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        save_for_feature(ws, "auth-flow", "x", repos=["repo-a", "ghost"])
    assert exc_info.value.code == "unknown_repo"


# ── list_grouped ─────────────────────────────────────────────────────────

def test_list_grouped_separates_tagged_and_untagged(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    api_path = workspace_with_feature / "repo-a"

    # Untagged stash via vanilla git: modify a tracked file so vanilla
    # `git stash push` (no -u) actually stashes something.
    (api_path / "src" / "app.py").write_text("modified for untagged stash\n")
    _git(["stash", "push", "-m", "untagged WIP"], cwd=api_path)

    # Tagged stash via canopy
    _make_dirty(api_path, "y.txt")
    save_for_feature(ws, "auth-flow", "tagged WIP", repos=["repo-a"])

    grouped = list_grouped(ws)
    assert "auth-flow" in grouped["by_feature"]
    assert any(e["user_message"] == "tagged WIP" for e in grouped["by_feature"]["auth-flow"])
    assert any("untagged" in e["message"] for e in grouped["untagged"])


def test_list_grouped_filtered_by_feature(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "feat-a": {"repos": ["repo-a"], "status": "active"},
        "feat-b": {"repos": ["repo-a"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)

    _make_dirty(workspace_with_feature / "repo-a", "a.txt")
    save_for_feature(ws, "feat-a", "A work", repos=["repo-a"])
    _make_dirty(workspace_with_feature / "repo-a", "b.txt")
    save_for_feature(ws, "feat-b", "B work", repos=["repo-a"])

    grouped = list_grouped(ws, feature="feat-a")
    assert list(grouped["by_feature"].keys()) == ["feat-a"]
    assert grouped["untagged"] == []  # filter excludes untagged


# ── pop_feature ──────────────────────────────────────────────────────────

def test_pop_feature_pops_matching_stash(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)

    _make_dirty(workspace_with_feature / "repo-a", "stashed.txt", "before-stash")
    save_for_feature(ws, "auth-flow", "WIP", repos=["repo-a"])
    assert not (workspace_with_feature / "repo-a" / "stashed.txt").exists()

    result = pop_feature(ws, "auth-flow", repos=["repo-a"])
    assert result["repos"]["repo-a"]["status"] == "popped"
    assert (workspace_with_feature / "repo-a" / "stashed.txt").exists()


def test_pop_feature_pops_most_recent_when_multiple(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)

    _make_dirty(workspace_with_feature / "repo-a", "first.txt", "first")
    save_for_feature(ws, "auth-flow", "first", repos=["repo-a"])
    _make_dirty(workspace_with_feature / "repo-a", "second.txt", "second")
    save_for_feature(ws, "auth-flow", "second", repos=["repo-a"])

    result = pop_feature(ws, "auth-flow", repos=["repo-a"])
    assert result["repos"]["repo-a"]["status"] == "popped"
    # Most recent stash (lowest index = stash@{0}) is "second"
    assert result["repos"]["repo-a"]["message"] == "second"


def test_pop_feature_skips_repos_with_no_match(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    _make_dirty(workspace_with_feature / "repo-a", "x.txt")
    save_for_feature(ws, "auth-flow", "WIP", repos=["repo-a"])

    result = pop_feature(ws, "auth-flow")
    assert result["repos"]["repo-a"]["status"] == "popped"
    assert result["repos"]["repo-b"]["status"] == "no_match"


def test_pop_feature_no_match_anywhere_raises(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "auth-flow": {"repos": ["repo-a", "repo-b"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        pop_feature(ws, "auth-flow")
    assert exc_info.value.code == "no_tagged_stash"


def test_pop_feature_other_feature_stash_not_touched(workspace_with_feature):
    _features_file(workspace_with_feature, {
        "feat-a": {"repos": ["repo-a"], "status": "active"},
        "feat-b": {"repos": ["repo-a"], "status": "active"},
    })
    ws = _make_workspace(workspace_with_feature)

    _make_dirty(workspace_with_feature / "repo-a", "a.txt")
    save_for_feature(ws, "feat-a", "A work", repos=["repo-a"])
    _make_dirty(workspace_with_feature / "repo-a", "b.txt")
    save_for_feature(ws, "feat-b", "B work", repos=["repo-a"])

    pop_feature(ws, "feat-a", repos=["repo-a"])
    grouped = list_grouped(ws)
    # feat-b stash should still exist
    remaining = grouped["by_feature"].get("feat-b", [])
    assert len(remaining) == 1
    assert remaining[0]["user_message"] == "B work"
