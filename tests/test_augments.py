"""Tests for canopy.actions.augments — repo_augments() + bot_authors()."""
from __future__ import annotations

from pathlib import Path

import pytest

from canopy.actions.augments import bot_authors, repo_augments
from canopy.workspace.config import RepoConfig, WorkspaceConfig


def _ws(
    *,
    augments: dict | None = None,
    repos: list[RepoConfig] | None = None,
    root: Path = Path("/tmp"),
) -> WorkspaceConfig:
    return WorkspaceConfig(
        name="ws",
        repos=repos or [],
        root=root,
        augments=augments or {},
    )


# ── repo_augments ────────────────────────────────────────────────────────


def test_repo_augments_returns_workspace_defaults_when_no_per_repo():
    ws = _ws(
        augments={"preflight_cmd": "make check"},
        repos=[RepoConfig(name="api", path="./api")],
    )
    assert repo_augments(ws, "api") == {"preflight_cmd": "make check"}


def test_repo_augments_per_repo_wins_on_collision():
    ws = _ws(
        augments={"preflight_cmd": "make check", "test_cmd": "pytest"},
        repos=[RepoConfig(
            name="api", path="./api",
            augments={"preflight_cmd": "uv run pytest tests/fast"},
        )],
    )
    merged = repo_augments(ws, "api")
    assert merged == {
        "preflight_cmd": "uv run pytest tests/fast",   # per-repo wins
        "test_cmd": "pytest",                          # workspace default carries through
    }


def test_repo_augments_empty_when_neither_set():
    ws = _ws(repos=[RepoConfig(name="api", path="./api")])
    assert repo_augments(ws, "api") == {}


def test_repo_augments_returns_workspace_defaults_when_repo_unknown():
    """Caller may have a path but not a resolved RepoConfig; defaults still apply."""
    ws = _ws(augments={"preflight_cmd": "make check"})
    assert repo_augments(ws, "ghost") == {"preflight_cmd": "make check"}


def test_repo_augments_preserves_unknown_keys():
    """Lenient parser → unknown keys flow through."""
    ws = _ws(
        augments={"future_key": "value"},
        repos=[RepoConfig(name="api", path="./api", augments={"another_future": 42})],
    )
    merged = repo_augments(ws, "api")
    assert merged == {"future_key": "value", "another_future": 42}


# ── bot_authors ──────────────────────────────────────────────────────────


def test_bot_authors_lowercases_and_returns_list():
    ws = _ws(augments={"review_bots": ["CodeRabbit", "Korbit"]})
    assert bot_authors(ws) == ["coderabbit", "korbit"]


def test_bot_authors_empty_when_unset():
    ws = _ws(augments={"preflight_cmd": "make check"})
    assert bot_authors(ws) == []


def test_bot_authors_empty_when_no_augments_block():
    ws = _ws()
    assert bot_authors(ws) == []


def test_bot_authors_skips_falsy_entries():
    ws = _ws(augments={"review_bots": ["coderabbit", "", None, "korbit"]})
    assert bot_authors(ws) == ["coderabbit", "korbit"]


def test_bot_authors_returns_empty_when_review_bots_not_a_list():
    """Lenient: malformed value yields empty list, not crash."""
    ws = _ws(augments={"review_bots": "coderabbit"})   # should be a list
    assert bot_authors(ws) == []


def test_bot_authors_ignores_per_repo_overrides():
    """review_bots is a workspace-level concern; per-repo overrides are intentionally ignored."""
    ws = _ws(
        augments={"review_bots": ["coderabbit"]},
        repos=[RepoConfig(name="api", path="./api", augments={"review_bots": ["different"]})],
    )
    assert bot_authors(ws) == ["coderabbit"]
