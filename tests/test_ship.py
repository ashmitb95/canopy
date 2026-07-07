"""Smoke tests for ``canopy ship`` (M8 / Wave 2.4).

The orchestrator hits gh + git remotes and is exercised by the
existing integration tests in ``tests/test_commit_push_integration.py``;
here we cover the pure formatters and the per-repo classifier so the
wiring is provably right.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from canopy.management.ship import (
    _ahead_count, _classify_existing_pr, _format_body_initial,
    _format_body_with_siblings, _format_title, _position,
)
from canopy.workspace.config import load_config
from canopy.workspace.workspace import Workspace


@pytest.fixture
def workspace_with_features_json(workspace_dir, canopy_toml) -> Workspace:
    """Workspace with a multi-repo feature recorded in features.json."""
    state_dir = workspace_dir / ".canopy"
    state_dir.mkdir(exist_ok=True)
    (state_dir / "features.json").write_text(json.dumps({
        "auth-flow": {
            "repos": ["repo-a", "repo-b"],
            "status": "active",
            "linear_issue": "SIN-12",
            "linear_title": "Add auth refresh",
            "linear_url": "https://linear.app/x/issue/SIN-12",
        }
    }))
    return Workspace(load_config(workspace_dir))


def test_format_title_uses_linear_id_and_title(workspace_with_features_json):
    title = _format_title(workspace_with_features_json, "auth-flow")
    assert title == "SIN-12 Add auth refresh"


def test_format_title_falls_back_to_feature_name(workspace_with_features_json):
    title = _format_title(workspace_with_features_json, "no-such-feature")
    assert title == "no-such-feature"


def test_format_body_initial_includes_sibling_placeholders(workspace_with_features_json):
    body = _format_body_initial(workspace_with_features_json, "auth-flow", "repo-a")
    assert "Linear: SIN-12" in body
    assert "[Linear: SIN-12]" in body
    assert "1 of 2 repos" in body
    assert "repo-a: this PR" in body
    assert "sibling PR pending" in body
    assert "Opened by [canopy]" in body


def test_format_body_with_siblings_links_each_repo(workspace_with_features_json):
    pr_pairs = [
        ("repo-a", 142, "https://github.com/x/repo-a/pull/142"),
        ("repo-b", 58, "https://github.com/x/repo-b/pull/58"),
    ]
    body = _format_body_with_siblings(
        workspace_with_features_json, "auth-flow", "repo-a", pr_pairs,
    )
    assert "this PR (#142)" in body
    assert "[#58](https://github.com/x/repo-b/pull/58)" in body
    assert "1 of 2 repos" in body


def test_format_body_with_siblings_marks_my_repo(workspace_with_features_json):
    pr_pairs = [
        ("repo-a", 142, "url-a"),
        ("repo-b", 58, "url-b"),
    ]
    body = _format_body_with_siblings(
        workspace_with_features_json, "auth-flow", "repo-b", pr_pairs,
    )
    assert "repo-b: this PR (#58)" in body
    assert "repo-a: [#142](url-a)" in body


def test_position_returns_one_based_index():
    assert _position("a", ["a", "b", "c"]) == 1
    assert _position("b", ["a", "b", "c"]) == 2
    assert _position("missing", ["a", "b"]) == 3


# ── per-repo classifier ────────────────────────────────────────────────

def test_classify_existing_pr_up_to_date_when_shas_match(tmp_path, monkeypatch):
    fake_path = tmp_path
    monkeypatch.setattr(
        "canopy.management.ship.git.head_sha",
        lambda _: "abc123",
    )
    pr = {"number": 5, "url": "u", "state": "open", "head_sha": "abc123"}
    result = _classify_existing_pr(fake_path, "branch", pr)
    assert result == {"status": "up_to_date", "pr_number": 5, "url": "u"}


def test_classify_existing_pr_diverged_when_shas_differ(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "canopy.management.ship.git.head_sha",
        lambda _: "deadbeef",
    )
    pr = {"number": 5, "url": "u", "state": "open", "head_sha": "abc123"}
    result = _classify_existing_pr(tmp_path, "branch", pr)
    assert result["status"] == "diverged"
    assert "force-push" in result["warning"]


def test_classify_existing_pr_closed():
    pr = {"number": 5, "url": "u", "state": "closed"}
    result = _classify_existing_pr(Path("."), "branch", pr)
    assert result["status"] == "closed"
    assert "manual reopen" in result["reason"]


def test_classify_existing_pr_merged():
    pr = {"number": 5, "url": "u", "state": "merged"}
    result = _classify_existing_pr(Path("."), "branch", pr)
    assert result["status"] == "closed"


def test_ahead_count_handles_missing_branch(tmp_path):
    # Empty dir → git command fails → 0 ahead.
    assert _ahead_count(tmp_path, "no-such", "main") == 0
