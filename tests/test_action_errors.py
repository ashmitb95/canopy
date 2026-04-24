"""Tests for canopy.actions.errors and canopy.cli.render."""
import json

import pytest
from rich.console import Console

from canopy.actions.errors import (
    ActionError, BlockerError, FailedError, FixAction,
)
from canopy.cli.render import render_blocker


# ── FixAction ──────────────────────────────────────────────────────────

def test_fix_action_default_safe():
    fa = FixAction(action="realign")
    assert fa.safe is True
    assert fa.args == {}
    assert fa.preview is None


def test_fix_action_to_dict():
    fa = FixAction(
        action="realign", args={"feature": "doc-3029"},
        safe=False, preview="will discard ui's dirty changes",
    )
    d = fa.to_dict()
    assert d == {
        "action": "realign",
        "args": {"feature": "doc-3029"},
        "safe": False,
        "preview": "will discard ui's dirty changes",
    }


# ── BlockerError shape ──────────────────────────────────────────────────

def test_blocker_minimal():
    err = BlockerError(code="missing_config", what="canopy.toml not found")
    d = err.to_dict()
    assert d == {
        "status": "blocked",
        "code": "missing_config",
        "what": "canopy.toml not found",
        "fix_actions": [],
    }


def test_blocker_full_payload():
    err = BlockerError(
        code="drift_detected",
        what="branches don't match feature lane",
        expected={"branches": {"api": "doc-3029", "ui": "doc-3029"}},
        actual={"branches": {"api": "doc-3029", "ui": "main"}},
        fix_actions=[
            FixAction(action="realign", args={"feature": "doc-3029"},
                       safe=True, preview="checkout doc-3029 in ui (clean)"),
            FixAction(action="ship", args={"feature": "doc-3029", "auto_realign": True},
                       safe=True),
        ],
        details={"workspace_root": "/x/y/z"},
    )
    d = err.to_dict()
    assert d["status"] == "blocked"
    assert d["code"] == "drift_detected"
    assert d["expected"] == {"branches": {"api": "doc-3029", "ui": "doc-3029"}}
    assert d["actual"] == {"branches": {"api": "doc-3029", "ui": "main"}}
    assert len(d["fix_actions"]) == 2
    assert d["fix_actions"][0]["action"] == "realign"
    assert d["details"] == {"workspace_root": "/x/y/z"}


def test_blocker_is_raisable():
    with pytest.raises(BlockerError) as exc_info:
        raise BlockerError(code="x", what="y")
    assert exc_info.value.code == "x"


def test_blocker_message_includes_status_code_what():
    err = BlockerError(code="drift_detected", what="branches don't match")
    assert "blocked" in str(err)
    assert "drift_detected" in str(err)
    assert "branches don't match" in str(err)


def test_failed_error_status():
    err = FailedError(code="push_rejected", what="remote rejected")
    assert err.to_dict()["status"] == "failed"


def test_action_error_isinstance_chain():
    blk = BlockerError(code="x", what="y")
    fail = FailedError(code="x", what="y")
    assert isinstance(blk, ActionError)
    assert isinstance(fail, ActionError)
    assert not isinstance(blk, FailedError)
    assert not isinstance(fail, BlockerError)


def test_blocker_to_dict_omits_empty_optionals():
    """expected / actual / details should be omitted when not provided."""
    err = BlockerError(code="x", what="y")
    d = err.to_dict()
    assert "expected" not in d
    assert "actual" not in d
    assert "details" not in d
    # fix_actions is always present (even if empty list)
    assert d["fix_actions"] == []


def test_blocker_to_dict_is_json_serializable():
    err = BlockerError(
        code="drift_detected", what="x",
        expected={"a": 1}, actual={"a": 2},
        fix_actions=[FixAction(action="realign", args={"feature": "f"})],
    )
    s = json.dumps(err.to_dict())
    parsed = json.loads(s)
    assert parsed["code"] == "drift_detected"


# ── render_blocker ──────────────────────────────────────────────────────

def _capture_render(err, **kw) -> str:
    buf = Console(record=True, force_terminal=False, width=120)
    render_blocker(err, console=buf, **kw)
    return buf.export_text()


def test_render_blocker_includes_action_and_what():
    err = BlockerError(code="drift_detected", what="branches don't match feature lane")
    out = _capture_render(err, action="ship")
    assert "ship blocked" in out
    assert "branches don't match feature lane" in out
    assert "drift_detected" in out


def test_render_blocker_handles_dict_input():
    """MCP-side consumers pass JSON dicts; renderer should accept them."""
    payload = {
        "status": "blocked",
        "code": "drift_detected",
        "what": "branches don't match",
        "expected": {"api": "doc-3029"},
        "actual": {"api": "main"},
        "fix_actions": [{"action": "realign", "args": {"feature": "doc-3029"},
                          "safe": True, "preview": "checkout doc-3029 in api"}],
    }
    out = _capture_render(payload, action="ship")
    assert "ship blocked" in out
    assert "expected" in out
    assert "actual" in out
    assert "canopy realign doc-3029" in out
    assert "checkout doc-3029 in api" in out


def test_render_blocker_renders_expected_and_actual():
    err = BlockerError(
        code="drift_detected", what="x",
        expected={"api": "doc-3029", "ui": "doc-3029"},
        actual={"api": "doc-3029", "ui": "main"},
    )
    out = _capture_render(err, action="ship")
    assert "expected:" in out
    assert "actual:" in out
    assert "api=doc-3029" in out
    assert "ui=main" in out


def test_render_blocker_renders_fix_actions_with_safety_tag():
    err = BlockerError(
        code="x", what="y",
        fix_actions=[
            FixAction(action="realign", args={"feature": "f"}, safe=True),
            FixAction(action="done", args={"feature": "f", "force": True}, safe=False,
                       preview="will delete unmerged branches"),
        ],
    )
    out = _capture_render(err, action="ship")
    assert "canopy realign f" in out
    assert "canopy done f --force" in out
    assert "(safe)" in out
    assert "(needs review)" in out
    assert "will delete unmerged branches" in out


def test_render_blocker_omits_sections_when_absent():
    err = BlockerError(code="missing_config", what="canopy.toml not found")
    out = _capture_render(err, action="status")
    assert "expected" not in out
    assert "actual" not in out
    assert "fix:" not in out
    assert "details" not in out
    # Header still present
    assert "status blocked" in out


def test_render_blocker_no_action_uses_generic_label():
    err = BlockerError(code="x", what="y")
    out = _capture_render(err)
    # Header falls back to "action" when caller didn't pass an action name
    assert "action blocked" in out


def test_render_blocker_renders_details_block():
    err = BlockerError(
        code="x", what="y",
        details={"workspace_root": "/a/b", "trace_id": "abc123"},
    )
    out = _capture_render(err, action="ship")
    assert "details:" in out
    assert "workspace_root" in out
    assert "/a/b" in out
    assert "trace_id" in out
    assert "abc123" in out
