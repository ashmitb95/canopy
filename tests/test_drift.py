"""Tests for canopy.actions.drift — detect_drift + assert_aligned."""
import json
from datetime import datetime, timezone

import pytest

from canopy.actions.drift import (
    DriftReport, FeatureDrift, RepoAlignment,
    assert_aligned, detect_drift,
)
from canopy.actions.errors import BlockerError
from canopy.features.coordinator import FeatureCoordinator
from canopy.workspace.config import RepoConfig, WorkspaceConfig
from canopy.workspace.workspace import Workspace


def _make_workspace(workspace_dir, repos=("api", "ui")) -> Workspace:
    config = WorkspaceConfig(
        name="test",
        repos=[
            RepoConfig(name=name, path=f"./{name}", role="x", lang="x")
            for name in repos
        ],
        root=workspace_dir,
    )
    return Workspace(config)


def _write_heads(workspace_dir, **per_repo):
    """Write .canopy/state/heads.json with given repo entries.

    Pass kwargs like api={"branch": "auth-flow", "sha": "deadbeef..."}.
    Defaults ts to now and prev_sha to sha.
    """
    state_dir = workspace_dir / ".canopy" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state = {}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for repo, entry in per_repo.items():
        state[repo] = {
            "branch": entry["branch"],
            "sha": entry.get("sha", "0" * 40),
            "prev_sha": entry.get("prev_sha", entry.get("sha", "0" * 40)),
            "ts": entry.get("ts", now),
        }
    (state_dir / "heads.json").write_text(json.dumps(state))


def _create_explicit_feature(workspace_dir, name, repos):
    """Write a features.json entry for an active feature lane."""
    canopy_dir = workspace_dir / ".canopy"
    canopy_dir.mkdir(exist_ok=True)
    features_file = canopy_dir / "features.json"
    existing = {}
    if features_file.exists():
        existing = json.loads(features_file.read_text())
    existing[name] = {"repos": list(repos), "status": "active",
                      "created_at": "2026-04-25T00:00:00Z"}
    features_file.write_text(json.dumps(existing))


# ── detect_drift ─────────────────────────────────────────────────────────

def test_no_active_features_returns_empty_aligned_report(workspace_dir):
    ws = _make_workspace(workspace_dir)
    report = detect_drift(ws)
    assert report.overall_aligned is True
    assert report.features == []
    assert report.note == "no active features"


def test_aligned_two_repo_feature(workspace_with_feature):
    """Both repos on auth-flow branch matches features.json."""
    _create_explicit_feature(workspace_with_feature, "auth-flow", ["api", "ui"])
    _write_heads(workspace_with_feature,
                 api={"branch": "auth-flow"},
                 ui={"branch": "auth-flow"})
    ws = _make_workspace(workspace_with_feature)

    report = detect_drift(ws)
    assert report.overall_aligned is True
    assert len(report.features) == 1
    fd = report.features[0]
    assert fd.feature == "auth-flow"
    assert fd.aligned is True
    assert fd.drifted_repos == []
    assert fd.untracked_repos == []
    assert all(r.aligned for r in fd.repos)


def test_drift_in_one_repo(workspace_with_feature):
    """api on auth-flow, ui on main → drift in ui."""
    _create_explicit_feature(workspace_with_feature, "auth-flow", ["api", "ui"])
    _write_heads(workspace_with_feature,
                 api={"branch": "auth-flow"},
                 ui={"branch": "main"})
    ws = _make_workspace(workspace_with_feature)

    report = detect_drift(ws)
    assert report.overall_aligned is False
    fd = report.features[0]
    assert fd.aligned is False
    assert fd.drifted_repos == ["ui"]
    assert fd.untracked_repos == []
    ui_alignment = next(r for r in fd.repos if r.repo == "ui")
    assert ui_alignment.expected == "auth-flow"
    assert ui_alignment.actual == "main"
    assert ui_alignment.aligned is False


def test_untracked_repo_counted_as_drift(workspace_with_feature):
    """Repo in feature.repos but missing from heads.json is untracked."""
    _create_explicit_feature(workspace_with_feature, "auth-flow", ["api", "ui"])
    _write_heads(workspace_with_feature, api={"branch": "auth-flow"})
    ws = _make_workspace(workspace_with_feature)

    report = detect_drift(ws)
    assert report.overall_aligned is False
    fd = report.features[0]
    assert fd.aligned is False
    assert fd.drifted_repos == []
    assert fd.untracked_repos == ["ui"]
    ui_alignment = next(r for r in fd.repos if r.repo == "ui")
    assert ui_alignment.actual is None
    assert ui_alignment.aligned is False


def test_filter_by_feature_name(workspace_with_feature):
    """When feature_name passed, only that feature is reported."""
    _create_explicit_feature(workspace_with_feature, "auth-flow", ["api", "ui"])
    _create_explicit_feature(workspace_with_feature, "other-feature", ["api"])
    _write_heads(workspace_with_feature,
                 api={"branch": "auth-flow"}, ui={"branch": "auth-flow"})
    ws = _make_workspace(workspace_with_feature)

    report = detect_drift(ws, feature_name="auth-flow")
    assert len(report.features) == 1
    assert report.features[0].feature == "auth-flow"


def test_filter_by_unknown_feature(workspace_with_feature):
    _create_explicit_feature(workspace_with_feature, "auth-flow", ["api", "ui"])
    ws = _make_workspace(workspace_with_feature)
    report = detect_drift(ws, feature_name="nonexistent")
    assert report.overall_aligned is False
    assert "not an active" in (report.note or "")
    assert report.features == []


def test_single_repo_feature_aligned(workspace_with_feature):
    """ui-only feature should align even when api is on a different branch."""
    _create_explicit_feature(workspace_with_feature, "ui-only-feat", ["ui"])
    # Create the branch in ui so the feature is real
    from canopy.git import repo as git
    git.create_branch(workspace_with_feature / "ui", "ui-only-feat")
    _write_heads(workspace_with_feature,
                 api={"branch": "main"},          # api on main; not in feature
                 ui={"branch": "ui-only-feat"})
    ws = _make_workspace(workspace_with_feature)

    report = detect_drift(ws, feature_name="ui-only-feat")
    fd = report.features[0]
    assert fd.aligned is True, (
        "ui-only feature must ignore api's branch — api is not in feature.repos"
    )


def test_single_repo_feature_drift(workspace_with_feature):
    """ui-only feature drifts when ui is on the wrong branch, regardless of api."""
    _create_explicit_feature(workspace_with_feature, "ui-only-feat", ["ui"])
    from canopy.git import repo as git
    git.create_branch(workspace_with_feature / "ui", "ui-only-feat")
    _write_heads(workspace_with_feature,
                 api={"branch": "feature-x"},     # irrelevant
                 ui={"branch": "main"})           # ui not on its expected branch
    ws = _make_workspace(workspace_with_feature)

    report = detect_drift(ws, feature_name="ui-only-feat")
    fd = report.features[0]
    assert fd.aligned is False
    assert fd.drifted_repos == ["ui"]


def test_state_age_is_populated(workspace_with_feature):
    _create_explicit_feature(workspace_with_feature, "auth-flow", ["api", "ui"])
    _write_heads(workspace_with_feature,
                 api={"branch": "auth-flow", "ts": "2026-01-01T00:00:00Z"},
                 ui={"branch": "auth-flow"})
    ws = _make_workspace(workspace_with_feature)

    report = detect_drift(ws)
    api_alignment = next(r for r in report.features[0].repos if r.repo == "api")
    assert api_alignment.state_age_seconds is not None
    assert api_alignment.state_age_seconds > 0  # in the past


def test_report_to_dict_serializable(workspace_with_feature):
    _create_explicit_feature(workspace_with_feature, "auth-flow", ["api", "ui"])
    _write_heads(workspace_with_feature,
                 api={"branch": "auth-flow"}, ui={"branch": "main"})
    ws = _make_workspace(workspace_with_feature)
    report = detect_drift(ws)
    s = json.dumps(report.to_dict())
    parsed = json.loads(s)
    assert parsed["overall_aligned"] is False
    assert parsed["features"][0]["drifted_repos"] == ["ui"]


# ── assert_aligned ───────────────────────────────────────────────────────

def test_assert_aligned_passes_when_aligned(workspace_with_feature):
    _create_explicit_feature(workspace_with_feature, "auth-flow", ["api", "ui"])
    _write_heads(workspace_with_feature,
                 api={"branch": "auth-flow"}, ui={"branch": "auth-flow"})
    ws = _make_workspace(workspace_with_feature)
    assert_aligned(ws, "auth-flow")  # no raise


def test_assert_aligned_raises_blocker_on_drift(workspace_with_feature):
    _create_explicit_feature(workspace_with_feature, "auth-flow", ["api", "ui"])
    _write_heads(workspace_with_feature,
                 api={"branch": "auth-flow"}, ui={"branch": "main"})
    ws = _make_workspace(workspace_with_feature)

    with pytest.raises(BlockerError) as exc_info:
        assert_aligned(ws, "auth-flow")

    err = exc_info.value
    assert err.code == "drift_detected"
    assert "auth-flow" in err.what
    assert err.expected["branches"] == {"api": "auth-flow", "ui": "auth-flow"}
    assert err.actual["branches"] == {"api": "auth-flow", "ui": "main"}
    assert err.details["drifted_repos"] == ["ui"]
    assert err.details["untracked_repos"] == []
    # Fix action: realign
    assert len(err.fix_actions) == 1
    fix = err.fix_actions[0]
    assert fix.action == "realign"
    assert fix.args == {"feature": "auth-flow"}
    assert fix.safe is True
    assert "ui" in (fix.preview or "")


def test_assert_aligned_raises_unknown_feature(workspace_with_feature):
    ws = _make_workspace(workspace_with_feature)
    with pytest.raises(BlockerError) as exc_info:
        assert_aligned(ws, "does-not-exist")
    assert exc_info.value.code == "unknown_feature"
    assert exc_info.value.details["feature"] == "does-not-exist"


def test_assert_aligned_raises_blocker_on_untracked(workspace_with_feature):
    """Repo missing from heads.json counts as drift for assertion purposes."""
    _create_explicit_feature(workspace_with_feature, "auth-flow", ["api", "ui"])
    _write_heads(workspace_with_feature, api={"branch": "auth-flow"})
    ws = _make_workspace(workspace_with_feature)

    with pytest.raises(BlockerError) as exc_info:
        assert_aligned(ws, "auth-flow")

    err = exc_info.value
    assert err.code == "drift_detected"
    assert err.details["untracked_repos"] == ["ui"]
