"""
GitHub integration via MCP, with gh CLI fallback.

Fetches PR data and review comments from a GitHub MCP server configured
in .canopy/mcps.json when available, falling back to the user's local
``gh`` CLI when MCP isn't configured. Same return shapes either way so
upstream callers don't branch.
"""
from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..mcp.client import (
    get_mcp_config,
    is_mcp_configured,
    call_tool,
    McpClientError,
)


class GitHubNotConfiguredError(Exception):
    """Neither GitHub MCP nor authenticated gh CLI is available.

    Carries the same structured payload that ``github_unavailable_blocker()``
    returns so upstream callers (e.g. triage) can convert to a BlockerError
    with proper ``fix_actions`` without re-deriving install hints.
    """

    def __init__(self, message: str = "", *, payload: dict | None = None):
        super().__init__(message or (payload or {}).get("what", "GitHub not configured"))
        self.payload = payload or {}


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
    """Check if GitHub access is available — MCP first, gh CLI as fallback."""
    return is_mcp_configured(workspace_root, "github") or have_gh_cli()


def have_gh_cli() -> bool:
    """True if the gh CLI is installed and authenticated."""
    if shutil.which("gh") is None:
        return False
    result = subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True, check=False,
    )
    return result.returncode == 0


def gh_install_hint() -> str:
    """Platform-aware install instructions for gh CLI."""
    system = platform.system()
    if system == "Darwin":
        return "brew install gh && gh auth login"
    if system == "Linux":
        return (
            "Install gh from https://github.com/cli/cli#installation "
            "(`apt install gh` on Debian/Ubuntu, `dnf install gh` on Fedora), "
            "then run `gh auth login`."
        )
    if system == "Windows":
        return "winget install --id GitHub.cli && gh auth login"
    return "See https://github.com/cli/cli#installation, then run `gh auth login`."


def gh_status_hint() -> str:
    """Hint when gh is installed but not authenticated."""
    return "Run `gh auth login` to authenticate."


def github_unavailable_blocker() -> dict:
    """Build a structured no-github-access dict that callers can wrap into BlockerError.

    Returns ``{code, what, fix_actions}`` matching the action contract. Use
    when neither the GitHub MCP server is configured nor the gh CLI is
    available. Tells the user how to fix it on their platform.
    """
    have_gh_binary = shutil.which("gh") is not None
    actions = []
    if have_gh_binary:
        # gh installed but not authed
        actions.append({
            "action": "gh auth login",
            "args": {},
            "safe": True,
            "preview": gh_status_hint(),
        })
    else:
        actions.append({
            "action": "install gh CLI",
            "args": {},
            "safe": True,
            "preview": gh_install_hint(),
        })
    actions.append({
        "action": "configure github MCP",
        "args": {},
        "safe": True,
        "preview": (
            "Add a 'github' entry to .canopy/mcps.json with command/args/env "
            "for an MCP server (e.g. @modelcontextprotocol/server-github)"
        ),
    })
    return {
        "code": "github_not_configured",
        "what": (
            "GitHub access not configured. Either install + auth gh CLI, "
            "or configure the github MCP server in .canopy/mcps.json."
        ),
        "fix_actions": actions,
    }


def _gh(args: list[str], timeout: float = 15.0) -> str:
    """Run gh and return stdout. Raises GitHubNotConfiguredError on failure."""
    try:
        proc = subprocess.run(
            ["gh"] + args, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except FileNotFoundError as e:
        raise GitHubNotConfiguredError(f"gh CLI not on PATH: {e}")
    except subprocess.TimeoutExpired as e:
        raise GitHubNotConfiguredError(f"gh CLI timed out: {' '.join(args)}")
    if proc.returncode != 0:
        raise GitHubNotConfiguredError(
            f"gh {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


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
    """Find an open PR for a branch in a repo. Returns None if not found.

    Tries the configured GitHub MCP server first, then falls back to
    ``gh pr list``. Same dict shape either way: at minimum ``number,
    title, url, state, head_branch``.
    """
    if is_mcp_configured(workspace_root, "github"):
        config = _get_github_config(workspace_root)
        tool_attempts = [
            ("list_pull_requests", {
                "owner": owner, "repo": repo,
                "head": f"{owner}:{branch}", "state": "open",
            }),
            ("search_pull_requests", {
                "owner": owner, "repo": repo,
                "head": branch, "state": "open",
            }),
            ("list_pull_requests", {
                "owner": owner, "repo": repo, "state": "open",
            }),
        ]
        for tool_name, args in tool_attempts:
            try:
                result = call_tool(config, tool_name, args, timeout=15.0, server_name="github")
                parsed = _parse_mcp_result(result)
                if parsed is None:
                    continue
                prs = _extract_prs(parsed, branch)
                if prs:
                    return _normalize_pr(prs[0])
            except McpClientError:
                continue
        # MCP configured but didn't find anything — don't fall back; treat as
        # authoritative "no PR" to avoid double-querying.
        return None

    if have_gh_cli():
        try:
            output = _gh([
                "pr", "list",
                "--repo", f"{owner}/{repo}",
                "--head", branch, "--state", "open",
                "--json", "number,title,url,state,headRefName,body",
                "--limit", "5",
            ])
            data = json.loads(output) if output.strip() else []
            if data:
                pr = data[0]
                return _normalize_pr({
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "html_url": pr.get("url"),
                    "state": (pr.get("state") or "open").lower(),
                    "head": {"ref": pr.get("headRefName")},
                    "body": pr.get("body") or "",
                })
        except (GitHubNotConfiguredError, json.JSONDecodeError):
            pass
        return None

    payload = github_unavailable_blocker()
    raise GitHubNotConfiguredError(payload=payload)


def get_pull_request_by_number(
    workspace_root: Path,
    owner: str,
    repo: str,
    pr_number: int,
) -> dict | None:
    """Fetch a specific PR by number. Returns None if not found.

    MCP first; gh fallback. Same return shape as ``find_pull_request``,
    plus ``base_branch``, ``mergeable``, ``draft``, ``review_decision``.
    """
    if is_mcp_configured(workspace_root, "github"):
        config = _get_github_config(workspace_root)
        for tool_name, args in [
            ("get_pull_request", {"owner": owner, "repo": repo, "pull_number": pr_number}),
            ("pull_request_get", {"owner": owner, "repo": repo, "pull_number": pr_number}),
        ]:
            try:
                result = call_tool(config, tool_name, args, timeout=15.0, server_name="github")
                parsed = _parse_mcp_result(result)
                if parsed:
                    return _normalize_pr(parsed)
            except McpClientError:
                continue
        return None

    if have_gh_cli():
        try:
            output = _gh([
                "pr", "view", str(pr_number),
                "--repo", f"{owner}/{repo}",
                "--json", "number,title,url,state,headRefName,baseRefName,body,reviewDecision,mergeable,isDraft",
            ])
            pr = json.loads(output) if output.strip() else None
            if pr:
                return _normalize_pr({
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "html_url": pr.get("url"),
                    "state": (pr.get("state") or "open").lower(),
                    "head": {"ref": pr.get("headRefName")},
                    "base": {"ref": pr.get("baseRefName")},
                    "body": pr.get("body") or "",
                    "review_decision": pr.get("reviewDecision") or "",
                    "mergeable": pr.get("mergeable") or "",
                    "draft": bool(pr.get("isDraft")),
                })
        except (GitHubNotConfiguredError, json.JSONDecodeError):
            pass
        return None

    payload = github_unavailable_blocker()
    raise GitHubNotConfiguredError(payload=payload)


def list_open_prs(
    workspace_root: Path,
    owner: str,
    repo: str,
    author: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List open PRs in a repo, optionally filtered by author.

    MCP first; gh fallback. Each entry: ``{number, title, url, state,
    head_branch, review_decision, body}``.
    """
    if is_mcp_configured(workspace_root, "github"):
        config = _get_github_config(workspace_root)
        args = {"owner": owner, "repo": repo, "state": "open"}
        if author:
            args["author"] = author
        for tool_name in ("list_pull_requests", "search_pull_requests"):
            try:
                result = call_tool(config, tool_name, args, timeout=15.0, server_name="github")
                parsed = _parse_mcp_result(result)
                if parsed is None:
                    continue
                prs = parsed if isinstance(parsed, list) else (
                    parsed.get("pull_requests") or parsed.get("items")
                    or parsed.get("data") or []
                )
                if isinstance(prs, list):
                    return [_normalize_pr(p) for p in prs[:limit]]
            except McpClientError:
                continue
        return []

    if have_gh_cli():
        try:
            cli_args = [
                "pr", "list", "--repo", f"{owner}/{repo}",
                "--state", "open", "--limit", str(limit),
                "--json", "number,title,url,state,headRefName,body,reviewDecision",
            ]
            if author:
                cli_args.extend(["--author", author])
            output = _gh(cli_args)
            data = json.loads(output) if output.strip() else []
            return [
                _normalize_pr({
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "html_url": pr.get("url"),
                    "state": (pr.get("state") or "open").lower(),
                    "head": {"ref": pr.get("headRefName")},
                    "body": pr.get("body") or "",
                    "review_decision": pr.get("reviewDecision") or "",
                })
                for pr in data
            ]
        except (GitHubNotConfiguredError, json.JSONDecodeError):
            return []

    payload = github_unavailable_blocker()
    raise GitHubNotConfiguredError(payload=payload)


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
    """Normalize PR data into a consistent shape across MCP / gh."""
    head = data.get("head") or {}
    head_branch = head.get("ref", "") if isinstance(head, dict) else ""
    if not head_branch:
        head_branch = data.get("head_branch") or ""
    base = data.get("base") or {}
    base_branch = base.get("ref", "") if isinstance(base, dict) else ""
    if not base_branch:
        base_branch = data.get("base_branch") or ""
    return {
        "number": data.get("number") or data.get("id"),
        "title": data.get("title") or "",
        "url": data.get("html_url") or data.get("url") or "",
        "state": data.get("state") or "open",
        "head_branch": head_branch,
        "base_branch": base_branch,
        "body": data.get("body") or "",
        "review_decision": data.get("review_decision") or data.get("reviewDecision") or "",
        "mergeable": data.get("mergeable") or "",
        "draft": bool(data.get("draft") or data.get("isDraft")),
    }


def get_review_comments(
    workspace_root: Path,
    owner: str,
    repo: str,
    pr_number: int,
) -> tuple[list[dict], int]:
    """Fetch review comments for a PR. MCP first; gh CLI fallback.

    Returns ``(comments, resolved_count)``: comments are normalized with
    fields ``path, line, body, author, author_type, state, created_at,
    url, in_reply_to_id``. ``resolved_count`` is the number of threads
    excluded because GitHub flagged them resolved.

    Bot threads are kept (the temporal classifier downstream handles
    staleness). If neither path is available, returns ``([], 0)``.
    """
    if is_mcp_configured(workspace_root, "github"):
        config = _get_github_config(workspace_root)
        for tool_name, args in [
            ("get_pull_request_comments", {"owner": owner, "repo": repo, "pull_number": pr_number}),
            ("list_review_comments", {"owner": owner, "repo": repo, "pull_number": pr_number}),
            ("get_pull_request_reviews", {"owner": owner, "repo": repo, "pull_number": pr_number}),
        ]:
            try:
                result = call_tool(config, tool_name, args, timeout=15.0, server_name="github")
                parsed = _parse_mcp_result(result)
                if parsed is not None:
                    return _normalize_comments(parsed)
            except McpClientError:
                continue
        return [], 0

    if have_gh_cli():
        try:
            output = _gh([
                "api", f"repos/{owner}/{repo}/pulls/{pr_number}/comments",
                "--paginate",
            ])
            data = json.loads(output) if output.strip() else []
            return _normalize_comments(data)
        except (GitHubNotConfiguredError, json.JSONDecodeError):
            return [], 0

    return [], 0


def _normalize_comments(data: Any) -> tuple[list[dict], int]:
    """Normalize review comments from various MCP response shapes.

    Drops threads explicitly marked resolved (isResolved/state==RESOLVED).
    Bot comments are NOT filtered: a claude[bot] thread may carry the
    only actionable feedback. The temporal classifier downstream handles
    staleness regardless of author.

    Returns ``(comments, resolved_count)`` so callers can report how many
    were excluded.
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
        return [], 0

    normalized = []
    resolved_count = 0
    for c in comments:
        if c.get("resolved", False) or c.get("state") == "RESOLVED":
            resolved_count += 1
            continue

        author = c.get("user", {})
        if isinstance(author, dict):
            author_login = author.get("login", "")
            author_type = author.get("type", "")
        else:
            author_login = str(author) if author else ""
            author_type = ""

        normalized.append({
            "path": c.get("path") or c.get("file") or "",
            "line": c.get("line") or c.get("original_line") or c.get("position") or 0,
            "body": c.get("body") or "",
            "author": author_login or c.get("author", ""),
            "author_type": author_type,
            "state": c.get("state") or "",
            "created_at": c.get("created_at") or c.get("createdAt") or "",
            "url": c.get("html_url") or c.get("url") or "",
            "in_reply_to_id": c.get("in_reply_to_id"),
        })

    return normalized, resolved_count
