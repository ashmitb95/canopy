"""Tests for canopy.integrations.precommit — run_precommit + custom augment path.

The auto-detection branches (framework / git_hook / none) are exercised
indirectly via the existing fixtures; these tests focus on the M2 augments
override path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from canopy.integrations.precommit import run_precommit, _run_custom_preflight


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    """A directory with no pre-commit hooks of any kind — auto-detect → 'none'."""
    return tmp_path


# ── augments: preflight_cmd override ─────────────────────────────────────


def test_run_precommit_runs_custom_cmd_when_augment_set(empty_repo):
    result = run_precommit(empty_repo, augments={"preflight_cmd": "true"})
    assert result["type"] == "custom"
    assert result["passed"] is True
    assert result["applied_augment"] is True
    assert result["command"] == "true"


def test_run_precommit_custom_cmd_failure_surfaces_in_result(empty_repo):
    result = run_precommit(empty_repo, augments={"preflight_cmd": "false"})
    assert result["type"] == "custom"
    assert result["passed"] is False
    assert result["applied_augment"] is True


def test_run_precommit_custom_cmd_supports_shell_chaining(empty_repo):
    """sh -c lets users chain commands with && and pipes."""
    result = run_precommit(empty_repo, augments={"preflight_cmd": "true && true"})
    assert result["passed"] is True


def test_run_precommit_captures_stdout_and_stderr(empty_repo):
    result = run_precommit(
        empty_repo,
        augments={"preflight_cmd": "echo hello && echo oops 1>&2"},
    )
    assert "hello" in result["output"]
    assert "oops" in result["output"]


def test_run_precommit_runs_in_repo_cwd(tmp_path: Path):
    """Custom command's $PWD is the repo path."""
    marker = tmp_path / "marker.txt"
    cmd = f"pwd > {marker}"
    run_precommit(tmp_path, augments={"preflight_cmd": cmd})
    assert marker.exists()
    assert marker.read_text().strip() == str(tmp_path)


# ── augments: missing / falsy preflight_cmd falls back to auto-detect ────


def test_run_precommit_no_augments_uses_auto_detect(empty_repo):
    result = run_precommit(empty_repo)   # no augments arg
    assert result["type"] == "none"      # nothing detected in empty dir
    assert result["passed"] is True
    assert result["applied_augment"] is False


def test_run_precommit_empty_augments_uses_auto_detect(empty_repo):
    result = run_precommit(empty_repo, augments={})
    assert result["type"] == "none"
    assert result["applied_augment"] is False


def test_run_precommit_other_augments_keys_dont_trigger_custom_path(empty_repo):
    """Only preflight_cmd flips to custom mode; test_cmd / review_bots are no-ops here."""
    result = run_precommit(
        empty_repo,
        augments={"test_cmd": "pytest", "review_bots": ["coderabbit"]},
    )
    assert result["type"] == "none"
    assert result["applied_augment"] is False


# ── _run_custom_preflight — direct unit test ─────────────────────────────


def test_run_custom_preflight_returns_command_in_result(empty_repo):
    result = _run_custom_preflight(empty_repo, "echo done")
    assert result["command"] == "echo done"
    assert result["applied_augment"] is True
    assert result["type"] == "custom"
