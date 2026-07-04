"""Tests for cli/render.py — fix_action command strings must be runnable."""
from __future__ import annotations

import io

from rich.console import Console

from canopy.actions.errors import BlockerError, FixAction
from canopy.cli.render import render_blocker


def _render(err) -> str:
    buf = io.StringIO()
    console = Console(file=buf, width=200, force_terminal=False)
    render_blocker(err, action="switch", console=console)
    return buf.getvalue()


def test_config_slots_renders_positional():
    """A config+slots fix_action must render `canopy config slots <N>`
    (positional), not `canopy config --slots <N>` (which the CLI rejects)."""
    err = BlockerError(
        code="worktree_cap_reached", what="cap full",
        fix_actions=[FixAction(action="config", args={"slots": 3}, safe=True,
                               preview="raise cap")],
    )
    out = _render(err)
    assert "canopy config slots 3" in out
    assert "--slots" not in out


def test_switch_flag_uses_dash_not_underscore():
    """Boolean flag keys with underscores must render with dashes
    (`--release-current`, the real flag) — never `--release_current`."""
    err = BlockerError(
        code="x", what="y",
        fix_actions=[FixAction(action="switch",
                               args={"feature": "Y", "release_current": True},
                               safe=True, preview="p")],
    )
    out = _render(err)
    assert "canopy switch Y --release-current" in out
    assert "release_current" not in out
