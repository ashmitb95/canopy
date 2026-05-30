"""Tests for actions/thread_actions.py and actions/thread_resolutions.py."""
import json
from pathlib import Path

import pytest

from canopy.actions import thread_resolutions as tr
from canopy.actions.errors import BlockerError
from canopy.workspace.config import load_config
from canopy.workspace.workspace import Workspace


# ── thread_resolutions helpers ───────────────────────────────────────────


def test_load_returns_empty_when_missing(canopy_toml):
    result = tr.load(canopy_toml)
    assert result == {}


def test_record_and_load_roundtrip(canopy_toml):
    entry = tr.record(
        canopy_toml,
        thread_id="PRRT_abc123",
        feature="auth-flow",
        via_command="resolve",
    )
    assert entry["feature"] == "auth-flow"
    assert entry["via_command"] == "resolve"
    assert entry["via_commit_sha"] is None
    assert "resolved_by_canopy_at" in entry

    log = tr.load(canopy_toml)
    assert "PRRT_abc123" in log
    assert log["PRRT_abc123"]["feature"] == "auth-flow"


def test_record_with_commit_sha(canopy_toml):
    entry = tr.record(
        canopy_toml,
        thread_id="PRRT_xyz",
        feature="my-feat",
        via_command="commit_address",
        via_commit_sha="deadbeef",
    )
    assert entry["via_commit_sha"] == "deadbeef"
    log = tr.load(canopy_toml)
    assert log["PRRT_xyz"]["via_commit_sha"] == "deadbeef"


def test_record_is_last_write_wins(canopy_toml):
    tr.record(canopy_toml, thread_id="PRRT_abc", feature="feat-a", via_command="resolve")
    tr.record(canopy_toml, thread_id="PRRT_abc", feature="feat-b", via_command="reply_resolve")
    log = tr.load(canopy_toml)
    assert log["PRRT_abc"]["feature"] == "feat-b"
    assert log["PRRT_abc"]["via_command"] == "reply_resolve"


def test_thread_resolutions_filter_since(canopy_toml):
    tr.record(canopy_toml, thread_id="PRRT_old", feature="f", via_command="resolve")
    tr.record(canopy_toml, thread_id="PRRT_new", feature="f", via_command="resolve")

    log = tr.load(canopy_toml)
    # Both entries have timestamps >= epoch
    filtered = tr.filter_since(canopy_toml, "2000-01-01T00:00:00Z")
    assert "PRRT_old" in filtered
    assert "PRRT_new" in filtered

    # Filtering with a far-future cutoff should return nothing
    empty = tr.filter_since(canopy_toml, "2099-01-01T00:00:00Z")
    assert empty == {}


def test_filter_since_partial(canopy_toml):
    tr.record(canopy_toml, thread_id="PRRT_early", feature="f", via_command="resolve")
    # Manually write a past timestamp for one entry
    path = canopy_toml / ".canopy" / "state" / "thread_resolutions.json"
    data = json.loads(path.read_text())
    data["PRRT_early"]["resolved_by_canopy_at"] = "2020-01-01T00:00:00Z"
    path.write_text(json.dumps(data))

    tr.record(canopy_toml, thread_id="PRRT_recent", feature="f", via_command="resolve")

    filtered = tr.filter_since(canopy_toml, "2025-01-01T00:00:00Z")
    assert "PRRT_early" not in filtered
    assert "PRRT_recent" in filtered


# ── thread_actions wrappers ──────────────────────────────────────────────


def _make_workspace(canopy_toml):
    return Workspace(load_config(canopy_toml))


def test_resolve_thread_writes_log(canopy_toml, monkeypatch):
    """resolve_thread calls gh integration and writes thread_resolutions.json."""
    from canopy.actions import thread_actions

    gh_result = {"thread_id": "PRRT_abc", "is_resolved": True}
    monkeypatch.setattr(
        "canopy.integrations.github.resolve_thread",
        lambda root, tid: gh_result,
    )

    ws = _make_workspace(canopy_toml)
    result = thread_actions.resolve_thread(ws, "PRRT_abc", feature="auth-flow")

    # Return value carries both gh result and log
    assert result["is_resolved"] is True
    assert "logged" in result
    assert result["logged"]["feature"] == "auth-flow"
    assert result["logged"]["via_command"] == "resolve"

    # State file written
    log = tr.load(canopy_toml)
    assert "PRRT_abc" in log
    assert log["PRRT_abc"]["feature"] == "auth-flow"
    assert log["PRRT_abc"]["via_command"] == "resolve"


def test_resolve_thread_idempotent(canopy_toml, monkeypatch):
    """Calling resolve_thread twice is safe (last-write-wins, no crash)."""
    from canopy.actions import thread_actions

    monkeypatch.setattr(
        "canopy.integrations.github.resolve_thread",
        lambda root, tid: {"thread_id": tid, "is_resolved": True},
    )

    ws = _make_workspace(canopy_toml)
    thread_actions.resolve_thread(ws, "PRRT_dup", feature="feat-a")
    thread_actions.resolve_thread(ws, "PRRT_dup", feature="feat-a")

    log = tr.load(canopy_toml)
    assert "PRRT_dup" in log
    assert log["PRRT_dup"]["feature"] == "feat-a"


def test_resolve_thread_invalid_id(canopy_toml):
    """thread_id that doesn't start with PRRT_ raises BlockerError."""
    from canopy.actions import thread_actions

    ws = _make_workspace(canopy_toml)
    with pytest.raises(BlockerError) as exc_info:
        thread_actions.resolve_thread(ws, "IC_badinput", feature="feat")

    err = exc_info.value
    assert err.code == "invalid_thread_id"
    assert err.STATUS == "blocked"


def test_reply_to_thread_invalid_id(canopy_toml):
    """reply_to_thread also validates the thread_id."""
    from canopy.actions import thread_actions

    ws = _make_workspace(canopy_toml)
    with pytest.raises(BlockerError) as exc_info:
        thread_actions.reply_to_thread(ws, "BAD_ID", "hello", feature="feat")

    assert exc_info.value.code == "invalid_thread_id"


def test_reply_to_thread_posts_without_resolve(canopy_toml, monkeypatch):
    """reply_to_thread posts a comment but does not resolve by default."""
    from canopy.actions import thread_actions

    posted_result = {"comment_id": "IC_xyz", "url": "https://github.com/..."}
    monkeypatch.setattr(
        "canopy.integrations.github.reply_to_thread",
        lambda root, tid, body: posted_result,
    )

    ws = _make_workspace(canopy_toml)
    result = thread_actions.reply_to_thread(ws, "PRRT_abc", "LGTM", feature="feat")

    assert result["posted"] == posted_result
    assert "resolved" not in result
    # Should NOT have written a resolution log
    log = tr.load(canopy_toml)
    assert "PRRT_abc" not in log


def test_reply_to_thread_resolve_after(canopy_toml, monkeypatch):
    """reply_to_thread with resolve_after=True also resolves and logs."""
    from canopy.actions import thread_actions

    monkeypatch.setattr(
        "canopy.integrations.github.reply_to_thread",
        lambda root, tid, body: {"comment_id": "IC_1", "url": ""},
    )
    monkeypatch.setattr(
        "canopy.integrations.github.resolve_thread",
        lambda root, tid: {"thread_id": tid, "is_resolved": True},
    )

    ws = _make_workspace(canopy_toml)
    result = thread_actions.reply_to_thread(
        ws, "PRRT_abc", "Done!", feature="my-feat", resolve_after=True,
    )

    assert "posted" in result
    assert "resolved" in result
    assert result["resolved"]["is_resolved"] is True

    log = tr.load(canopy_toml)
    assert "PRRT_abc" in log
    assert log["PRRT_abc"]["via_command"] == "reply_resolve"
