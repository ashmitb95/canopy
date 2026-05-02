"""Canonical types for the issue-provider contract.

The :class:`Issue` dataclass is what every action that consumes issue data
operates on, regardless of which backend produced it. Providers map their
internal shapes into ``Issue`` instances.

See ``docs/architecture/providers.md`` §2 for the design.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# Canonical state vocabulary. Every provider maps its internal state names
# into one of these. Agents pattern-match on these strings; downstream
# rendering can show the raw provider name from ``Issue.raw`` when needed.
CANONICAL_STATES = ("todo", "in_progress", "done", "cancelled")


@dataclass(frozen=True)
class Issue:
    """An issue from any tracker, normalized to the canopy canonical shape.

    Every provider returns this. ``raw`` is an escape hatch holding the
    original API response so adapter layers (e.g. ``actions/reads.py``)
    can pass through provider-specific fields for backward compatibility
    without expanding the canonical type.
    """
    id: str                                       # provider-internal id (Linear UUID, GH issue number, JIRA key)
    identifier: str                               # human-readable: "SIN-7", "#142", "PROJ-123"
    title: str
    description: str | None = None
    state: str = "todo"                           # one of CANONICAL_STATES
    url: str = ""
    assignee: str | None = None
    labels: tuple[str, ...] = ()
    priority: int | None = None                  # 1=urgent, 2=high, 3=medium, 4=low
    raw: dict[str, Any] | None = None             # provider-specific original payload

    def to_dict(self) -> dict[str, Any]:
        """Render to a JSON-friendly dict. Tuples become lists."""
        return {
            "id": self.id,
            "identifier": self.identifier,
            "title": self.title,
            "description": self.description,
            "state": self.state,
            "url": self.url,
            "assignee": self.assignee,
            "labels": list(self.labels),
            "priority": self.priority,
            "raw": self.raw,
        }


@runtime_checkable
class IssueProvider(Protocol):
    """Contract every issue provider must implement.

    Concrete providers live under ``canopy.providers.<name>``. The
    registry in ``canopy.providers.__init__`` dispatches based on the
    workspace's ``[issue_provider] name = "..."`` config.
    """

    def get_issue(self, alias: str) -> Issue:
        """Resolve a provider-native alias to an ``Issue``.

        Alias formats are provider-specific:
          - Linear: ``"SIN-7"``
          - GitHub Issues: ``"#142"`` or ``"owner/repo#142"``
          - JIRA: ``"PROJ-123"``

        Raises:
            IssueNotFoundError: alias didn't resolve to an existing issue.
            ProviderNotConfigured: backend credentials missing or wrong.
            IssueProviderError: any other backend / network failure.
        """
        ...

    def list_my_issues(self, limit: int = 50) -> list[Issue]:
        """Return the current user's open issues, ordered by recency or
        priority (provider's choice). Empty list is valid.

        Raises:
            ProviderNotConfigured: backend credentials missing or wrong.
            IssueProviderError: backend / network failure.
        """
        ...

    def format_branch_name(
        self,
        issue_id: str,
        title: str | None = None,
        custom_name: str | None = None,
    ) -> str:
        """Provider-specific branch slug rules.

        ``custom_name`` overrides any default slugging when the user wants
        a non-derived branch name.
        """
        ...

    def update_issue_state(self, alias: str, new_state: str) -> None:
        """Optional. Lifecycle automation (e.g. flip to ``in_progress``
        on ``canopy switch <issue>``). v1 implementations may raise
        ``NotImplementedError`` — this slot exists so future plans can
        wire it without changing the protocol.
        """
        ...


# Provider exceptions. These are the only exceptions providers should
# raise; the action layer catches them and converts to ``BlockerError``
# for the CLI / MCP surfaces.

class IssueProviderError(Exception):
    """Base for all provider-raised errors."""


class ProviderNotConfigured(IssueProviderError):
    """Backend isn't configured for this workspace (missing creds, wrong
    canopy.toml block, unknown provider name in registry)."""


class IssueNotFoundError(IssueProviderError):
    """Alias didn't resolve to a real issue."""
