"""Tests for canopy.providers.linear — LinearProvider.

The MCP transport (call_tool / get_mcp_config) is mocked at the module
import boundary; this exercises the parsing + fan-out + canonical-state
mapping logic, not the MCP client.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from canopy.mcp.client import McpClientError
from canopy.providers.linear import (
    LinearProvider,
    _looks_like_mcp_error,
    _parse_issue_result,
    _to_issue,
)
from canopy.providers.types import (
    IssueNotFoundError,
    IssueProviderError,
    ProviderNotConfigured,
)


def _mcp_text_result(text: str):
    """Build a minimal CallToolResult-shaped object."""
    return SimpleNamespace(content=[SimpleNamespace(text=text)])


# ── _to_issue / _parse_issue_result ──────────────────────────────────────


def test_to_issue_maps_canonical_state():
    issue = _to_issue(
        {"id": "uuid", "identifier": "SIN-1", "title": "t", "state": {"name": "In Progress"}},
        original_id="SIN-1",
    )
    assert issue.state == "in_progress"
    assert issue.identifier == "SIN-1"


def test_to_issue_unknown_state_falls_back_to_todo():
    issue = _to_issue(
        {"id": "uuid", "identifier": "X", "title": "t", "state": {"name": "Discovery"}},
        original_id="X",
    )
    assert issue.state == "todo"


def test_to_issue_preserves_raw_payload():
    payload = {"id": "uuid", "identifier": "X", "title": "t", "state": "Backlog"}
    issue = _to_issue(payload, original_id="X")
    assert issue.raw == payload


def test_to_issue_handles_search_envelope():
    issue = _to_issue(
        {"issues": [{"id": "u", "identifier": "S-1", "title": "first"}]},
        original_id="S-1",
    )
    assert issue.title == "first"


def test_to_issue_empty_list_raises_not_found():
    with pytest.raises(IssueNotFoundError):
        _to_issue([], original_id="X")


def test_to_issue_extracts_labels_and_assignee():
    payload = {
        "id": "u", "identifier": "X", "title": "t",
        "labels": {"nodes": [{"name": "bug"}, {"name": "p1"}]},
        "assignee": {"name": "alice"},
    }
    issue = _to_issue(payload, original_id="X")
    assert issue.labels == ("bug", "p1")
    assert issue.assignee == "alice"


def test_parse_issue_result_recognizes_inline_mcp_error():
    result = _mcp_text_result("Error: not found")
    assert _parse_issue_result(result) is None


def test_parse_issue_result_parses_json_block():
    result = _mcp_text_result('{"id":"u","identifier":"X","title":"t"}')
    parsed = _parse_issue_result(result)
    assert parsed["identifier"] == "X"


def test_looks_like_mcp_error_variants():
    assert _looks_like_mcp_error("Error: x")
    assert _looks_like_mcp_error("MCP error -32602: bad")
    assert _looks_like_mcp_error("Input validation error here")
    assert not _looks_like_mcp_error("Something normal")


# ── LinearProvider — get_issue ───────────────────────────────────────────


def _provider(tmp_path: Path) -> LinearProvider:
    return LinearProvider({}, workspace_root=tmp_path)


def test_get_issue_raises_when_not_configured(tmp_path):
    p = _provider(tmp_path)
    with patch("canopy.providers.linear.get_mcp_config", return_value=None):
        with pytest.raises(ProviderNotConfigured):
            p.get_issue("SIN-1")


def test_get_issue_first_attempt_succeeds(tmp_path):
    p = _provider(tmp_path)
    with patch("canopy.providers.linear.get_mcp_config", return_value={"command": "x"}), \
         patch("canopy.providers.linear.call_tool",
               return_value=_mcp_text_result(
                   '{"id":"u","identifier":"SIN-1","title":"hello","state":{"name":"Started"}}',
               )) as ct:
        issue = p.get_issue("SIN-1")
    assert issue.title == "hello"
    assert issue.state == "in_progress"
    assert ct.call_count == 1


def test_get_issue_falls_back_through_attempts(tmp_path):
    """First two tools error, third returns the issue."""
    p = _provider(tmp_path)
    side = [
        McpClientError("nope"),
        McpClientError("still nope"),
        _mcp_text_result('{"id":"u","identifier":"SIN-2","title":"third"}'),
    ]
    with patch("canopy.providers.linear.get_mcp_config", return_value={"command": "x"}), \
         patch("canopy.providers.linear.call_tool", side_effect=side) as ct:
        issue = p.get_issue("SIN-2")
    assert issue.identifier == "SIN-2"
    assert ct.call_count == 3


def test_get_issue_all_attempts_fail_raises_not_found(tmp_path):
    p = _provider(tmp_path)
    with patch("canopy.providers.linear.get_mcp_config", return_value={"command": "x"}), \
         patch("canopy.providers.linear.call_tool", side_effect=McpClientError("boom")):
        with pytest.raises(IssueNotFoundError):
            p.get_issue("SIN-X")


# ── LinearProvider — list_my_issues ──────────────────────────────────────


def test_list_my_issues_filters_to_open_status_types(tmp_path):
    p = _provider(tmp_path)
    payload = (
        '[{"id":"a","identifier":"SIN-1","title":"open","statusType":"started"},'
        ' {"id":"b","identifier":"SIN-2","title":"closed","statusType":"completed"}]'
    )
    with patch("canopy.providers.linear.get_mcp_config", return_value={"command": "x"}), \
         patch("canopy.providers.linear.call_tool",
               return_value=_mcp_text_result(payload)):
        issues = p.list_my_issues()
    assert len(issues) == 1
    assert issues[0].identifier == "SIN-1"


def test_list_my_issues_envelope_in_dict_response(tmp_path):
    p = _provider(tmp_path)
    payload = (
        '{"issues":[{"id":"a","identifier":"SIN-1","title":"x","statusType":"started"}]}'
    )
    with patch("canopy.providers.linear.get_mcp_config", return_value={"command": "x"}), \
         patch("canopy.providers.linear.call_tool",
               return_value=_mcp_text_result(payload)):
        issues = p.list_my_issues()
    assert len(issues) == 1


def test_list_my_issues_all_attempts_fail_raises(tmp_path):
    p = _provider(tmp_path)
    with patch("canopy.providers.linear.get_mcp_config", return_value={"command": "x"}), \
         patch("canopy.providers.linear.call_tool", side_effect=McpClientError("nope")):
        with pytest.raises(IssueProviderError):
            p.list_my_issues()


def test_list_my_issues_respects_limit(tmp_path):
    p = _provider(tmp_path)
    items = [
        {"id": str(i), "identifier": f"SIN-{i}", "title": "t", "statusType": "started"}
        for i in range(10)
    ]
    import json
    with patch("canopy.providers.linear.get_mcp_config", return_value={"command": "x"}), \
         patch("canopy.providers.linear.call_tool",
               return_value=_mcp_text_result(json.dumps(items))):
        issues = p.list_my_issues(limit=3)
    assert len(issues) == 3


# ── LinearProvider — format_branch_name ──────────────────────────────────


def test_format_branch_name_plain(tmp_path):
    p = _provider(tmp_path)
    assert p.format_branch_name("SIN-7") == "sin-7"


def test_format_branch_name_with_title(tmp_path):
    p = _provider(tmp_path)
    assert p.format_branch_name("SIN-7", title="Add OAuth login flow") == \
           "sin-7-add-oauth-login-flow"


def test_format_branch_name_custom_overrides(tmp_path):
    p = _provider(tmp_path)
    assert p.format_branch_name("SIN-7", title="X", custom_name="my/branch") == "my/branch"


def test_format_branch_name_strips_special_chars(tmp_path):
    p = _provider(tmp_path)
    out = p.format_branch_name("SIN-7", title="Fix: bug? & friends!")
    assert out == "sin-7-fix-bug-friends"


def test_format_branch_name_truncates_long_title(tmp_path):
    p = _provider(tmp_path)
    long_title = "x" * 200
    out = p.format_branch_name("S-1", title=long_title)
    # "s-1-" (4) + slug truncated to 50 = 54 max
    assert len(out) <= 54


# ── update_issue_state — explicitly NotImplemented in v1 ─────────────────


def test_update_issue_state_not_implemented(tmp_path):
    p = _provider(tmp_path)
    with pytest.raises(NotImplementedError):
        p.update_issue_state("SIN-1", "done")


# ── workspace_root sanity ────────────────────────────────────────────────


def test_get_issue_without_root_raises_provider_error():
    p = LinearProvider({})
    with pytest.raises(IssueProviderError):
        p.get_issue("SIN-1")


# ── parse_alias (M5+ Provider Protocol method — F-7) ────────────────────


def test_parse_alias_recognises_linear_id(tmp_path):
    p = _provider(tmp_path)
    assert p.parse_alias("SIN-412") == "SIN-412"
    assert p.parse_alias("ENG-1") == "ENG-1"
    assert p.parse_alias("DOC-12345") == "DOC-12345"


def test_parse_alias_case_insensitive(tmp_path):
    p = _provider(tmp_path)
    assert p.parse_alias("sin-7") == "sin-7"


def test_parse_alias_handles_whitespace(tmp_path):
    p = _provider(tmp_path)
    assert p.parse_alias("  SIN-7  ") == "SIN-7"


def test_parse_alias_returns_none_for_non_linear(tmp_path):
    p = _provider(tmp_path)
    # Bare numbers, GH-shaped, feature names — all None for Linear.
    assert p.parse_alias("142") is None
    assert p.parse_alias("#142") is None
    assert p.parse_alias("owner/repo#142") is None
    assert p.parse_alias("auth-flow") is None
    assert p.parse_alias("https://github.com/o/r/issues/5") is None
