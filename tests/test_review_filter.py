"""Tests for canopy.actions.review_filter — temporal classification.

Reproduces the four real-PR cases from the user's research doc to anchor
the validation:

| Feature   | Repo | Comments | Notes                                       |
|-----------|------|----------|---------------------------------------------|
| SIN-3029  | api  | 4        | All post-commit → all ACTIONABLE            |
| SIN-3010  | api  | 6        | 4 post-commit, 2 pre-commit on touched file |
| SIN-3008  | ui   | 11       | 1 post-commit, 10 likely_resolved           |
| SIN-2827  | mixed| many     | mix; bot threads kept                       |
"""
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from canopy.actions.review_filter import classify_threads


def _git(args, cwd):
    subprocess.run(
        ["git"] + args, cwd=cwd, check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )


def _git_at(args, cwd, when_iso):
    """Run a git command with a fixed committer/author date."""
    subprocess.run(
        ["git"] + args, cwd=cwd, check=True, capture_output=True, text=True,
        env={**os.environ,
             "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com",
             "GIT_AUTHOR_DATE": when_iso,
             "GIT_COMMITTER_DATE": when_iso},
    )


def _commit_at(repo: Path, files: dict[str, str], message: str, when_iso: str) -> str:
    """Stage some files and commit with a fixed timestamp. Returns sha."""
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _git(["add", "."], cwd=repo)
    _git_at(["commit", "-m", message], cwd=repo, when_iso=when_iso)
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
    ).strip()


@pytest.fixture
def repo(tmp_path):
    """A repo with three timestamped commits across two files.

    Timeline:
        T0  2026-04-15  initial: file_a, file_b
        T1  2026-04-20  edit file_a (api timeline 'last commit before fix')
        T2  2026-04-22  edit file_a (post-comment commit)
    """
    r = tmp_path / "repo"
    r.mkdir()
    _git(["init", "-b", "main"], cwd=r)
    _git(["config", "user.email", "t@t.com"], cwd=r)
    _git(["config", "user.name", "T"], cwd=r)
    _commit_at(r, {"file_a.py": "v1\n", "file_b.py": "v1\n"},
               "init", "2026-04-15T10:00:00Z")
    _commit_at(r, {"file_a.py": "v2\n"}, "edit a", "2026-04-20T10:00:00Z")
    _commit_at(r, {"file_a.py": "v3\n"}, "edit a again", "2026-04-22T10:00:00Z")
    return r


# ── Case 1: ACTIONABLE because comment posted AFTER latest commit ────────

def test_post_commit_comment_is_actionable(repo):
    """SIN-3029 case: comment timestamp is after branch HEAD timestamp."""
    comments = [{
        "path": "file_a.py", "line": 1, "body": "fix this",
        "author": "reviewer", "created_at": "2026-04-23T10:00:00Z",
    }]
    out = classify_threads(comments, repo, "main")
    assert len(out["actionable_threads"]) == 1
    assert len(out["likely_resolved_threads"]) == 0
    assert out["actionable_threads"][0]["classification_reason"] == "posted_after_latest_commit"


# ── Case 2: LIKELY_RESOLVED because a later commit touched the file ──────

def test_pre_commit_comment_on_touched_file_is_likely_resolved(repo):
    """Comment posted Apr 18 on file_a; commit on Apr 20 + Apr 22 touched
    file_a → likely resolved (the addressing commit is the most recent one)."""
    comments = [{
        "path": "file_a.py", "line": 1, "body": "use status from fastapi",
        "author": "alice", "created_at": "2026-04-18T10:00:00Z",
        "url": "https://github.com/x/y/pull/1#c1",
    }]
    out = classify_threads(comments, repo, "main")
    assert len(out["actionable_threads"]) == 0
    assert len(out["likely_resolved_threads"]) == 1
    lr = out["likely_resolved_threads"][0]
    assert lr["path"] == "file_a.py"
    assert lr["author"] == "alice"
    # Most recent post-comment commit wins
    assert lr["addressed_at"].startswith("2026-04-22")
    assert "after the comment" in lr["reason"]


# ── Case 3: ACTIONABLE because untouched file even though comment is old ──

def test_pre_commit_comment_on_untouched_file_is_actionable(repo):
    """SIN-3010 'validate the account' on repository.py: comment is old,
    file wasn't touched by interim commits → still ACTIONABLE."""
    comments = [{
        "path": "file_b.py", "line": 1, "body": "validate the account",
        "author": "alice", "created_at": "2026-04-18T10:00:00Z",
    }]
    out = classify_threads(comments, repo, "main")
    assert len(out["actionable_threads"]) == 1
    assert len(out["likely_resolved_threads"]) == 0
    reason = out["actionable_threads"][0]["classification_reason"]
    assert reason == "no_post_comment_commit_touched_file"


# ── Case 4: bot threads are kept and classified the same way ─────────────

def test_bot_thread_is_classified_not_filtered(repo):
    """claude[bot] thread on a touched file → likely_resolved (not skipped)."""
    comments = [{
        "path": "file_a.py", "line": 1, "body": "stale inline import",
        "author": "claude[bot]", "author_type": "Bot",
        "created_at": "2026-04-18T10:00:00Z",
    }]
    out = classify_threads(comments, repo, "main")
    assert len(out["likely_resolved_threads"]) == 1
    # Bot author preserved in summary
    assert out["likely_resolved_threads"][0]["author"] == "claude[bot]"


# ── Mixed batch: end-to-end sanity ───────────────────────────────────────

def test_mixed_batch_sorts_correctly(repo):
    """One actionable, one likely-resolved, one untouched-file → all correctly bucketed."""
    comments = [
        {"path": "file_a.py", "body": "post-commit", "author": "r",
         "created_at": "2026-04-23T10:00:00Z"},
        {"path": "file_a.py", "body": "addressed", "author": "r",
         "created_at": "2026-04-18T10:00:00Z"},
        {"path": "file_b.py", "body": "untouched", "author": "r",
         "created_at": "2026-04-18T10:00:00Z"},
    ]
    out = classify_threads(comments, repo, "main")
    assert len(out["actionable_threads"]) == 2
    assert len(out["likely_resolved_threads"]) == 1
    bodies_actionable = {t["body"] for t in out["actionable_threads"]}
    assert bodies_actionable == {"post-commit", "untouched"}


# ── Latest-commit timestamp surfaced in result ───────────────────────────

def test_latest_commit_at_is_returned(repo):
    out = classify_threads([], repo, "main")
    assert out["latest_commit_at"].startswith("2026-04-22")


# ── Edge: missing or malformed timestamps ────────────────────────────────

def test_comment_with_missing_timestamp_treated_as_actionable(repo):
    comments = [{"path": "file_a.py", "body": "no ts", "author": "r",
                 "created_at": ""}]
    out = classify_threads(comments, repo, "main")
    assert len(out["actionable_threads"]) == 1
    assert out["actionable_threads"][0]["classification_reason"] == "missing_timestamp"


def test_comment_with_no_path_treated_as_actionable(repo):
    """A general PR comment (no file path) can't be temporally checked."""
    comments = [{"path": "", "body": "general feedback", "author": "r",
                 "created_at": "2026-04-18T10:00:00Z"}]
    out = classify_threads(comments, repo, "main")
    assert len(out["actionable_threads"]) == 1
    assert out["actionable_threads"][0]["classification_reason"] == "no_path_to_check"


# ── Resolved count is preserved ──────────────────────────────────────────

def test_classification_includes_resolved_count_field(repo):
    out = classify_threads([], repo, "main")
    assert "resolved_thread_count" in out
    assert out["resolved_thread_count"] == 0  # set by caller, not classifier
