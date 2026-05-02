"""Tests for providers/__init__.py — registry + get_issue_provider."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from canopy.providers import (
    _clear_cache,
    available_providers,
    get_issue_provider,
    register_provider,
)
from canopy.providers.types import Issue, IssueProvider, ProviderNotConfigured
from canopy.workspace.config import (
    IssueProviderConfig,
    RepoConfig,
    WorkspaceConfig,
)
from canopy.workspace.workspace import Workspace


def _ws(tmp_path: Path, provider: IssueProviderConfig) -> Workspace:
    config = WorkspaceConfig(
        name="test",
        repos=[RepoConfig(name="r", path="./r", role="x", lang="x")],
        root=tmp_path,
        issue_provider=provider,
    )
    return Workspace(config)


@pytest.fixture(autouse=True)
def clear_cache():
    _clear_cache()
    yield
    _clear_cache()


def test_available_providers_includes_bundled():
    names = available_providers()
    assert "linear" in names
    assert "github_issues" in names


def test_get_issue_provider_unknown_name_raises_with_available_list(tmp_path):
    ws = _ws(tmp_path, IssueProviderConfig(name="nonsense"))
    with pytest.raises(ProviderNotConfigured) as exc:
        get_issue_provider(ws)
    msg = str(exc.value)
    assert "nonsense" in msg
    assert "linear" in msg


def test_get_issue_provider_caches_per_workspace(tmp_path):
    """Two calls on the same workspace return the same instance."""
    # Avoid touching MCP/network: register a noop provider.
    register_provider("test_noop", "tests.test_providers_registry._NoopProvider")
    try:
        ws = _ws(tmp_path, IssueProviderConfig(name="test_noop"))
        a = get_issue_provider(ws)
        b = get_issue_provider(ws)
        assert a is b
    finally:
        _clear_cache()


def test_get_issue_provider_returns_protocol_compliant(tmp_path):
    register_provider("test_noop", "tests.test_providers_registry._NoopProvider")
    try:
        ws = _ws(tmp_path, IssueProviderConfig(name="test_noop"))
        provider = get_issue_provider(ws)
        assert isinstance(provider, IssueProvider)
    finally:
        _clear_cache()


def test_register_provider_adds_to_registry():
    register_provider("test_x", "tests.test_providers_registry._NoopProvider")
    assert "test_x" in available_providers()


def test_get_issue_provider_passes_options_and_root(tmp_path):
    register_provider("test_capture", "tests.test_providers_registry._CapturingProvider")
    try:
        opts = {"foo": "bar"}
        ws = _ws(tmp_path, IssueProviderConfig(name="test_capture", options=opts))
        instance = get_issue_provider(ws)
        assert instance.captured_options == opts
        assert instance.captured_root == tmp_path
    finally:
        _clear_cache()


# ── helpers used as importable provider classes ──────────────────────────


class _NoopProvider:
    def __init__(self, options=None, *, workspace_root=None):  # noqa: ARG002
        self._options = options or {}

    def get_issue(self, alias):
        return Issue(id="1", identifier=alias, title="t")

    def list_my_issues(self, limit=50):
        return []

    def format_branch_name(self, issue_id, title=None, custom_name=None):
        return issue_id

    def update_issue_state(self, alias, new_state):
        raise NotImplementedError


class _CapturingProvider(_NoopProvider):
    def __init__(self, options=None, *, workspace_root=None):
        super().__init__(options, workspace_root=workspace_root)
        self.captured_options = options
        self.captured_root = workspace_root
