"""Tests for the PreToolUse Bash gate (hook_gate)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


# ── split_top_level ─────────────────────────────────────────────────────

def test_split_simple_chain():
    from canopy.actions.hook_gate import split_top_level
    assert split_top_level("cd api && git push") == ["cd api", "git push"]


def test_split_respects_quotes():
    from canopy.actions.hook_gate import split_top_level
    parts = split_top_level('git commit -m "fix a && b; done"')
    assert parts == ['git commit -m "fix a && b; done"']


def test_split_semicolons_and_pipes():
    from canopy.actions.hook_gate import split_top_level
    assert split_top_level("git log --oneline | head -5; git status") == [
        "git log --oneline", "head -5", "git status",
    ]


def test_split_ignores_operators_inside_subshell():
    from canopy.actions.hook_gate import split_top_level
    parts = split_top_level('git commit -m "$(date +%s && echo x)" && git push')
    assert parts == ['git commit -m "$(date +%s && echo x)"', "git push"]


def test_split_single_or_chain():
    from canopy.actions.hook_gate import split_top_level
    assert split_top_level("git fetch || true") == ["git fetch", "true"]


# ── resolve_segments ────────────────────────────────────────────────────

def test_cd_chain_updates_effective_dir(tmp_path):
    from canopy.actions.hook_gate import resolve_segments
    segs = resolve_segments("cd api && git push", cwd=tmp_path)
    assert len(segs) == 1  # only git segments are returned
    assert segs[0].argv[:2] == ["git", "push"]
    assert segs[0].effective_dir == tmp_path / "api"
    assert segs[0].dir_known is True


def test_git_dash_c_overrides_dir(tmp_path):
    from canopy.actions.hook_gate import resolve_segments
    segs = resolve_segments(f"git -C {tmp_path}/ui commit -m 'x'", cwd=tmp_path)
    assert segs[0].effective_dir == tmp_path / "ui"
    assert segs[0].argv_after_globals[0] == "commit"


def test_absolute_cd(tmp_path):
    from canopy.actions.hook_gate import resolve_segments
    segs = resolve_segments(f"cd {tmp_path}/api && git add -A && git commit -m 'x'",
                            cwd=Path("/somewhere/else"))
    assert [s.argv_after_globals[0] for s in segs] == ["add", "commit"]
    assert all(s.effective_dir == tmp_path / "api" for s in segs)


def test_unresolvable_cd_marks_dir_unknown(tmp_path):
    from canopy.actions.hook_gate import resolve_segments
    segs = resolve_segments('cd "$PROJECT_DIR" && git push', cwd=tmp_path)
    assert segs[0].dir_known is False   # fail-open downstream


def test_non_git_segments_skipped(tmp_path):
    from canopy.actions.hook_gate import resolve_segments
    segs = resolve_segments("ls -la && pytest tests/ -v", cwd=tmp_path)
    assert segs == []


def test_unparseable_segment_skipped(tmp_path):
    from canopy.actions.hook_gate import resolve_segments
    # unbalanced quote inside one segment must not raise
    segs = resolve_segments("git commit -m 'unclosed && git push", cwd=tmp_path)
    assert isinstance(segs, list)
