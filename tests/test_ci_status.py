"""Smoke tests for M10 — CI status integration.

The integration tests for ``feature_state`` (with PRs + reviews) live in
``test_feature_state.py``; here we cover the new pure helpers
(``_rollup_checks`` + ``_aggregate_ci``) and the matrix branch added to
``_decide_state``.
"""
from __future__ import annotations

import pytest

from canopy.management.feature_state import _aggregate_ci, _decide_state
from canopy.integrations.github import _rollup_checks


# ── _rollup_checks ─────────────────────────────────────────────────────

def test_rollup_passing_when_all_succeeded():
    raw = [
        {"name": "lint", "bucket": "pass"},
        {"name": "test", "bucket": "success"},
    ]
    out = _rollup_checks(raw, owner="o", repo="r", pr_number=1)
    assert out["status"] == "passing"
    assert out["passed"] == 2
    assert out["failing"] == 0
    assert out["pending"] == 0
    assert out["details_url"].endswith("/pull/1/checks")


def test_rollup_failing_overrides_pending():
    raw = [
        {"name": "lint", "bucket": "fail"},
        {"name": "build", "bucket": "pending"},
    ]
    out = _rollup_checks(raw, owner="o", repo="r", pr_number=1)
    assert out["status"] == "failing"
    assert out["required_failing"] == ["lint"]
    assert out["required_pending"] == ["build"]


def test_rollup_pending_when_only_running():
    raw = [
        {"name": "lint", "bucket": "running"},
        {"name": "test", "bucket": "queued"},
    ]
    out = _rollup_checks(raw, owner="o", repo="r", pr_number=1)
    assert out["status"] == "pending"
    assert sorted(out["required_pending"]) == ["lint", "test"]


def test_rollup_treats_cancelled_as_failing():
    raw = [{"name": "lint", "bucket": "cancelled"}]
    out = _rollup_checks(raw, owner="o", repo="r", pr_number=1)
    assert out["status"] == "failing"
    assert out["required_failing"] == ["lint"]


def test_rollup_unknown_bucket_falls_back_to_pending():
    raw = [{"name": "weird", "bucket": "something_new"}]
    out = _rollup_checks(raw, owner="o", repo="r", pr_number=1)
    assert out["status"] == "pending"
    assert out["required_pending"] == ["weird"]


# ── _aggregate_ci ─────────────────────────────────────────────────────

def test_aggregate_no_checks_when_empty():
    assert _aggregate_ci({}) == "no_checks"


def test_aggregate_failing_wins_over_pending():
    assert _aggregate_ci({
        "api": {"status": "failing"},
        "ui": {"status": "pending"},
    }) == "failing"


def test_aggregate_pending_wins_over_passing():
    assert _aggregate_ci({
        "api": {"status": "passing"},
        "ui": {"status": "pending"},
    }) == "pending"


def test_aggregate_passing_when_all_passing():
    assert _aggregate_ci({
        "api": {"status": "passing"},
        "ui": {"status": "passing"},
    }) == "passing"


# ── _decide_state CI matrix ────────────────────────────────────────────

def _make_summary(*, decisions, ci_aggregate, ci_per_repo=None,
                   actionable=0, actionable_human=0, actionable_bot=0):
    """Build the smallest summary that exercises _decide_state."""
    return {
        "dirty_repos": [],
        "ahead_repos": {},
        "actionable_count": actionable,
        "actionable_human_count": actionable_human,
        "actionable_bot_count": actionable_bot,
        "review_decisions": decisions,
        "pr_count": len(decisions),
        "ci_aggregate": ci_aggregate,
        "ci_per_repo": ci_per_repo or {},
    }


def test_decide_approved_with_passing_ci_returns_approved():
    summary = _make_summary(decisions={"api": "APPROVED"}, ci_aggregate="passing")
    state, _, _ = _decide_state("f", {"api": {"pr": True}}, summary, True, None)
    assert state == "approved"


def test_decide_approved_with_pending_ci_returns_awaiting_ci():
    ci_per_repo = {"api": {"status": "pending", "required_pending": ["e2e"]}}
    summary = _make_summary(
        decisions={"api": "APPROVED"}, ci_aggregate="pending",
        ci_per_repo=ci_per_repo,
    )
    state, next_actions, _ = _decide_state(
        "f", {"api": {"pr": True}}, summary, True, None,
    )
    assert state == "awaiting_ci"
    assert next_actions[0]["action"] == "wait_for_ci"
    assert "e2e" in next_actions[0]["preview"]


def test_decide_approved_with_failing_ci_returns_needs_work():
    ci_per_repo = {"api": {"status": "failing", "required_failing": ["lint"]}}
    summary = _make_summary(
        decisions={"api": "APPROVED"}, ci_aggregate="failing",
        ci_per_repo=ci_per_repo,
    )
    state, next_actions, _ = _decide_state(
        "f", {"api": {"pr": True}}, summary, True, None,
    )
    assert state == "needs_work"
    assert next_actions[0]["action"] == "investigate_ci"
    assert "lint" in next_actions[0]["preview"]


def test_decide_approved_with_no_checks_returns_approved():
    summary = _make_summary(decisions={"api": "APPROVED"}, ci_aggregate="no_checks")
    state, _, _ = _decide_state("f", {"api": {"pr": True}}, summary, True, None)
    assert state == "approved"
