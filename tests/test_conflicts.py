"""Smoke tests for ``canopy conflicts`` (M12)."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from canopy.management.conflicts import (
    classify, compute_overlap, find_conflicts,
)
from canopy.workspace.config import load_config
from canopy.workspace.workspace import Workspace


def _git(args: list[str], cwd: Path) -> str:
    res = subprocess.run(
        ["git"] + args,
        capture_output=True, text=True, cwd=cwd,
        env={**os.environ,
             "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com",
             "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"},
    )
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr}")
    return res.stdout.strip()


@pytest.fixture
def two_features(workspace_dir, canopy_toml) -> Workspace:
    """Two features touching the same file in repo-a."""
    api = workspace_dir / "repo-a"

    # feature_a: edit models.py + auth.py
    _git(["checkout", "-b", "feature-a"], cwd=api)
    (api / "src" / "models.py").write_text(
        "class User:\n    name: str\n    email: str\n    token: str\n"
    )
    (api / "src" / "auth.py").write_text("def login(): pass\n")
    _git(["add", "."], cwd=api)
    _git(["commit", "-m", "feature-a"], cwd=api)

    # feature_b: edit models.py with different lines + a unique file
    _git(["checkout", "main"], cwd=api)
    _git(["checkout", "-b", "feature-b"], cwd=api)
    (api / "src" / "models.py").write_text(
        "class User:\n    name: str\n    email: str\n    role: str\n"
    )
    (api / "src" / "rbac.py").write_text("def can(): return True\n")
    _git(["add", "."], cwd=api)
    _git(["commit", "-m", "feature-b"], cwd=api)
    _git(["checkout", "main"], cwd=api)

    # Register both features in features.json so the enumerator finds them.
    features = {
        "feature-a": {"repos": ["repo-a"], "status": "active",
                       "worktree_paths": {"repo-a": str(api)}},
        "feature-b": {"repos": ["repo-a"], "status": "active",
                       "worktree_paths": {"repo-a": str(api)}},
    }
    state_dir = workspace_dir / ".canopy"
    state_dir.mkdir(exist_ok=True)
    (state_dir / "features.json").write_text(json.dumps(features))

    return Workspace(load_config(workspace_dir))


def test_compute_overlap_returns_shared_files(two_features):
    diff_a = {"repo-a": {"changed_files": ["src/models.py", "src/auth.py"]}}
    diff_b = {"repo-a": {"changed_files": ["src/models.py", "src/rbac.py"]}}
    result = compute_overlap(diff_a, diff_b)
    assert result == {
        "repo-a": {"files": ["src/models.py"], "generated_files": []},
    }


def test_compute_overlap_skips_repos_without_overlap(two_features):
    diff_a = {"repo-a": {"changed_files": ["a.py"]}}
    diff_b = {"repo-a": {"changed_files": ["b.py"]}}
    assert compute_overlap(diff_a, diff_b) == {}


def test_compute_overlap_flags_generated_files():
    diff_a = {"repo-a": {"changed_files": ["package-lock.json", "src/models.py"]}}
    diff_b = {"repo-a": {"changed_files": ["package-lock.json", "src/x.py"]}}
    result = compute_overlap(diff_a, diff_b)
    assert result["repo-a"]["files"] == ["package-lock.json"]
    assert result["repo-a"]["generated_files"] == ["package-lock.json"]


def test_classify_high_when_real_files_overlap_without_line_data():
    overlap = {"repo-a": {"files": ["src/models.py"], "generated_files": []}}
    sev, _ = classify(overlap, "feature-a", "feature-b")
    assert sev == "high"


def test_classify_medium_when_only_generated_overlap():
    overlap = {"repo-a": {"files": ["package-lock.json"],
                            "generated_files": ["package-lock.json"]}}
    sev, suggestion = classify(overlap, "a", "b")
    assert sev == "medium"
    assert "auto-merge" in suggestion or "auto-mergeable" in suggestion


def test_classify_high_when_lines_intersect():
    overlap = {"repo-a": {"files": ["x"], "generated_files": [],
                            "lines_a_only": 2, "lines_b_only": 3, "lines_both": 4}}
    sev, _ = classify(overlap, "a", "b")
    assert sev == "high"


def test_classify_medium_when_lines_disjoint():
    overlap = {"repo-a": {"files": ["x"], "generated_files": [],
                            "lines_a_only": 2, "lines_b_only": 3, "lines_both": 0}}
    sev, _ = classify(overlap, "a", "b")
    assert sev == "medium"


def test_find_conflicts_end_to_end_file_level(two_features):
    result = find_conflicts(two_features)
    assert "feature-a" in result["features"]
    assert "feature-b" in result["features"]
    assert len(result["pairs"]) == 1
    pair = result["pairs"][0]
    names = {pair["feature_a"], pair["feature_b"]}
    assert names == {"feature-a", "feature-b"}
    assert pair["severity"] == "high"
    assert "src/models.py" in pair["overlap"]["repo-a"]["files"]


def test_find_conflicts_with_line_level(two_features):
    result = find_conflicts(two_features, line_level=True)
    pair = result["pairs"][0]
    entry = pair["overlap"]["repo-a"]
    assert "lines_both" in entry
    # Both features modified the same line of models.py (different content
    # for `token` vs `role`) so the line-level overlap is real.
    assert entry["lines_both"] >= 1
    assert pair["severity"] == "high"


def test_find_conflicts_scoped_to_one_feature(two_features):
    result = find_conflicts(two_features, feature="feature-a")
    # Only pairs involving feature-a should appear.
    for pair in result["pairs"]:
        assert "feature-a" in (pair["feature_a"], pair["feature_b"])


def test_find_conflicts_with_other_filter(two_features):
    result = find_conflicts(two_features, feature="feature-a", other="feature-b")
    assert len(result["pairs"]) == 1
    pair = result["pairs"][0]
    assert {pair["feature_a"], pair["feature_b"]} == {"feature-a", "feature-b"}
