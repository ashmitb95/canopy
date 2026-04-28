"""Tests for the worktree_create MCP tool — specifically the linear_lookup
status field added in B2 (R6) so the agent sees Linear-fetch failures
explicitly instead of getting a lane with empty title/url and no signal.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from canopy.integrations.linear import (
    LinearIssueNotFoundError, LinearNotConfiguredError,
)
from canopy.mcp.client import McpClientError


def _setup_workspace(tmp_path) -> Path:
    """Build a minimal canopy workspace with two real git repos."""
    import subprocess
    for name in ("repo-a", "repo-b"):
        repo = tmp_path / name
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@x"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
        (repo / "README.md").write_text("x")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

    (tmp_path / "canopy.toml").write_text(
        '[workspace]\nname = "t"\n\n'
        '[[repos]]\nname = "repo-a"\npath = "./repo-a"\n\n'
        '[[repos]]\nname = "repo-b"\npath = "./repo-b"\n'
    )
    (tmp_path / ".canopy").mkdir()
    return tmp_path


def _call_worktree_create(workspace_root, **kwargs):
    """Invoke the worktree_create MCP tool function directly with
    CANOPY_ROOT set, so _get_workspace() resolves to our temp workspace."""
    # Re-import to pick up patched env
    os.environ["CANOPY_ROOT"] = str(workspace_root)
    from importlib import reload
    import canopy.mcp.server as srv
    reload(srv)
    return srv.worktree_create(**kwargs)


class TestLinearLookupSignal:
    """worktree_create.linear_lookup tells the agent whether the Linear
    fetch succeeded, was skipped, or failed — instead of silently returning
    a lane with empty title/url."""

    def test_no_issue_arg_omits_linear_lookup(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        result = _call_worktree_create(ws, name="no-issue")
        assert "linear_lookup" not in result

    def test_no_linear_mcp_returns_not_configured(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        # No mcps.json → not configured
        result = _call_worktree_create(ws, name="lane-a", issue="SIN-1")
        assert result["linear_lookup"]["status"] == "not_configured"
        assert result["linear_issue"] == "SIN-1"
        assert result.get("linear_title", "") == ""

    def test_linear_fetch_success_returns_ok(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        (ws / ".canopy" / "mcps.json").write_text(json.dumps(
            {"linear": {"command": "echo"}},
        ))

        with patch(
            "canopy.integrations.linear.get_issue",
            return_value={
                "identifier": "SIN-2", "title": "Real title",
                "url": "https://linear.app/x/SIN-2", "state": "Todo",
                "description": "", "raw": {},
            },
        ):
            result = _call_worktree_create(ws, name="lane-ok", issue="SIN-2")

        assert result["linear_lookup"] == {"status": "ok"}
        assert result["linear_title"] == "Real title"
        assert result["linear_url"] == "https://linear.app/x/SIN-2"

    def test_linear_fetch_returns_empty_treated_as_failed(self, tmp_path):
        """Pre-B1, a wrong-arg-shape Linear call returned an empty issue
        and the lane silently had title='' / url=''. B2 catches this:
        treat empty title+url as a lookup failure."""
        ws = _setup_workspace(tmp_path)
        (ws / ".canopy" / "mcps.json").write_text(json.dumps(
            {"linear": {"command": "echo"}},
        ))

        with patch(
            "canopy.integrations.linear.get_issue",
            return_value={
                "identifier": "SIN-3", "title": "", "url": "",
                "state": "", "description": "", "raw": {},
            },
        ):
            result = _call_worktree_create(ws, name="lane-empty", issue="SIN-3")

        assert result["linear_lookup"]["status"] == "failed"
        assert "schema mismatch" in result["linear_lookup"]["reason"]
        assert result["linear_issue"] == "SIN-3"
        assert result.get("linear_title", "") == ""

    def test_linear_issue_not_found_returns_failed(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        (ws / ".canopy" / "mcps.json").write_text(json.dumps(
            {"linear": {"command": "echo"}},
        ))

        with patch(
            "canopy.integrations.linear.get_issue",
            side_effect=LinearIssueNotFoundError("no such issue"),
        ):
            result = _call_worktree_create(ws, name="lane-404", issue="SIN-999")

        assert result["linear_lookup"]["status"] == "failed"
        assert "not found" in result["linear_lookup"]["reason"]
        assert result["linear_issue"] == "SIN-999"

    def test_mcp_call_error_returns_failed(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        (ws / ".canopy" / "mcps.json").write_text(json.dumps(
            {"linear": {"command": "echo"}},
        ))

        with patch(
            "canopy.integrations.linear.get_issue",
            side_effect=McpClientError("transport blew up"),
        ):
            result = _call_worktree_create(ws, name="lane-err", issue="SIN-5")

        assert result["linear_lookup"]["status"] == "failed"
        assert "transport blew up" in result["linear_lookup"]["reason"]
        # Lane was still created with the bare issue ID — fetch failure
        # doesn't fail the worktree creation
        assert result["linear_issue"] == "SIN-5"
        assert "worktree_paths" in result
