"""Canonical Issue dataclass + IssueProvider Protocol contract."""
from __future__ import annotations

import pytest

from canopy.providers.types import (
    CANONICAL_STATES,
    Issue,
    IssueNotFoundError,
    IssueProvider,
    IssueProviderError,
    ProviderNotConfigured,
)


def test_issue_defaults():
    issue = Issue(id="1", identifier="#1", title="t")
    assert issue.state == "todo"
    assert issue.url == ""
    assert issue.assignee is None
    assert issue.labels == ()
    assert issue.priority is None
    assert issue.raw is None


def test_issue_to_dict_round_trips_lists():
    issue = Issue(
        id="1", identifier="#1", title="t",
        labels=("bug", "p0"),
    )
    d = issue.to_dict()
    assert d["labels"] == ["bug", "p0"]
    assert isinstance(d["labels"], list)


def test_issue_is_frozen():
    issue = Issue(id="1", identifier="#1", title="t")
    with pytest.raises(Exception):
        issue.title = "mutated"  # type: ignore[misc]


def test_canonical_states_contract():
    assert CANONICAL_STATES == ("todo", "in_progress", "done", "cancelled")


def test_exception_hierarchy():
    assert issubclass(ProviderNotConfigured, IssueProviderError)
    assert issubclass(IssueNotFoundError, IssueProviderError)


def test_protocol_runtime_check_minimal_impl():
    """Anything with the four methods passes isinstance(obj, IssueProvider)."""

    class Stub:
        def get_issue(self, alias):  # noqa: ARG002
            return Issue(id="1", identifier="#1", title="t")

        def list_my_issues(self, limit=50):  # noqa: ARG002
            return []

        def format_branch_name(self, issue_id, title=None, custom_name=None):  # noqa: ARG002
            return ""

        def update_issue_state(self, alias, new_state):  # noqa: ARG002
            return None

    assert isinstance(Stub(), IssueProvider)


def test_protocol_runtime_check_rejects_partial():
    class Partial:
        def get_issue(self, alias):  # noqa: ARG002
            return None

    assert not isinstance(Partial(), IssueProvider)
