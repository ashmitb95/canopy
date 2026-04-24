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

    # Try common Linear MCP tool names
    # Different Linear MCP servers use different tool names
    tool_attempts = [
        ("get_issue", {"issue_id": issue_id}),
        ("linear_get_issue", {"issueId": issue_id}),
        ("get_issue", {"issueId": issue_id}),
        ("search_issues", {"query": issue_id}),
        ("linear_search_issues", {"query": issue_id}),
    ]

    last_error = None
    for tool_name, args in tool_attempts:
        try:
            result = call_tool(config, tool_name, args, timeout=15.0)
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


def list_my_issues(workspace_root: Path, limit: int = 25) -> list[dict]:
    """Fetch open Linear issues assigned to the current user.

    Used by the VSCode extension's "Create Feature" quick pick to populate
    autocomplete suggestions. Returns an empty list (never raises) if the
    Linear MCP isn't configured or doesn't expose a usable list tool — the
    extension treats this as "no autocomplete available."

    Returns:
        List of {identifier, title, state, url}.
    """
    if not is_linear_configured(workspace_root):
        return []

    try:
        config = _get_linear_config(workspace_root)
    except LinearNotConfiguredError:
        return []

    tool_attempts = [
        ("list_my_issues", {}),
        ("linear_list_my_issues", {}),
        ("get_my_issues", {}),
        ("list_issues", {"assignee": "me", "state": "open"}),
        ("linear_list_issues", {"assignee": "me", "state": "open"}),
        ("search_issues", {"query": "assignee:me state:open"}),
    ]

    for tool_name, args in tool_attempts:
        try:
            result = call_tool(config, tool_name, args, timeout=15.0)
        except McpClientError:
            continue
        parsed = _parse_issue_result(result)
        if parsed is None:
            continue

        items = parsed
        if isinstance(items, dict):
            for key in ("issues", "results", "data", "items"):
                if isinstance(items.get(key), list):
                    items = items[key]
                    break
        if not isinstance(items, list):
            continue

        normalized = []
        for entry in items[:limit]:
            if not isinstance(entry, dict):
                continue
            issue = _normalize_issue(entry, entry.get("identifier", ""))
            normalized.append({
                "identifier": issue["identifier"],
                "title": issue["title"],
                "state": issue["state"],
                "url": issue["url"],
            })
        if normalized:
            return normalized

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
