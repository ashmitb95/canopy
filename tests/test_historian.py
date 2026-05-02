"""Tests for canopy.actions.historian — cross-session feature memory (M4)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from canopy.actions import historian
from canopy.actions.historian import (
    compact, format_for_agent, read, record_classifier_resolved,
    record_comment_deferred, record_comment_read, record_comment_resolved,
    record_decision, record_event, record_pause, record_pr_context,
    record_pr_update, render_path, store_path,
)


@pytest.fixture(autouse=True)
def fixed_session(monkeypatch):
    """Pin CANOPY_SESSION_ID so dedup-per-session is predictable in tests."""
    monkeypatch.setenv("CANOPY_SESSION_ID", "session-A")


# ── Storage paths ────────────────────────────────────────────────────────


def test_paths_under_canopy_memory(tmp_path):
    assert store_path(tmp_path, "f").parent == tmp_path / ".canopy" / "memory"
    assert store_path(tmp_path, "f").name == "f.jsonl"
    assert render_path(tmp_path, "f").name == "f.md"


# ── Append + read round-trip ────────────────────────────────────────────


def test_record_decision_persists(tmp_path):
    record_decision(tmp_path, "feat-1", title="use jwt.decode", rationale="stdlib only")
    entries = read(tmp_path, "feat-1")
    assert len(entries) == 1
    assert entries[0]["kind"] == "decision"
    assert entries[0]["title"] == "use jwt.decode"
    assert entries[0]["rationale"] == "stdlib only"
    assert entries[0]["session"] == "session-A"
    assert entries[0]["at"]   # timestamp populated


def test_record_event_persists(tmp_path):
    record_event(tmp_path, "feat-1", summary="ran preflight (passed)")
    entries = read(tmp_path, "feat-1")
    assert entries[0]["kind"] == "event"
    assert entries[0]["summary"] == "ran preflight (passed)"


def test_record_pause_persists(tmp_path):
    record_pause(tmp_path, "feat-1", reason="blocked on design copy")
    entries = read(tmp_path, "feat-1")
    assert entries[0]["kind"] == "pause"
    assert entries[0]["reason"] == "blocked on design copy"


def test_read_returns_empty_when_no_memory(tmp_path):
    assert read(tmp_path, "ghost") == []


# ── Decision dedup ───────────────────────────────────────────────────────


def test_decision_deduped_within_session(tmp_path):
    out1 = record_decision(tmp_path, "feat-1", title="same title")
    out2 = record_decision(tmp_path, "feat-1", title="same title")
    assert out1["action"] == "recorded"
    assert out2["action"] == "deduped"
    assert len(read(tmp_path, "feat-1")) == 1


def test_decision_not_deduped_across_sessions(tmp_path, monkeypatch):
    record_decision(tmp_path, "feat-1", title="cross-session")
    monkeypatch.setenv("CANOPY_SESSION_ID", "session-B")
    record_decision(tmp_path, "feat-1", title="cross-session")
    assert len(read(tmp_path, "feat-1")) == 2


# ── Comment read dedup ──────────────────────────────────────────────────


def test_comment_read_deduped_per_session(tmp_path):
    record_comment_read(tmp_path, "feat-1", comment_id=42, author="bot",
                          path="x.py", line=1)
    record_comment_read(tmp_path, "feat-1", comment_id=42, author="bot",
                          path="x.py", line=1)
    assert len(read(tmp_path, "feat-1")) == 1


def test_comment_read_int_or_str_id(tmp_path):
    record_comment_read(tmp_path, "feat-1", comment_id=42, author="bot",
                          path="", line=0)
    record_comment_read(tmp_path, "feat-1", comment_id="42", author="bot",
                          path="", line=0)
    assert len(read(tmp_path, "feat-1")) == 1


# ── Classifier dedup ────────────────────────────────────────────────────


def test_classifier_resolved_logs_once_per_session(tmp_path):
    threads = [{"id": 1, "author": "bot", "path": "a.py"}]
    record_classifier_resolved(tmp_path, "feat-1", threads=threads)
    record_classifier_resolved(tmp_path, "feat-1", threads=threads)
    assert len(read(tmp_path, "feat-1")) == 1


def test_classifier_resolved_noop_when_empty(tmp_path):
    record_classifier_resolved(tmp_path, "feat-1", threads=[])
    assert read(tmp_path, "feat-1") == []


# ── Comment resolved + deferred ─────────────────────────────────────────


def test_record_comment_resolved(tmp_path):
    record_comment_resolved(tmp_path, "feat-1", comment_id=99, commit_sha="abc12345",
                              gist="renamed foo to bar", author="bot",
                              path="src/x.py", line=42)
    e = read(tmp_path, "feat-1")[0]
    assert e["kind"] == "comment_resolved"
    assert e["comment_id"] == "99"
    assert e["commit_sha"] == "abc12345"
    assert e["gist"] == "renamed foo to bar"


def test_record_comment_deferred(tmp_path):
    record_comment_deferred(tmp_path, "feat-1", comment_id=50,
                              reason="design discussion needed")
    e = read(tmp_path, "feat-1")[0]
    assert e["kind"] == "comment_deferred"
    assert e["reason"] == "design discussion needed"


# ── PR context + updates ────────────────────────────────────────────────


def test_record_pr_context(tmp_path):
    record_pr_context(tmp_path, "feat-1", pr_number=142, repo="api",
                        title="cache stats", base="main",
                        rationale="closes 3 actionable threads", url="https://gh/p/142")
    e = read(tmp_path, "feat-1")[0]
    assert e["kind"] == "pr_context"
    assert e["pr_number"] == 142
    assert e["title"] == "cache stats"
    assert e["url"] == "https://gh/p/142"


def test_record_pr_update(tmp_path):
    record_pr_update(tmp_path, "feat-1", pr_number=142, repo="api",
                       summary="addressed bot 789")
    e = read(tmp_path, "feat-1")[0]
    assert e["kind"] == "pr_update"
    assert e["summary"] == "addressed bot 789"


# ── format_for_agent ─────────────────────────────────────────────────────


def test_format_for_agent_empty(tmp_path):
    assert format_for_agent(tmp_path, "ghost") == ""


def test_format_for_agent_renders_three_sections(tmp_path):
    record_decision(tmp_path, "feat-1", title="picked stdlib jwt")
    record_comment_resolved(tmp_path, "feat-1", comment_id=1, commit_sha="abc12345",
                              gist="renamed", author="bot", path="x.py", line=1)
    record_pr_context(tmp_path, "feat-1", pr_number=10, repo="api", title="t")

    md = format_for_agent(tmp_path, "feat-1")
    assert "# Feature: feat-1" in md
    assert "## Resolutions log" in md
    assert "## PR context" in md
    assert "## Sessions (newest first)" in md
    # Resolution rendered with check glyph + sha shorthand
    assert "✓ comment 1" in md
    assert "abc12345" in md
    # PR block rendered
    assert "PR #10 — api" in md
    # Decision rendered in Sessions
    assert "decision:" in md
    assert "picked stdlib jwt" in md


def test_format_for_agent_handles_missing_sections(tmp_path):
    """Sections with no content show a placeholder rather than disappear."""
    record_decision(tmp_path, "feat-1", title="solo decision")
    md = format_for_agent(tmp_path, "feat-1")
    assert "_(no comment activity yet)_" in md
    assert "_(no PRs opened yet)_" in md


def test_render_file_written_alongside_store(tmp_path):
    record_decision(tmp_path, "feat-1", title="t")
    assert store_path(tmp_path, "feat-1").exists()
    assert render_path(tmp_path, "feat-1").exists()
    md = render_path(tmp_path, "feat-1").read_text()
    assert "# Feature: feat-1" in md


# ── Compaction ──────────────────────────────────────────────────────────


def test_compact_noop_when_within_limit(tmp_path, monkeypatch):
    for i in range(3):
        monkeypatch.setenv("CANOPY_SESSION_ID", f"s-{i}")
        record_event(tmp_path, "feat-1", summary=f"event {i}")
    out = compact(tmp_path, "feat-1", keep_sessions=5)
    assert out["action"] == "noop"


def test_compact_drops_old_sessions_keeps_structural(tmp_path, monkeypatch):
    # 7 sessions, each with one decision + one comment_resolved (structural).
    for i in range(7):
        monkeypatch.setenv("CANOPY_SESSION_ID", f"s-{i}")
        record_decision(tmp_path, "feat-1", title=f"decision-{i}")
        record_comment_resolved(tmp_path, "feat-1", comment_id=i,
                                  commit_sha=f"sha{i}", gist=f"g-{i}")
    pre_total = len(read(tmp_path, "feat-1"))
    assert pre_total == 14

    out = compact(tmp_path, "feat-1", keep_sessions=3)
    assert out["action"] == "compacted"
    assert out["kept"] < pre_total
    entries = read(tmp_path, "feat-1")
    # All 7 comment_resolved entries preserved (structural).
    assert sum(1 for e in entries if e["kind"] == "comment_resolved") == 7
    # Only the last 3 sessions' decisions remain.
    decisions = [e for e in entries if e["kind"] == "decision"]
    assert len(decisions) == 3
    titles = {d["title"] for d in decisions}
    assert titles == {"decision-4", "decision-5", "decision-6"}


def test_compact_noop_when_no_memory(tmp_path):
    assert compact(tmp_path, "ghost")["action"] == "noop"
