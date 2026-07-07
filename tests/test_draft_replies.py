"""Smoke tests for ``canopy draft-replies`` (M9).

Focuses on the pure helpers (``classify_comment`` / ``render_reply``) and
the ``log_for_path`` git primitive. The end-to-end ``draft_replies``
orchestrator hits GitHub and is exercised by the existing review-flow
integration tests; here we test it through the seams.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from canopy.management.draft_replies import (
    classify_comment, render_reply, _has_keyword_overlap,
)
from canopy.git import repo as git


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


# ── classify_comment ────────────────────────────────────────────────────

def test_classify_unaddressed_when_no_history():
    result = classify_comment({"body": "rename foo to bar"}, [])
    assert result["status"] == "unaddressed"
    assert result["confidence"] == "low"
    assert result["reason"] == "no_commits"


def test_classify_high_confidence_with_keyword_match():
    history = [{"sha": "abc123", "subject": "rename foo to bar in search"}]
    result = classify_comment({"body": "please rename foo to bar"}, history)
    assert result["status"] == "addressed"
    assert result["confidence"] == "high"


def test_classify_medium_confidence_without_keyword_match():
    history = [{"sha": "abc123", "subject": "tweak whitespace"}]
    result = classify_comment({"body": "please rename foo to bar"}, history)
    assert result["status"] == "addressed"
    assert result["confidence"] == "medium"


def test_classify_low_confidence_with_multiple_commits():
    history = [
        {"sha": "abc", "subject": "first"},
        {"sha": "def", "subject": "second"},
    ]
    result = classify_comment({"body": "rename foo to bar"}, history)
    assert result["status"] == "addressed"
    assert result["confidence"] == "low"


# ── render_reply ────────────────────────────────────────────────────────

def test_render_reply_high_confidence_drops_lead_in():
    text = render_reply(
        {"body": "rename foo"},
        [{"sha": "abc12345dead", "subject": "rename foo to bar"}],
        confidence="high",
    )
    assert text == "Done — rename foo to bar. (abc12345)"


def test_render_reply_medium_uses_addressed_in():
    text = render_reply(
        {"body": "tweak"},
        [{"sha": "abc12345dead", "subject": "tweak whitespace"}],
        confidence="medium",
    )
    assert text == "Addressed in abc12345: tweak whitespace."


def test_render_reply_multiple_commits():
    text = render_reply(
        {"body": "x"},
        [
            {"sha": "abc12345aaaa", "subject": "first"},
            {"sha": "def67890bbbb", "subject": "second"},
        ],
        confidence="low",
    )
    assert text == "Addressed across 2 commits — abc12345, def67890."


def test_render_reply_empty_when_no_commits():
    assert render_reply({}, [], "low") == ""


# ── keyword overlap ────────────────────────────────────────────────────

def test_keyword_overlap_matches_identifier_tokens():
    assert _has_keyword_overlap("please rename foo_bar", "rename foo_bar in search")
    assert not _has_keyword_overlap("a tiny tweak", "completely unrelated subject")


def test_keyword_overlap_ignores_short_tokens():
    # "the" / "and" wouldn't be matched even if they appeared in both.
    assert not _has_keyword_overlap("the and to of", "the and to of")


# ── log_for_path integration with a real tmp git repo ─────────────────

def test_log_for_path_reports_commits_after_anchor(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)

    (repo / "f.py").write_text("a\n")
    _git(["add", "."], repo)
    _git(["commit", "-m", "initial"], repo)
    anchor = _git(["rev-parse", "HEAD"], repo)

    # Touch a different file — should NOT count.
    (repo / "g.py").write_text("g\n")
    _git(["add", "."], repo)
    _git(["commit", "-m", "untouched-by-comment"], repo)

    # Touch the commented file — SHOULD count.
    (repo / "f.py").write_text("a\nb\n")
    _git(["add", "."], repo)
    _git(["commit", "-m", "rename foo to bar"], repo)

    history = git.log_for_path(repo, anchor, "f.py")
    assert len(history) == 1
    assert history[0]["subject"] == "rename foo to bar"
    assert "sha" in history[0] and "date" in history[0]


def test_log_for_path_returns_empty_when_file_untouched(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)

    (repo / "f.py").write_text("a\n")
    _git(["add", "."], repo)
    _git(["commit", "-m", "initial"], repo)
    anchor = _git(["rev-parse", "HEAD"], repo)

    (repo / "g.py").write_text("g\n")
    _git(["add", "."], repo)
    _git(["commit", "-m", "other file only"], repo)

    assert git.log_for_path(repo, anchor, "f.py") == []
