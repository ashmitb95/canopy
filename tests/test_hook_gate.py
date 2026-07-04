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
