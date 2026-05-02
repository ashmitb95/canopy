"""Tests for canopy.providers.github_issues — GitHubIssuesProvider.

The ``gh`` CLI is mocked at the ``_gh_json`` helper boundary; we exercise
parsing + alias resolution + canonical state mapping.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from canopy.integrations.github import GitHubNotConfiguredError
from canopy.providers.github_issues import (
    GitHubIssuesProvider,
    _to_issue,
    _priority_from_labels,
)
from canopy.providers.types import (
    IssueNotFoundError,
    IssueProviderError,
    ProviderNotConfigured,
)


def _provider(tmp_path: Path, **opts) -> GitHubIssuesProvider:
    options = {"repo": "owner/repo", **opts}
    return GitHubIssuesProvider(options, workspace_root=tmp_path)


# ── Construction ─────────────────────────────────────────────────────────


def test_init_requires_repo(tmp_path):
    with pytest.raises(ProviderNotConfigured):
        GitHubIssuesProvider({}, workspace_root=tmp_path)


def test_init_accepts_labels_filter(tmp_path):
    p = _provider(tmp_path, labels_filter=["bug", "p0"])
    assert p.labels_filter == ["bug", "p0"]


# ── _parse_alias ─────────────────────────────────────────────────────────


def test_parse_alias_hash_form(tmp_path):
    p = _provider(tmp_path)
    assert p._parse_alias("#142") == ("owner/repo", 142)


def test_parse_alias_bare_number(tmp_path):
    p = _provider(tmp_path)
    assert p._parse_alias("142") == ("owner/repo", 142)


def test_parse_alias_explicit_repo(tmp_path):
    p = _provider(tmp_path)
    assert p._parse_alias("other/repo#7") == ("other/repo", 7)


def test_parse_alias_garbage_raises(tmp_path):
    p = _provider(tmp_path)
    with pytest.raises(IssueNotFoundError):
        p._parse_alias("not-an-issue")


# ── get_issue ────────────────────────────────────────────────────────────


def test_get_issue_happy_path(tmp_path):
    p = _provider(tmp_path)
    raw = {
        "number": 142, "title": "bug", "state": "open", "body": "details",
        "html_url": "https://github.com/owner/repo/issues/142",
        "labels": [{"name": "bug"}, {"name": "p1"}],
        "assignees": [{"login": "alice"}],
    }
    with patch("canopy.providers.github_issues._gh_json", return_value=raw):
        issue = p.get_issue("#142")
    assert issue.identifier == "#142"
    assert issue.title == "bug"
    assert issue.state == "in_progress"   # open → in_progress
    assert issue.assignee == "alice"
    assert issue.labels == ("bug", "p1")
    assert issue.priority == 2
    assert issue.url == "https://github.com/owner/repo/issues/142"


def test_get_issue_closed_completed_maps_to_done(tmp_path):
    p = _provider(tmp_path)
    raw = {"number": 1, "title": "x", "state": "closed", "state_reason": "completed"}
    with patch("canopy.providers.github_issues._gh_json", return_value=raw):
        issue = p.get_issue("1")
    assert issue.state == "done"


def test_get_issue_closed_not_planned_maps_to_cancelled(tmp_path):
    p = _provider(tmp_path)
    raw = {"number": 1, "title": "x", "state": "closed", "state_reason": "not_planned"}
    with patch("canopy.providers.github_issues._gh_json", return_value=raw):
        issue = p.get_issue("1")
    assert issue.state == "cancelled"


def test_get_issue_pull_request_filtered_out(tmp_path):
    """A response with pull_request key is a PR, not an issue."""
    p = _provider(tmp_path)
    raw = {"number": 1, "title": "x", "state": "open", "pull_request": {"url": "..."}}
    with patch("canopy.providers.github_issues._gh_json", return_value=raw):
        with pytest.raises(IssueNotFoundError):
            p.get_issue("1")


def test_get_issue_propagates_gh_not_configured_as_provider_not_configured(tmp_path):
    p = _provider(tmp_path)
    with patch("canopy.providers.github_issues._gh_json",
               side_effect=GitHubNotConfiguredError("no gh")):
        with pytest.raises(ProviderNotConfigured):
            p.get_issue("1")


def test_get_issue_empty_response_raises_not_found(tmp_path):
    p = _provider(tmp_path)
    with patch("canopy.providers.github_issues._gh_json", return_value=None):
        with pytest.raises(IssueNotFoundError):
            p.get_issue("1")


# ── list_my_issues ───────────────────────────────────────────────────────


def test_list_my_issues_uses_gh_issue_list_with_flags(tmp_path):
    """F-10: must use ``gh issue list`` with --repo/--state/--assignee/--label
    flags. ``gh search issues`` treats positional arg as search text and
    chokes on qualifiers like ``repo:owner/repo``."""
    p = _provider(tmp_path, labels_filter=["bug", "p0"])
    captured: dict = {}

    def fake_gh(args):
        captured["args"] = args
        return [
            {"number": 1, "title": "x", "state": "open"},
            {"number": 2, "title": "y", "state": "open"},
        ]

    with patch("canopy.providers.github_issues._gh_json", side_effect=fake_gh):
        issues = p.list_my_issues()
    assert len(issues) == 2
    args = captured["args"]
    # First two args are the subcommand. NOT "search issues".
    assert args[:2] == ["issue", "list"]
    # Qualifiers are CLI flags, not embedded in a search query.
    assert "--repo" in args and args[args.index("--repo") + 1] == "owner/repo"
    assert "--state" in args and args[args.index("--state") + 1] == "open"
    assert "--assignee" in args and args[args.index("--assignee") + 1] == "@me"
    # Both labels passed as separate --label flags
    label_indices = [i for i, a in enumerate(args) if a == "--label"]
    assert len(label_indices) == 2
    assert {args[i + 1] for i in label_indices} == {"bug", "p0"}


def test_list_my_issues_returns_empty_when_no_results(tmp_path):
    p = _provider(tmp_path)
    with patch("canopy.providers.github_issues._gh_json", return_value=[]):
        assert p.list_my_issues() == []


def test_list_my_issues_propagates_gh_not_configured(tmp_path):
    p = _provider(tmp_path)
    with patch("canopy.providers.github_issues._gh_json",
               side_effect=GitHubNotConfiguredError("no gh")):
        with pytest.raises(ProviderNotConfigured):
            p.list_my_issues()


# ── format_branch_name ───────────────────────────────────────────────────


def test_format_branch_name_plain(tmp_path):
    p = _provider(tmp_path)
    assert p.format_branch_name("#42") == "gh-42"


def test_format_branch_name_with_title(tmp_path):
    p = _provider(tmp_path)
    assert p.format_branch_name("#42", title="Add OAuth login") == "gh-42-add-oauth-login"


def test_format_branch_name_custom_overrides(tmp_path):
    p = _provider(tmp_path)
    assert p.format_branch_name("#42", title="x", custom_name="ash/branch") == "ash/branch"


def test_format_branch_name_unparseable_falls_back(tmp_path):
    p = _provider(tmp_path)
    out = p.format_branch_name("garbage", title="Add login")
    assert out == "gh-garbage-add-login"


# ── update_issue_state — NotImplemented in v1 ────────────────────────────


def test_update_issue_state_not_implemented(tmp_path):
    p = _provider(tmp_path)
    with pytest.raises(NotImplementedError):
        p.update_issue_state("#1", "done")


# ── _to_issue / helpers ──────────────────────────────────────────────────


def test_priority_from_labels_first_match_wins():
    assert _priority_from_labels(("bug", "p0")) == 1
    assert _priority_from_labels(("priority/high",)) == 2
    assert _priority_from_labels(("misc",)) is None


def test_to_issue_uses_search_repository_field():
    raw = {
        "number": 7, "title": "x", "state": "open",
        "repository": {"nameWithOwner": "search/repo"},
    }
    issue = _to_issue(raw, default_repo="default/repo")
    # URL is derived from repository.nameWithOwner when html_url missing
    assert "search/repo" in issue.url


def test_to_issue_falls_back_to_default_repo_for_url():
    raw = {"number": 7, "title": "x", "state": "open"}
    issue = _to_issue(raw, default_repo="default/repo")
    assert issue.url == "https://github.com/default/repo/issues/7"


# ── parse_alias (M5+ Provider Protocol method — F-7) ────────────────────


def test_parse_alias_bare_number(tmp_path):
    p = _provider(tmp_path)
    assert p.parse_alias("142") == "142"


def test_parse_alias_hash_number(tmp_path):
    p = _provider(tmp_path)
    assert p.parse_alias("#142") == "142"


def test_parse_alias_owner_repo_form(tmp_path):
    p = _provider(tmp_path)
    assert p.parse_alias("owner/repo#142") == "owner/repo#142"


def test_parse_alias_full_url(tmp_path):
    p = _provider(tmp_path)
    out = p.parse_alias("https://github.com/owner/repo/issues/142")
    assert out == "owner/repo#142"


def test_parse_alias_url_with_trailing_slash(tmp_path):
    p = _provider(tmp_path)
    assert p.parse_alias("https://github.com/o/r/issues/9/") == "o/r#9"


def test_parse_alias_returns_none_for_unrecognized(tmp_path):
    p = _provider(tmp_path)
    assert p.parse_alias("auth-flow") is None
    assert p.parse_alias("SIN-412") is None
    assert p.parse_alias("not an issue") is None


def test_parse_alias_handles_whitespace(tmp_path):
    p = _provider(tmp_path)
    assert p.parse_alias("  142  ") == "142"
