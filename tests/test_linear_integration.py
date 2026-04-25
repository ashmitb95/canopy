"""
Tests for Linear integration, MCP client config, and worktree create with issue linking.
"""
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

import pytest

from canopy.git import repo as git
from canopy.features.coordinator import FeatureCoordinator
from canopy.workspace.config import WorkspaceConfig, RepoConfig
from canopy.workspace.workspace import Workspace
from canopy.mcp.client import (
    _load_mcp_configs,
    get_mcp_config,
    is_mcp_configured,
    McpClientError,
)
from canopy.integrations.linear import (
    is_linear_configured,
    format_branch_name,
    list_my_issues,
    list_my_issues_strict,
    get_issue,
    _normalize_issue,
    _parse_issue_result,
    _looks_like_mcp_error,
    LinearNotConfiguredError,
    LinearIssueNotFoundError,
    LinearCallError,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_workspace(workspace_dir) -> Workspace:
    config = WorkspaceConfig(
        name="test",
        repos=[
            RepoConfig(name="api", path="./api", role="backend", lang="python"),
            RepoConfig(name="ui", path="./ui", role="frontend", lang="typescript"),
        ],
        root=workspace_dir,
    )
    return Workspace(config)


# ── MCP client config ───────────────────────────────────────────────────

class TestMcpConfig:
    def test_load_configs_no_file(self, tmp_path):
        """Returns empty dict when no mcps.json exists."""
        assert _load_mcp_configs(tmp_path) == {}

    def test_load_configs_valid(self, tmp_path):
        config = {
            "linear": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-linear"],
                "env": {"LINEAR_API_KEY": "lin_test_123"},
            }
        }
        (tmp_path / ".canopy").mkdir()
        (tmp_path / ".canopy" / "mcps.json").write_text(json.dumps(config))

        result = _load_mcp_configs(tmp_path)
        assert "linear" in result
        assert result["linear"]["command"] == "npx"

    def test_get_mcp_config_found(self, tmp_path):
        config = {"linear": {"command": "test"}}
        (tmp_path / ".canopy").mkdir()
        (tmp_path / ".canopy" / "mcps.json").write_text(json.dumps(config))

        result = get_mcp_config(tmp_path, "linear")
        assert result == {"command": "test"}

    def test_get_mcp_config_not_found(self, tmp_path):
        assert get_mcp_config(tmp_path, "linear") is None

    def test_is_mcp_configured(self, tmp_path):
        assert is_mcp_configured(tmp_path, "linear") is False

        config = {"linear": {"command": "test"}}
        (tmp_path / ".canopy").mkdir()
        (tmp_path / ".canopy" / "mcps.json").write_text(json.dumps(config))
        assert is_mcp_configured(tmp_path, "linear") is True

    def test_load_from_dot_mcp_json(self, tmp_path):
        """Entries in .mcp.json (Claude Code format) are picked up."""
        shared = {
            "mcpServers": {
                "linear": {
                    "command": "npx",
                    "args": ["-y", "linear-mcp-server"],
                    "env": {"LINEAR_API_KEY": "lin_shared"},
                }
            }
        }
        (tmp_path / ".mcp.json").write_text(json.dumps(shared))

        result = _load_mcp_configs(tmp_path)
        assert "linear" in result
        assert result["linear"]["env"]["LINEAR_API_KEY"] == "lin_shared"

    def test_canopy_mcps_overrides_dot_mcp_json(self, tmp_path):
        """.canopy/mcps.json overrides .mcp.json on key collision."""
        (tmp_path / ".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "linear": {"command": "old", "env": {"LINEAR_API_KEY": "from-shared"}},
                    }
                }
            )
        )
        (tmp_path / ".canopy").mkdir()
        (tmp_path / ".canopy" / "mcps.json").write_text(
            json.dumps({"linear": {"command": "new", "env": {"LINEAR_API_KEY": "from-canopy"}}})
        )

        result = _load_mcp_configs(tmp_path)
        assert result["linear"]["command"] == "new"
        assert result["linear"]["env"]["LINEAR_API_KEY"] == "from-canopy"

    def test_merges_non_overlapping_servers(self, tmp_path):
        """Both files contribute when they define different servers."""
        (tmp_path / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"linear": {"command": "linear-mcp-server"}}})
        )
        (tmp_path / ".canopy").mkdir()
        (tmp_path / ".canopy" / "mcps.json").write_text(
            json.dumps({"github": {"command": "github-mcp-server"}})
        )

        result = _load_mcp_configs(tmp_path)
        assert set(result) == {"linear", "github"}


# ── Linear helpers ──────────────────────────────────────────────────────

class TestLinearHelpers:
    def test_format_branch_name_with_title(self):
        result = format_branch_name("ENG-123", "Add payment flow")
        assert result == "eng-123-add-payment-flow"

    def test_format_branch_name_custom(self):
        result = format_branch_name("ENG-123", "whatever", custom_name="payment-flow")
        assert result == "payment-flow"

    def test_format_branch_name_no_title(self):
        result = format_branch_name("ENG-123")
        assert result == "eng-123"

    def test_format_branch_name_special_chars(self):
        result = format_branch_name("ENG-123", "Add (payment) flow! #2")
        assert result == "eng-123-add-payment-flow-2"

    def test_format_branch_name_long_title(self):
        result = format_branch_name("ENG-1", "a" * 100)
        # Should be capped
        assert len(result) <= 60

    def test_normalize_issue_flat(self):
        data = {
            "identifier": "ENG-123",
            "title": "Fix auth",
            "state": {"name": "In Progress"},
            "url": "https://linear.app/...",
        }
        result = _normalize_issue(data, "ENG-123")
        assert result["identifier"] == "ENG-123"
        assert result["title"] == "Fix auth"
        assert result["state"] == "In Progress"

    def test_normalize_issue_list(self):
        data = [{"identifier": "ENG-123", "title": "Fix auth"}]
        result = _normalize_issue(data, "ENG-123")
        assert result["identifier"] == "ENG-123"

    def test_normalize_issue_nested(self):
        data = {"issues": [{"identifier": "ENG-123", "title": "Fix auth"}]}
        result = _normalize_issue(data, "ENG-123")
        assert result["identifier"] == "ENG-123"

    def test_normalize_issue_empty_list(self):
        with pytest.raises(LinearIssueNotFoundError):
            _normalize_issue([], "ENG-123")

    def test_is_linear_configured(self, tmp_path):
        assert is_linear_configured(tmp_path) is False

    def test_parse_issue_result_none(self):
        assert _parse_issue_result(None) is None

    def test_parse_issue_result_text_json(self):
        @dataclass
        class FakeBlock:
            text: str = ""

        @dataclass
        class FakeResult:
            content: list = None
            def __post_init__(self):
                if self.content is None:
                    self.content = []

        result = FakeResult(content=[FakeBlock(text='{"identifier": "ENG-1", "title": "Test"}')])
        parsed = _parse_issue_result(result)
        assert parsed["identifier"] == "ENG-1"


# ── list_my_issues ──────────────────────────────────────────────────────

class TestListMyIssues:
    def test_returns_empty_when_not_configured(self, tmp_path):
        assert list_my_issues(tmp_path) == []

    def test_returns_normalized_issues(self, tmp_path):
        config = {"linear": {"command": "echo"}}
        (tmp_path / ".canopy").mkdir()
        (tmp_path / ".canopy" / "mcps.json").write_text(json.dumps(config))

        @dataclass
        class FakeBlock:
            text: str

        @dataclass
        class FakeResult:
            content: list

        fake_payload = json.dumps({
            "issues": [
                {
                    "identifier": "ENG-518",
                    "title": "Add SSO",
                    "state": {"name": "Triage"},
                    "url": "https://linear.app/x/ENG-518",
                },
                {
                    "identifier": "ENG-522",
                    "title": "Rate-limit auth",
                    "state": "Backlog",
                    "url": "https://linear.app/x/ENG-522",
                },
            ]
        })
        fake_result = FakeResult(content=[FakeBlock(text=fake_payload)])

        with patch("canopy.integrations.linear.call_tool", return_value=fake_result):
            issues = list_my_issues(tmp_path)

        assert len(issues) == 2
        assert issues[0]["identifier"] == "ENG-518"
        assert issues[0]["title"] == "Add SSO"
        assert issues[0]["state"] == "Triage"
        assert issues[1]["identifier"] == "ENG-522"

    def test_returns_empty_when_all_tools_fail(self, tmp_path):
        config = {"linear": {"command": "echo"}}
        (tmp_path / ".canopy").mkdir()
        (tmp_path / ".canopy" / "mcps.json").write_text(json.dumps(config))

        with patch(
            "canopy.integrations.linear.call_tool",
            side_effect=McpClientError("nope"),
        ):
            assert list_my_issues(tmp_path) == []


# ── B1: inline MCP-error detection + canonical arg shapes ───────────────

@dataclass
class _Block:
    text: str

@dataclass
class _Result:
    content: list


class TestInlineMcpErrorDetection:
    """The Linear MCP returns validation errors as text content, not as
    JSON-RPC errors. _parse_issue_result must treat those as failure so
    get_issue/list_my_issues_strict fall through to the next attempt."""

    def test_looks_like_mcp_error_variants(self):
        assert _looks_like_mcp_error("Error: something broke")
        assert _looks_like_mcp_error("MCP error -32602: Input validation error")
        assert _looks_like_mcp_error("error: lower case is fine too")
        assert _looks_like_mcp_error('{"x": 1} ... Input validation error somewhere')
        assert not _looks_like_mcp_error('{"identifier": "ENG-1"}')
        assert not _looks_like_mcp_error("")
        assert not _looks_like_mcp_error("Error reading is part of the title")  # fine — leading "Error " not "Error:"

    def test_parse_issue_result_treats_inline_error_as_failure(self):
        """An MCP-error text response must NOT be normalized into a fake issue."""
        err_text = (
            "MCP error -32602: Input validation error: Invalid arguments for "
            'tool get_issue: [\n  {"path": ["id"], "message": "Invalid input"}\n]'
        )
        result = _Result(content=[_Block(text=err_text)])
        assert _parse_issue_result(result) is None

    def test_parse_issue_result_succeeds_on_valid_json(self):
        result = _Result(content=[_Block(text='{"id": "SIN-5", "title": "Test"}')])
        parsed = _parse_issue_result(result)
        assert parsed["id"] == "SIN-5"


class TestGetIssueCanonicalShape:
    """get_issue must try canonical Linear MCP shape ({id: ...}) first."""

    def test_get_issue_with_canonical_id_arg_succeeds(self, tmp_path):
        config = {"linear": {"command": "echo"}}
        (tmp_path / ".canopy").mkdir()
        (tmp_path / ".canopy" / "mcps.json").write_text(json.dumps(config))

        captured_calls = []

        def fake_call_tool(_cfg, tool_name, args, **_kw):
            captured_calls.append((tool_name, dict(args)))
            if tool_name == "get_issue" and args == {"id": "SIN-5"}:
                return _Result(content=[_Block(text=json.dumps(
                    {"id": "SIN-5", "title": "Test", "state": "Todo",
                     "url": "https://linear.app/x/SIN-5"},
                ))])
            raise McpClientError("nope")

        with patch("canopy.integrations.linear.call_tool", side_effect=fake_call_tool):
            issue = get_issue(tmp_path, "SIN-5")

        # First attempt must be canonical {id: ...}
        assert captured_calls[0] == ("get_issue", {"id": "SIN-5"})
        assert issue["title"] == "Test"

    def test_get_issue_propagates_inline_error_to_next_attempt(self, tmp_path):
        """Inline MCP error from one attempt → fall through, not normalize as empty."""
        config = {"linear": {"command": "echo"}}
        (tmp_path / ".canopy").mkdir()
        (tmp_path / ".canopy" / "mcps.json").write_text(json.dumps(config))

        err = _Result(content=[_Block(text="MCP error -32602: Input validation error")])
        ok = _Result(content=[_Block(text=json.dumps({"id": "SIN-5", "title": "Real"}))])
        responses = [err, ok]

        def fake_call_tool(*_a, **_k):
            return responses.pop(0)

        with patch("canopy.integrations.linear.call_tool", side_effect=fake_call_tool):
            issue = get_issue(tmp_path, "SIN-5")

        assert issue["title"] == "Real"  # not "" from a normalized error


class TestListMyIssuesStrict:
    """The strict variant raises LinearCallError with a per-attempt log."""

    def test_strict_raises_on_all_fail(self, tmp_path):
        config = {"linear": {"command": "echo"}}
        (tmp_path / ".canopy").mkdir()
        (tmp_path / ".canopy" / "mcps.json").write_text(json.dumps(config))

        with patch(
            "canopy.integrations.linear.call_tool",
            side_effect=McpClientError("schema mismatch"),
        ):
            with pytest.raises(LinearCallError) as exc_info:
                list_my_issues_strict(tmp_path)

        # attempts log carries every attempted tool/args pair
        assert len(exc_info.value.attempts) >= 1
        assert all(isinstance(t, tuple) and len(t) == 3 for t in exc_info.value.attempts)
        assert "schema mismatch" in str(exc_info.value)

    def test_soft_returns_empty_when_strict_raises(self, tmp_path):
        """list_my_issues (soft) preserves the no-autocomplete contract."""
        config = {"linear": {"command": "echo"}}
        (tmp_path / ".canopy").mkdir()
        (tmp_path / ".canopy" / "mcps.json").write_text(json.dumps(config))

        with patch(
            "canopy.integrations.linear.call_tool",
            side_effect=McpClientError("nope"),
        ):
            assert list_my_issues(tmp_path) == []

    def test_status_type_filter_drops_completed(self, tmp_path):
        """Canonical Linear MCP includes statusType per issue; closed/canceled
        get filtered agent-side since list_issues no longer accepts state."""
        config = {"linear": {"command": "echo"}}
        (tmp_path / ".canopy").mkdir()
        (tmp_path / ".canopy" / "mcps.json").write_text(json.dumps(config))

        payload = json.dumps({
            "issues": [
                {"id": "SIN-1", "title": "open", "statusType": "started",
                 "state": "In Progress", "url": "u1"},
                {"id": "SIN-2", "title": "done", "statusType": "completed",
                 "state": "Done", "url": "u2"},
                {"id": "SIN-3", "title": "todo", "statusType": "unstarted",
                 "state": "Todo", "url": "u3"},
                {"id": "SIN-4", "title": "canceled", "statusType": "canceled",
                 "state": "Canceled", "url": "u4"},
            ],
        })

        with patch(
            "canopy.integrations.linear.call_tool",
            return_value=_Result(content=[_Block(text=payload)]),
        ):
            issues = list_my_issues_strict(tmp_path)

        ids = [i["identifier"] for i in issues]
        assert ids == ["SIN-1", "SIN-3"]

    def test_status_type_absent_keeps_all(self, tmp_path):
        """Legacy MCP responses without statusType pass through unfiltered."""
        config = {"linear": {"command": "echo"}}
        (tmp_path / ".canopy").mkdir()
        (tmp_path / ".canopy" / "mcps.json").write_text(json.dumps(config))

        payload = json.dumps({
            "issues": [
                {"identifier": "ENG-1", "title": "a", "url": "u1"},
                {"identifier": "ENG-2", "title": "b", "url": "u2"},
            ],
        })

        with patch(
            "canopy.integrations.linear.call_tool",
            return_value=_Result(content=[_Block(text=payload)]),
        ):
            issues = list_my_issues_strict(tmp_path)

        assert len(issues) == 2

    def test_strict_prefers_canonical_call_first(self, tmp_path):
        """First attempt is list_issues({assignee: 'me'}), not the legacy
        list_issues({assignee: 'me', state: 'open'}) which Linear rejects."""
        config = {"linear": {"command": "echo"}}
        (tmp_path / ".canopy").mkdir()
        (tmp_path / ".canopy" / "mcps.json").write_text(json.dumps(config))

        captured = []

        def fake(_cfg, tool, args, **_k):
            captured.append((tool, dict(args)))
            if tool == "list_issues" and args == {"assignee": "me"}:
                return _Result(content=[_Block(text=json.dumps(
                    {"issues": [{"id": "SIN-1", "title": "x", "statusType": "started",
                                 "url": "u"}]},
                ))])
            raise McpClientError("not this one")

        with patch("canopy.integrations.linear.call_tool", side_effect=fake):
            issues = list_my_issues_strict(tmp_path)

        assert captured[0] == ("list_issues", {"assignee": "me"})
        assert len(issues) == 1


# ── Feature create with Linear metadata ─────────────────────────────────

class TestFeatureCreateWithLinear:
    def test_create_stores_linear_metadata(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        coordinator = FeatureCoordinator(ws)

        lane = coordinator.create(
            "payment-flow",
            use_worktrees=True,
            linear_issue="ENG-123",
            linear_title="Add payment processing",
            linear_url="https://linear.app/test/ENG-123",
        )

        assert lane.linear_issue == "ENG-123"
        assert lane.linear_title == "Add payment processing"
        assert lane.linear_url == "https://linear.app/test/ENG-123"

        # Verify persisted in features.json
        features_path = workspace_dir / ".canopy" / "features.json"
        features = json.loads(features_path.read_text())
        assert features["payment-flow"]["linear_issue"] == "ENG-123"
        assert features["payment-flow"]["linear_title"] == "Add payment processing"

    def test_create_without_linear(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        coordinator = FeatureCoordinator(ws)

        lane = coordinator.create("no-linear", use_worktrees=True)

        assert lane.linear_issue == ""
        d = lane.to_dict()
        assert "linear_issue" not in d  # Not included when empty

    def test_status_loads_linear_metadata(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        coordinator = FeatureCoordinator(ws)

        coordinator.create(
            "linked-feat",
            use_worktrees=True,
            linear_issue="ENG-456",
            linear_title="Fix login bug",
            linear_url="https://linear.app/test/ENG-456",
        )

        # Fresh coordinator to simulate reload
        coordinator2 = FeatureCoordinator(ws)
        lane = coordinator2.status("linked-feat")
        assert lane.linear_issue == "ENG-456"
        assert lane.linear_title == "Fix login bug"

        d = lane.to_dict()
        assert d["linear_issue"] == "ENG-456"

    def test_list_active_loads_linear_metadata(self, workspace_dir):
        ws = _make_workspace(workspace_dir)
        coordinator = FeatureCoordinator(ws)

        coordinator.create(
            "feat-with-linear",
            use_worktrees=True,
            linear_issue="ENG-789",
            linear_title="Migrate database",
        )

        coordinator2 = FeatureCoordinator(ws)
        lanes = coordinator2.list_active()
        linked = [l for l in lanes if l.name == "feat-with-linear"]
        assert len(linked) == 1
        assert linked[0].linear_issue == "ENG-789"

    def test_worktrees_live_after_linear_create(self, workspace_dir):
        """worktrees_live still works when features have Linear metadata."""
        ws = _make_workspace(workspace_dir)
        coordinator = FeatureCoordinator(ws)

        coordinator.create(
            "live-linear",
            use_worktrees=True,
            linear_issue="ENG-100",
            linear_title="Add caching",
        )

        result = coordinator.worktrees_live()
        assert "live-linear" in result["features"]
        api_info = result["features"]["live-linear"]["repos"]["api"]
        assert api_info["branch"] == "live-linear"
