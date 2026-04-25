"""
Linear integration via MCP.

Fetches issue data from a Linear MCP server configured in .canopy/mcps.json.
Canopy never talks to Linear directly — it always goes through the MCP layer.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..mcp.client import (
    get_mcp_config,
    is_mcp_configured,
    call_tool,
    McpClientError,
)


class LinearNotConfiguredError(Exception):
    """Linear MCP is not configured in .canopy/mcps.json."""


class LinearIssueNotFoundError(Exception):
    """Could not find the requested Linear issue."""


class LinearCallError(Exception):
    """Every attempt to call the Linear MCP server failed.

    Carries the per-attempt log so callers (e.g. the MCP server tool wrapper)
    can convert this into a structured ``BlockerError`` and the agent sees
    why every attempt failed instead of an empty list.
    """

    def __init__(self, attempts: list[tuple[str, dict, str]]):
        self.attempts = attempts
        summary = "\n  ".join(
            f"- {tool}({args}): {err}" for tool, args, err in attempts
        )
        super().__init__(f"All Linear MCP attempts failed:\n  {summary}")


_MCP_ERROR_PATTERN = re.compile(r"^(error\s*:|mcp error -?\d+\s*:)", re.IGNORECASE)


def _looks_like_mcp_error(text: str) -> bool:
    """True when an MCP tool's text response is itself an error payload.

    The Linear MCP returns validation errors as a normal text content block
    rather than as a JSON-RPC error, so a naive parser sees them as success.
    Detect the leading ``Error:``/``MCP error -32602:`` marker (and the
    common ``Input validation error`` body) and treat as failure.
    """
    if not text:
        return False
    head = text.strip()[:200]
    return bool(_MCP_ERROR_PATTERN.match(head)) or "Input validation error" in head


_OPEN_STATUS_TYPES = {"backlog", "unstarted", "started", "triage"}


def _get_linear_config(workspace_root: Path) -> dict:
    """Get Linear MCP config, raising if not configured."""
    config = get_mcp_config(workspace_root, "linear")
    if config is None:
        raise LinearNotConfiguredError(
            "Linear MCP not configured.\n"
            "Add a 'linear' entry to .canopy/mcps.json:\n"
            "  {\n"
            '    "linear": {\n'
            '      "command": "npx",\n'
            '      "args": ["-y", "linear-mcp-server"],\n'
            '      "env": {"LINEAR_API_KEY": "lin_api_..."}\n'
            "    }\n"
            "  }"
        )
    return config


def is_linear_configured(workspace_root: Path) -> bool:
    """Check if Linear MCP is set up."""
    return is_mcp_configured(workspace_root, "linear")


def _parse_issue_result(result: Any) -> dict | None:
    """Extract issue data from an MCP tool call result.

    MCP results come as a CallToolResult with .content blocks.
    Linear MCP tools typically return a single text block with JSON.
    """
    if result is None:
        return None

    # result is a CallToolResult — iterate content blocks
    for block in result.content:
        if hasattr(block, "text") and block.text:
            text = block.text.strip()
            # Inline MCP error surfaced as text content (Linear MCP does this
            # for validation failures). Treat as failure so the caller falls
            # through to the next tool/args attempt instead of normalizing
            # into an empty issue.
            if _looks_like_mcp_error(text):
                return None
            # Try to parse as JSON
            if text.startswith("{") or text.startswith("["):
                import json
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    pass
            # If not JSON, return as raw text
            return {"raw": text}
    return None


def get_issue(workspace_root: Path, issue_id: str) -> dict:
    """Fetch a Linear issue by identifier (e.g. ENG-123).

    Returns a dict with at least: identifier, title, state, url.
    The exact shape depends on the Linear MCP server's response.

    Raises:
        LinearNotConfiguredError: If Linear MCP isn't in mcps.json.
        LinearIssueNotFoundError: If the issue doesn't exist.
        McpClientError: If the MCP call fails.
    """
    config = _get_linear_config(workspace_root)

    # Canonical Linear MCP (mcp.linear.app) is first; legacy servers follow.
    tool_attempts = [
        ("get_issue", {"id": issue_id}),
        ("get_issue", {"issue_id": issue_id}),
        ("linear_get_issue", {"issueId": issue_id}),
        ("get_issue", {"issueId": issue_id}),
        ("search_issues", {"query": issue_id}),
        ("linear_search_issues", {"query": issue_id}),
    ]

    last_error = None
    for tool_name, args in tool_attempts:
        try:
            result = call_tool(config, tool_name, args, timeout=15.0, server_name="linear")
            parsed = _parse_issue_result(result)
            if parsed:
                return _normalize_issue(parsed, issue_id)
        except McpClientError as e:
            last_error = e
            continue

    raise LinearIssueNotFoundError(
        f"Could not fetch issue '{issue_id}' from Linear MCP. "
        f"Last error: {last_error}"
    )


def _normalize_issue(data: dict, original_id: str) -> dict:
    """Normalize issue data into a consistent shape.

    Different MCP servers return different schemas. This normalizes
    to: {identifier, title, state, url, description, raw}.
    """
    # If it's a search result (list), take the first match
    if isinstance(data, list):
        if not data:
            raise LinearIssueNotFoundError(f"No results for '{original_id}'")
        data = data[0]

    # Handle nested results (some MCPs wrap in {issues: [...]})
    if "issues" in data and isinstance(data["issues"], list):
        if not data["issues"]:
            raise LinearIssueNotFoundError(f"No results for '{original_id}'")
        data = data["issues"][0]

    return {
        "identifier": data.get("identifier") or data.get("id") or original_id,
        "title": data.get("title") or data.get("name") or "",
        "state": (
            data.get("state", {}).get("name")
            if isinstance(data.get("state"), dict)
            else data.get("state") or data.get("status") or ""
        ),
        "url": data.get("url") or "",
        "description": data.get("description") or "",
        "raw": data,
    }


def list_my_issues_strict(workspace_root: Path, limit: int = 25) -> list[dict]:
    """Fetch open Linear issues assigned to the current user; raise on failure.

    Canonical Linear MCP (mcp.linear.app) attempts come first; legacy server
    shapes follow as fallbacks. When the canonical attempt succeeds with a
    full issue list, results are filtered agent-side to ``statusType in
    {backlog, unstarted, started, triage}`` (Linear's ``state`` arg isn't
    accepted on ``list_issues`` — filtering server-side is impossible).

    Raises:
        LinearNotConfiguredError: Linear MCP not in mcps.json.
        LinearCallError: Every tool/args combination failed. Carries the
            per-attempt log so the caller can build a structured error.
    """
    config = _get_linear_config(workspace_root)

    tool_attempts = [
        ("list_issues", {"assignee": "me"}),
        ("list_my_issues", {}),
        ("linear_list_my_issues", {}),
        ("get_my_issues", {}),
        ("list_issues", {"assignee": "me", "state": "open"}),
        ("linear_list_issues", {"assignee": "me", "state": "open"}),
        ("search_issues", {"query": "assignee:me state:open"}),
    ]
    attempts_log: list[tuple[str, dict, str]] = []

    for tool_name, args in tool_attempts:
        try:
            result = call_tool(
                config, tool_name, args, timeout=15.0, server_name="linear",
            )
        except McpClientError as e:
            attempts_log.append((tool_name, args, str(e)))
            continue
        parsed = _parse_issue_result(result)
        if parsed is None:
            attempts_log.append(
                (tool_name, args, "no usable response (parse failed or inline MCP error)"),
            )
            continue

        items = parsed
        if isinstance(items, dict):
            for key in ("issues", "results", "data", "items"):
                if isinstance(items.get(key), list):
                    items = items[key]
                    break
        if not isinstance(items, list):
            attempts_log.append(
                (tool_name, args, f"unexpected response shape: {type(items).__name__}"),
            )
            continue

        normalized = []
        for entry in items[:limit]:
            if not isinstance(entry, dict):
                continue
            status_type = entry.get("statusType")
            if status_type and str(status_type).lower() not in _OPEN_STATUS_TYPES:
                continue
            issue = _normalize_issue(
                entry, entry.get("identifier", entry.get("id", "")),
            )
            normalized.append({
                "identifier": issue["identifier"],
                "title": issue["title"],
                "state": issue["state"],
                "url": issue["url"],
            })
        if normalized:
            return normalized
        attempts_log.append((tool_name, args, "no open issues in response"))

    raise LinearCallError(attempts_log)


def list_my_issues(workspace_root: Path, limit: int = 25) -> list[dict]:
    """Soft wrapper around :func:`list_my_issues_strict`.

    Returns ``[]`` whenever Linear isn't configured or every attempt failed,
    preserving the existing "no autocomplete available" contract for the
    VSCode extension's Create Feature quick pick.

    Agent-facing surfaces should call :func:`list_my_issues_strict` and
    convert :class:`LinearCallError` into a structured ``BlockerError`` so
    the agent sees the real reason instead of an empty list.
    """
    if not is_linear_configured(workspace_root):
        return []
    try:
        return list_my_issues_strict(workspace_root, limit=limit)
    except (LinearNotConfiguredError, LinearCallError):
        return []


def format_branch_name(issue_id: str, title: str = "", custom_name: str = "") -> str:
    """Format a branch name from a Linear issue.

    If custom_name is provided, use it as-is.
    Otherwise, format as: <issue-id>-<slugified-title>

    Examples:
        format_branch_name("ENG-123", "Add payment flow") → "ENG-123-add-payment-flow"
        format_branch_name("ENG-123", "", "payment-flow") → "payment-flow"
    """
    if custom_name:
        return custom_name

    if not title:
        return issue_id.lower()

    slug = re.sub(r"[^a-zA-Z0-9\s-]", "", title)
    slug = re.sub(r"\s+", "-", slug.strip()).lower()
    slug = slug[:50].rstrip("-")  # Cap length

    return f"{issue_id}-{slug}".lower()
