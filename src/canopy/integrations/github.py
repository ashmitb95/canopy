"""
GitHub integration via MCP.

Fetches PR data and review comments from a GitHub MCP server configured
in .canopy/mcps.json. Canopy never talks to GitHub directly — it always
goes through the MCP layer.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..mcp.client import (
    get_mcp_config,
    is_mcp_configured,
    call_tool,
    McpClientError,
)


class GitHubNotConfiguredError(Exception):
    """GitHub MCP is not configured in .canopy/mcps.json."""


class PullRequestNotFoundError(Exception):
    """No pull request found for the given branch."""


def _get_github_config(workspace_root: Path) -> dict:
    """Get GitHub MCP config, raising if not configured."""
    config = get_mcp_config(workspace_root, "github")
    if config is None:
        raise GitHubNotConfiguredError(
            "GitHub MCP not configured.\n"
            "Add a 'github' entry to .canopy/mcps.json:\n"
            "  {\n"
            '    "github": {\n'
            '      "command": "npx",\n'
            '      "args": ["-y", "@modelcontextprotocol/server-github"],\n'
            '      "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_..."}\n'
            "    }\n"
            "  }"
        )
    return config


def is_github_configured(workspace_root: Path) -> bool:
    """Check if GitHub MCP is set up."""
    return is_mcp_configured(workspace_root, "github")


def _parse_mcp_result(result: Any) -> Any:
    """Extract data from an MCP tool call result.

    MCP results come as a CallToolResult with .content blocks.
    GitHub MCP tools typically return a single text block with JSON.
    """
    if result is None:
        return None

    for block in result.content:
        if hasattr(block, "text") and block.text:
            text = block.text.strip()
            if text.startswith("{") or text.startswith("["):
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    pass
            return {"raw": text}
    return None


def _extract_owner_repo(remote_url: str) -> tuple[str, str] | None:
    """Extract owner/repo from a git remote URL.

    Handles:
        git@github.com:owner/repo.git
        https://github.com/owner/repo.git
        https://github.com/owner/repo
    """
    # SSH format
    m = re.match(r"git@github\.com:([^/]+)/([^/.]+?)(?:\.git)?$", remote_url)
    if m:
        return m.group(1), m.group(2)

    # HTTPS format
    m = re.match(r"https?://github\.com/([^/]+)/([^/.]+?)(?:\.git)?$", remote_url)
    if m:
        return m.group(1), m.group(2)

    return None


def find_pull_request(
    workspace_root: Path,
    owner: str,
    repo: str,
    branch: str,
) -> dict | None:
    """Find an open PR for a branch in a repo.

    Returns PR data dict or None if no PR exists.

    The dict includes at minimum: number, title, url, state, head_branch.
    """
    config = _get_github_config(workspace_root)

    # Try common GitHub MCP tool names for listing/searching PRs
    tool_attempts = [
        ("list_pull_requests", {
            "owner": owner,
            "repo": repo,
            "head": f"{owner}:{branch}",
            "state": "open",
        }),
        ("search_pull_requests", {
            "owner": owner,
            "repo": repo,
            "head": branch,
            "state": "open",
        }),
        ("list_pull_requests", {
            "owner": owner,
            "repo": repo,
            "state": "open",
        }),
    ]

    last_error = None
    for tool_name, args in tool_attempts:
        try:
            result = call_tool(config, tool_name, args, timeout=15.0)
            parsed = _parse_mcp_result(result)
            if parsed is None:
                continue

            prs = _extract_prs(parsed, branch)
            if prs:
                return _normalize_pr(prs[0])
        except McpClientError as e:
            last_error = e
            continue

    return None


def _extract_prs(data: Any, branch: str) -> list[dict]:
    """Extract PR list from various MCP response shapes, filtering by branch."""
    if isinstance(data, list):
        prs = data
    elif isinstance(data, dict):
        # Some MCPs wrap in {pull_requests: [...]} or {items: [...]}
        prs = (
            data.get("pull_requests")
            or data.get("items")
            or data.get("data")
            or []
        )
        if not isinstance(prs, list):
            prs = [data]
    else:
        return []

    # Filter to PRs matching the branch
    matched = []
    for pr in prs:
        head = pr.get("head", {})
        head_ref = head.get("ref", "") if isinstance(head, dict) else ""
        if head_ref == branch or pr.get("head_branch") == branch:
            matched.append(pr)

    # If the initial query already filtered by head, all results match
    if not matched and prs:
        # The API might have already filtered — check if any PR exists
        # that looks right
        for pr in prs:
            head = pr.get("head", {})
            head_ref = head.get("ref", "") if isinstance(head, dict) else ""
            if branch in (head_ref or pr.get("head_branch", "")):
                matched.append(pr)

    return matched


def _normalize_pr(data: dict) -> dict:
    """Normalize PR data into a consistent shape."""
    head = data.get("head") or {}
    head_branch = ""
    if isinstance(head, dict):
        head_branch = head.get("ref", "")
    if not head_branch:
        head_branch = data.get("head_branch") or ""
    return {
        "number": data.get("number") or data.get("id"),
        "title": data.get("title") or "",
        "url": data.get("html_url") or data.get("url") or "",
        "state": data.get("state") or "open",
        "head_branch": head_branch,
        "body": data.get("body") or "",
    }


def get_review_comments(
    workspace_root: Path,
    owner: str,
    repo: str,
    pr_number: int,
) -> list[dict]:
    """Fetch review comments for a PR.

    Returns list of comment dicts, each with:
        path, line, body, author, state (if available), created_at, url
    """
    config = _get_github_config(workspace_root)

    # Try different tool names
    tool_attempts = [
        ("get_pull_request_comments", {
            "owner": owner,
            "repo": repo,
            "pull_number": pr_number,
        }),
        ("list_review_comments", {
            "owner": owner,
            "repo": repo,
            "pull_number": pr_number,
        }),
        ("get_pull_request_reviews", {
            "owner": owner,
            "repo": repo,
            "pull_number": pr_number,
        }),
    ]

    last_error = None
    for tool_name, args in tool_attempts:
        try:
            result = call_tool(config, tool_name, args, timeout=15.0)
            parsed = _parse_mcp_result(result)
            if parsed is not None:
                return _normalize_comments(parsed)
        except McpClientError as e:
            last_error = e
            continue

    # If all tool names failed, return empty (not an error — PR might
    # have no comments, or the MCP server uses unknown tool names)
    return []


def _normalize_comments(data: Any) -> list[dict]:
    """Normalize review comments from various MCP response shapes.

    Filters to unresolved comments where possible.
    """
    if isinstance(data, list):
        comments = data
    elif isinstance(data, dict):
        comments = (
            data.get("comments")
            or data.get("data")
            or data.get("items")
            or []
        )
        if not isinstance(comments, list):
            comments = [data]
    else:
        return []

    normalized = []
    for c in comments:
        # Skip resolved comments if the field is available
        if c.get("resolved", False) or c.get("state") == "RESOLVED":
            continue

        # Skip bot comments and system comments
        author = c.get("user", {})
        if isinstance(author, dict):
            author_login = author.get("login", "")
            author_type = author.get("type", "")
            if author_type == "Bot":
                continue
        else:
            author_login = str(author) if author else ""

        normalized.append({
            "path": c.get("path") or c.get("file") or "",
            "line": c.get("line") or c.get("original_line") or c.get("position") or 0,
            "body": c.get("body") or "",
            "author": author_login or c.get("author", ""),
            "state": c.get("state") or "",
            "created_at": c.get("created_at") or c.get("createdAt") or "",
            "url": c.get("html_url") or c.get("url") or "",
            "in_reply_to_id": c.get("in_reply_to_id"),
        })

    return normalized
