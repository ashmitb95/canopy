"""GitHub Issues backend for the issue-provider contract.

New in M5. Uses the existing ``gh`` CLI helper from
``integrations/github.py`` (no MCP server required); falls back to
``BlockerError(code='github_not_configured')`` semantics if ``gh`` isn't
available.

Workspace config under ``[issue_provider.github_issues]`` accepts:

  - ``repo``: required. ``"owner/repo"`` of the GitHub repository hosting
    the issues for this workspace.
  - ``labels_filter``: optional list of label names. When set, restricts
    ``list_my_issues`` to issues bearing at least one of these labels.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .types import (
    Issue,
    IssueNotFoundError,
    IssueProviderError,
    ProviderNotConfigured,
)
from ..integrations.github import GitHubNotConfiguredError, _gh


# GitHub state names → canonical canopy states. GH only has open / closed,
# but issues with the ``state_reason`` of "completed" vs "not_planned"
# get split into done / cancelled.
_GH_STATE_MAP = {
    "open": "in_progress",
    "closed": "done",
}

# Labels we recognize for priority hinting. Order matters — first match
# wins. Both "p0/p1/..." short forms and "priority/urgent" GH-Issues
# convention are supported.
_PRIORITY_LABEL_MAP = {
    "priority/urgent": 1,
    "priority/critical": 1,
    "priority/high": 2,
    "priority/medium": 3,
    "priority/low": 4,
    "p0": 1,
    "p1": 2,
    "p2": 3,
    "p3": 4,
}


class GitHubIssuesProvider:
    """GitHub Issues issue provider.

    Backed by the ``gh`` CLI (the same helper canopy uses for PR data).
    Requires a configured ``repo`` in canopy.toml; aliases get parsed as
    issue numbers (``#142``, ``142``, or ``owner/repo#142``).
    """

    def __init__(self, options: dict[str, Any] | None = None, *, workspace_root: Path | None = None):
        self._options = options or {}
        self._workspace_root = workspace_root  # currently unused; reserved for future config files
        repo = self._options.get("repo")
        if not repo:
            raise ProviderNotConfigured(
                "GitHubIssuesProvider requires 'repo' in [issue_provider.github_issues]. "
                "Example: repo = \"owner/repo\"",
            )
        self.repo: str = repo
        self.labels_filter: list[str] = list(self._options.get("labels_filter") or [])

    # ── Protocol methods ────────────────────────────────────────────────

    def get_issue(self, alias: str) -> Issue:
        """Fetch a GitHub issue by alias.

        Aliases:
          - ``"#142"`` — issue 142 in the configured repo
          - ``"142"`` — same
          - ``"owner/repo#142"`` — explicit repo override (must match self.repo for v1; cross-repo lookup is a future)
        """
        target_repo, issue_num = self._parse_alias(alias)
        try:
            raw = _gh_json(["api", f"repos/{target_repo}/issues/{issue_num}"])
        except GitHubNotConfiguredError as e:
            raise ProviderNotConfigured(str(e)) from e

        if not isinstance(raw, dict) or "number" not in raw:
            raise IssueNotFoundError(f"GitHub issue '{alias}' not found in {target_repo}")
        # GH returns PRs from /issues/<n> too; filter them out — canopy's
        # PR handling lives elsewhere.
        if raw.get("pull_request"):
            raise IssueNotFoundError(
                f"'{alias}' is a pull request, not an issue. Use canopy review for PRs.",
            )
        return _to_issue(raw, default_repo=target_repo)

    def list_my_issues(self, limit: int = 50) -> list[Issue]:
        """Return open GitHub issues assigned to the current user, scoped
        to the configured repo. Honors ``labels_filter`` when set.

        Uses ``gh issue list`` (not ``gh search issues``) — the search form
        treats positional args as search *text*, so passing qualifiers like
        ``repo:...`` and ``is:open`` quotes them as a single text token and
        the API returns "Invalid search query." See test-findings F-10.
        """
        args = [
            "issue", "list",
            "--repo", self.repo,
            "--state", "open",
            "--assignee", "@me",
            "--limit", str(limit),
            "--json", "number,title,state,body,url,assignees,labels",
        ]
        if self.labels_filter:
            for label in self.labels_filter:
                args.extend(["--label", label])

        try:
            raw_list = _gh_json(args)
        except GitHubNotConfiguredError as e:
            raise ProviderNotConfigured(str(e)) from e

        if not isinstance(raw_list, list):
            return []
        return [_to_issue(r, default_repo=self.repo) for r in raw_list if isinstance(r, dict)]

    def format_branch_name(
        self,
        issue_id: str,
        title: str | None = None,
        custom_name: str | None = None,
    ) -> str:
        """``"gh-<n>-<slug>"`` or ``"gh-<n>"`` if title missing."""
        if custom_name:
            return custom_name
        try:
            _, n = self._parse_alias(issue_id)
        except IssueProviderError:
            # Not a parseable issue alias — fall back to lowercased id.
            n_str = issue_id.lstrip("#").lower()
            if not title:
                return f"gh-{n_str}"
            return f"gh-{n_str}-{_slugify(title)}"
        if not title:
            return f"gh-{n}"
        return f"gh-{n}-{_slugify(title)}"

    def update_issue_state(self, alias: str, new_state: str) -> None:
        """Lifecycle automation reserved for a future plan."""
        raise NotImplementedError(
            "GitHubIssuesProvider.update_issue_state is not implemented in v1.",
        )

    def parse_alias(self, alias: str) -> str | None:
        """Recognize GitHub-shaped aliases. See ``_GH_ALIAS`` shapes.

        Returns the canonical alias string (which ``get_issue`` can
        consume) when recognized, ``None`` otherwise.
        """
        s = alias.strip()
        # Full issue URL — return the issue id (provider knows its repo).
        url_match = re.match(
            r"^https?://github\.com/([\w\-.]+)/([\w\-.]+)/issues/(\d+)/?$", s,
        )
        if url_match:
            owner, repo, num = url_match.group(1), url_match.group(2), url_match.group(3)
            return f"{owner}/{repo}#{num}"
        # owner/repo#N
        if re.match(r"^[\w\-.]+/[\w\-.]+#\d+$", s):
            return s
        # #N or bare N
        if re.match(r"^#?\d+$", s):
            return s.lstrip("#")
        return None

    # ── Internal ────────────────────────────────────────────────────────

    def _parse_alias(self, alias: str) -> tuple[str, int]:
        """Parse an alias into (repo, issue_number).

        Accepts:
          - ``"#142"`` → (self.repo, 142)
          - ``"142"`` → (self.repo, 142)
          - ``"owner/repo#142"`` → ("owner/repo", 142)
        """
        # owner/repo#142
        m = re.match(r"^([\w\-.]+/[\w\-.]+)#(\d+)$", alias)
        if m:
            return m.group(1), int(m.group(2))
        # #142 or 142
        m = re.match(r"^#?(\d+)$", alias)
        if m:
            return self.repo, int(m.group(1))
        raise IssueNotFoundError(
            f"Can't parse GitHub issue alias '{alias}'. Use '#142', '142', or 'owner/repo#142'.",
        )


# ── Module-level helpers ────────────────────────────────────────────────


def _gh_json(args: list[str]) -> Any:
    """``_gh`` wrapper that JSON-decodes stdout. Empty stdout → ``None``.

    Lifted to module level so tests can monkeypatch it without touching
    the underlying subprocess machinery in ``integrations/github.py``.
    """
    out = _gh(args)
    if not out.strip():
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise IssueProviderError(f"gh returned non-JSON output: {e}") from e


def _to_issue(raw: dict, *, default_repo: str) -> Issue:
    """Map a GitHub API issue payload to a canonical ``Issue``.

    Used by both ``get_issue`` (which fetches a single issue) and
    ``list_my_issues`` (which gets a list from the search endpoint).
    Search results have a slightly different shape (top-level fields are
    similar but ``html_url`` may be missing; ``url`` is the API URL).
    """
    state_raw = raw.get("state") or ""
    state_reason = raw.get("state_reason") or ""
    canonical_state = _GH_STATE_MAP.get(state_raw.lower(), "todo")
    if canonical_state == "done" and state_reason == "not_planned":
        canonical_state = "cancelled"

    labels_raw = raw.get("labels") or []
    labels: tuple[str, ...] = tuple(
        l.get("name") if isinstance(l, dict) else str(l)
        for l in labels_raw
        if (isinstance(l, dict) and l.get("name")) or isinstance(l, str)
    )

    assignees = raw.get("assignees") or []
    assignee = (
        assignees[0].get("login")
        if assignees and isinstance(assignees[0], dict)
        else (raw.get("assignee", {}) or {}).get("login")
    )

    # Search results put repo info in raw["repository"]["nameWithOwner"];
    # single-issue responses derive from URL.
    repository = raw.get("repository") or {}
    if isinstance(repository, dict):
        repo_name = repository.get("nameWithOwner") or repository.get("full_name") or default_repo
    else:
        repo_name = default_repo

    number = raw.get("number")
    return Issue(
        id=str(number),
        identifier=f"#{number}",
        title=raw.get("title") or "",
        description=raw.get("body"),
        state=canonical_state,
        url=raw.get("html_url") or raw.get("url") or _make_html_url(repo_name, number),
        assignee=assignee,
        labels=labels,
        priority=_priority_from_labels(labels),
        raw=raw,
    )


def _make_html_url(repo_name: str, number: int | None) -> str:
    if not number:
        return ""
    return f"https://github.com/{repo_name}/issues/{number}"


def _priority_from_labels(labels: tuple[str, ...]) -> int | None:
    for l in labels:
        p = _PRIORITY_LABEL_MAP.get(l.lower())
        if p is not None:
            return p
    return None


def _slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s.strip()).lower()
    return s[:50].rstrip("-")
