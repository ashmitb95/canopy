"""Tests for canopy.actions.bot_resolutions — persistence layer for M3."""
from __future__ import annotations

import json
from pathlib import Path

from canopy.actions.bot_resolutions import (
    is_resolved,
    load_resolutions,
    record_resolution,
    resolutions_for_feature,
)


def _state_file(workspace_root: Path) -> Path:
    return workspace_root / ".canopy" / "state" / "bot_resolutions.json"


def test_load_returns_empty_when_no_file(tmp_path):
    assert load_resolutions(tmp_path) == {}


def test_record_then_load_round_trip(tmp_path):
    record_resolution(
        tmp_path,
        comment_id=123456,
        feature="sin-6",
        repo="api",
        commit_sha="abc123de",
        comment_title="rename foo to bar",
        comment_url="https://github.com/o/r/pull/1#discussion_r123456",
    )
    data = load_resolutions(tmp_path)
    assert "123456" in data
    entry = data["123456"]
    assert entry["feature"] == "sin-6"
    assert entry["repo"] == "api"
    assert entry["commit_sha"] == "abc123de"
    assert entry["comment_title"] == "rename foo to bar"
    assert entry["comment_url"].endswith("123456")
    assert entry["addressed_at"]   # ISO timestamp set


def test_record_creates_state_directory(tmp_path):
    assert not (tmp_path / ".canopy").exists()
    record_resolution(
        tmp_path,
        comment_id=1, feature="f", repo="r", commit_sha="sha",
        comment_title="t",
    )
    assert _state_file(tmp_path).exists()


def test_record_supports_int_or_str_comment_id(tmp_path):
    record_resolution(
        tmp_path, comment_id=999, feature="f", repo="r",
        commit_sha="x", comment_title="t",
    )
    record_resolution(
        tmp_path, comment_id="888", feature="f", repo="r",
        commit_sha="y", comment_title="t",
    )
    data = load_resolutions(tmp_path)
    assert "999" in data and "888" in data


def test_record_overwrites_on_duplicate_id(tmp_path):
    record_resolution(
        tmp_path, comment_id=1, feature="f", repo="r",
        commit_sha="first", comment_title="initial",
    )
    record_resolution(
        tmp_path, comment_id=1, feature="f", repo="r",
        commit_sha="second", comment_title="re-addressed",
    )
    data = load_resolutions(tmp_path)
    assert data["1"]["commit_sha"] == "second"
    assert data["1"]["comment_title"] == "re-addressed"


def test_is_resolved_true_after_record(tmp_path):
    assert is_resolved(tmp_path, 42) is False
    record_resolution(
        tmp_path, comment_id=42, feature="f", repo="r",
        commit_sha="x", comment_title="t",
    )
    assert is_resolved(tmp_path, 42) is True
    assert is_resolved(tmp_path, "42") is True   # str/int both work


def test_resolutions_for_feature_filters(tmp_path):
    record_resolution(
        tmp_path, comment_id=1, feature="alpha", repo="r",
        commit_sha="x", comment_title="t",
    )
    record_resolution(
        tmp_path, comment_id=2, feature="beta", repo="r",
        commit_sha="y", comment_title="t",
    )
    record_resolution(
        tmp_path, comment_id=3, feature="alpha", repo="r",
        commit_sha="z", comment_title="t",
    )
    alpha_only = resolutions_for_feature(tmp_path, "alpha")
    assert set(alpha_only.keys()) == {"1", "3"}


def test_load_returns_empty_on_corrupt_file(tmp_path):
    state = _state_file(tmp_path)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("{ this is not valid json")
    assert load_resolutions(tmp_path) == {}


def test_persisted_file_is_pretty_json(tmp_path):
    record_resolution(
        tmp_path, comment_id=1, feature="f", repo="r",
        commit_sha="x", comment_title="t",
    )
    raw = _state_file(tmp_path).read_text()
    # indent=2 + sort_keys → human-diffable
    assert "\n" in raw
    parsed = json.loads(raw)
    assert "1" in parsed


def test_addressed_at_can_be_overridden_for_deterministic_tests(tmp_path):
    record_resolution(
        tmp_path, comment_id=1, feature="f", repo="r",
        commit_sha="x", comment_title="t",
        addressed_at="2026-05-02T17:30:00Z",
    )
    assert load_resolutions(tmp_path)["1"]["addressed_at"] == "2026-05-02T17:30:00Z"
