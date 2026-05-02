"""Linear backend for the issue-provider contract.

Refactored from ``integrations/linear.py`` (M5). The original module
remains as a re-export shim for one release cycle so external callers
don't break.

Wraps the canonical Linear MCP tool conventions plus a fan-out of
fallback tool/args shapes for legacy MCP servers. See ``docs/architecture/
providers.md`` §7 for the rationale.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .types import (
    Issue,
    IssueNotFoundError,
    IssueProviderError,
    ProviderNotConfigured,
)
from ..mcp.client import (
    McpClientError,
    call_tool,
    get_mcp_config,
    is_mcp_configured,
)


_MCP_ERROR_PATTERN = re.compile(r"^(error\s*:|mcp error -?\d+\s*:)", re.IGNORECASE)
_OPEN_STATUS_TYPES = {"backlog", "unstarted", "started", "triage"}

# Linear's state names → canonical canopy states.
_LINEAR_STATE_MAP = {
    "backlog": "todo",
    "triage": "todo",
    "todo": "todo",
    "unstarted": "todo",
    "started": "in_progress",
    "in progress": "in_progress",
    "in review": "in_progress",
    "in_progress": "in_progress",
    "completed": "done",
    "done": "done",
    "merged": "done",
    "shipped": "done",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "duplicate": "cancelled",
}


class LinearProvider:
    """Linear MCP-backed issue provider.

    The provider's ``options`` (passed by the registry) come from the
    workspace's ``[issue_provider.linear]`` block. v1 honors:

      - ``api_key_env``: name of the env var holding the Linear API key.
        Default ``"LINEAR_API_KEY"``. The MCP server is what actually reads
        this; canopy just passes config through.

    The provider needs the workspace root to look up MCP config. The
    registry passes a ``Workspace`` reference at construction so each
    method has access without changing the protocol signatures.
    """

    def __init__(self, options: dict[str, Any] | None = None, *, workspace_root: Path | None = None):
        self._options = options or {}
        # workspace_root is set by the registry's factory before first use;
        # tests can also pass it directly.
        self._workspace_root: Path | None = workspace_root
        self.api_key_env: str = self._options.get("api_key_env", "LINEAR_API_KEY")

    # ── Internal helpers ────────────────────────────────────────────────

    def _root(self) -> Path:
        if self._workspace_root is None:
            raise IssueProviderError(
                "LinearProvider has no workspace_root; the registry must set it before use.",
            )
        return self._workspace_root

    def _config(self) -> dict:
        """Fetch the Linear MCP config or raise ``ProviderNotConfigured``."""
        config = get_mcp_config(self._root(), "linear")
        if config is None:
            raise ProviderNotConfigured(
                "Linear MCP not configured. "
                "Add a 'linear' entry to .canopy/mcps.json with command + env "
                "(LINEAR_API_KEY).",
            )
        return config

    def is_configured(self) -> bool:
        """Lightweight check: is the Linear MCP entry present?"""
        return is_mcp_configured(self._root(), "linear")

    # ── Protocol methods ────────────────────────────────────────────────

    def get_issue(self, alias: str) -> Issue:
        """Fetch a Linear issue by identifier (e.g. SIN-7).

        Tries the canonical Linear MCP tool first, then a fan-out of
        legacy server shapes. Raises ``IssueNotFoundError`` if every
        attempt fails.
        """
        config = self._config()

        tool_attempts = [
            ("get_issue", {"id": alias}),
            ("get_issue", {"issue_id": alias}),
            ("linear_get_issue", {"issueId": alias}),
            ("get_issue", {"issueId": alias}),
            ("search_issues", {"query": alias}),
            ("linear_search_issues", {"query": alias}),
        ]

        last_error: McpClientError | None = None
        for tool_name, args in tool_attempts:
            try:
                result = call_tool(config, tool_name, args, timeout=15.0, server_name="linear")
                parsed = _parse_issue_result(result)
                if parsed:
                    return _to_issue(parsed, alias)
            except McpClientError as e:
                last_error = e
                continue

        raise IssueNotFoundError(
            f"Could not fetch Linear issue '{alias}'. "
            f"Last MCP error: {last_error}",
        )

    def list_my_issues(self, limit: int = 50) -> list[Issue]:
        """Return the current user's open Linear issues.

        Tries the canonical ``list_issues(assignee="me")`` first, then a
        fan-out of legacy shapes. Filters server-side responses agent-side
        to ``statusType in {backlog, unstarted, started, triage}`` since
        the canonical Linear MCP doesn't accept a ``state`` filter on
        ``list_issues``.

        Raises ``IssueProviderError`` (with a per-attempt log) if every
        tool/args combo fails. Soft-empty (``[]``) is reserved for the
        configured-but-no-issues case.
        """
        config = self._config()

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

            normalized: list[Issue] = []
            for entry in items[:limit]:
                if not isinstance(entry, dict):
                    continue
                status_type = entry.get("statusType")
                if status_type and str(status_type).lower() not in _OPEN_STATUS_TYPES:
                    continue
                normalized.append(
                    _to_issue(entry, entry.get("identifier", entry.get("id", ""))),
                )
            if normalized:
                return normalized
            attempts_log.append((tool_name, args, "no open issues in response"))

        # All attempts failed — surface the per-attempt log so the caller
        # can render it as a structured BlockerError.
        summary = "\n  ".join(
            f"- {tool}({args}): {err}" for tool, args, err in attempts_log
        )
        raise IssueProviderError(
            f"All Linear MCP attempts failed:\n  {summary}",
        )

    def format_branch_name(
        self,
        issue_id: str,
        title: str | None = None,
        custom_name: str | None = None,
    ) -> str:
        """Format a branch name from a Linear issue.

        - ``custom_name`` overrides everything (returned as-is).
        - With ``title``: ``"<lowercased-issue-id>-<slug>"``.
        - Without: ``"<lowercased-issue-id>"``.
        """
        if custom_name:
            return custom_name
        if not title:
            return issue_id.lower()
        slug = re.sub(r"[^a-zA-Z0-9\s-]", "", title)
        slug = re.sub(r"\s+", "-", slug.strip()).lower()
        slug = slug[:50].rstrip("-")
        return f"{issue_id}-{slug}".lower()

    def update_issue_state(self, alias: str, new_state: str) -> None:
        """Lifecycle automation reserved for a future plan."""
        raise NotImplementedError(
            "LinearProvider.update_issue_state is not implemented in v1. "
            "Track via a future plan if you need write-back.",
        )


# ── Module-level parsers (kept module-level so tests can mock easily) ──


def _parse_issue_result(result: Any) -> dict | list | None:
    """Extract issue data from an MCP tool call result.

    MCP results come as a CallToolResult with .content blocks. Linear MCP
    typically returns a single text block with JSON. Inline MCP errors
    (text blocks starting with ``Error:`` / ``MCP error -32602:``) are
    treated as failure so the caller falls through to the next attempt
    instead of normalizing into an empty issue.
    """
    if result is None:
        return None

    for block in result.content:
        if hasattr(block, "text") and block.text:
            text = block.text.strip()
            if _looks_like_mcp_error(text):
                return None
            if text.startswith("{") or text.startswith("["):
                import json
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    pass
            return {"raw": text}
    return None


def _looks_like_mcp_error(text: str) -> bool:
    """Heuristic: does this text content look like an inline MCP error?"""
    if not text:
        return False
    head = text.strip()[:200]
    return bool(_MCP_ERROR_PATTERN.match(head)) or "Input validation error" in head


def _to_issue(data: dict | list, original_id: str) -> Issue:
    """Map a Linear API response dict into a canonical ``Issue``.

    Handles search-result lists (takes the first match) and nested
    ``{issues: [...]}`` envelopes. Raises ``IssueNotFoundError`` for
    empty results.
    """
    if isinstance(data, list):
        if not data:
            raise IssueNotFoundError(f"No Linear results for '{original_id}'")
        data = data[0]

    if "issues" in data and isinstance(data["issues"], list):
        if not data["issues"]:
            raise IssueNotFoundError(f"No Linear results for '{original_id}'")
        data = data["issues"][0]

    raw_state = (
        data.get("state", {}).get("name")
        if isinstance(data.get("state"), dict)
        else data.get("state") or data.get("status") or ""
    )
    canonical_state = _LINEAR_STATE_MAP.get(str(raw_state).lower(), "todo")

    labels_node = (data.get("labels") or {}).get("nodes", []) if isinstance(data.get("labels"), dict) else (data.get("labels") or [])
    labels: tuple[str, ...] = tuple(
        l.get("name") if isinstance(l, dict) else str(l)
        for l in labels_node
        if (isinstance(l, dict) and l.get("name")) or isinstance(l, str)
    )

    assignee_node = data.get("assignee")
    assignee = (
        assignee_node.get("name") or assignee_node.get("displayName")
        if isinstance(assignee_node, dict) else assignee_node
    )

    return Issue(
        id=str(data.get("id") or data.get("identifier") or original_id),
        identifier=data.get("identifier") or data.get("id") or original_id,
        title=data.get("title") or data.get("name") or "",
        description=data.get("description") or "",
        state=canonical_state,
        url=data.get("url") or "",
        assignee=assignee,
        labels=labels,
        priority=data.get("priority"),
        raw=data if isinstance(data, dict) else None,
    )
