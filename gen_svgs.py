"""Generate CLI preview SVGs for docs using Rich Console export.

Imports theme + symbols from `canopy.cli.ui` so the SVGs stay in
lockstep with the live CLI palette. Run with:

    python gen_svgs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from rich.console import Console

from canopy.cli.ui import (
    CANOPY_THEME,
    SYM_ARROW,
    SYM_BRANCH,
    SYM_CHECK,
    SYM_CLEAN,
    SYM_CROSS,
    SYM_DIRTY,
    SYM_DOT,
    SYM_LINK,
)

# Default width — enough room for paths but not so wide it dominates
# the README on small viewports.
W = 76


def _con() -> Console:
    return Console(theme=CANOPY_THEME, record=True, width=W)


# ─── Banner ─────────────────────────────────────────────────────────────
def gen_banner() -> str:
    c = Console(theme=CANOPY_THEME, record=True, width=60)
    c.print()
    c.print()
    c.print("   [bold]canopy[/]")
    c.print()
    c.print("   [muted]multi-repo work, one focused command[/]")
    c.print()
    c.print(f"   [muted]$[/] [info]canopy[/] [feature]switch[/] [muted]<feature>[/]")
    c.print()
    c.print()
    return c.export_svg(title="canopy")


# ─── Hero: canopy switch ────────────────────────────────────────────────
def gen_switch() -> str:
    c = _con()
    c.print()
    c.print("[muted]$[/] [info]canopy switch sin-7-empty-state[/]")
    c.print()
    c.print(f"  [header]Evacuating[/] [feature]sin-6-cache-stats[/] [muted]{SYM_ARROW} warm worktree[/]")
    c.print(f"  [success]{SYM_CHECK}[/] [repo]test-api[/]  [muted]stashed 1 file →[/] [path].canopy/worktrees/sin-6-cache-stats/test-api[/]")
    c.print(f"  [success]{SYM_CHECK}[/] [repo]test-ui[/]   [muted]clean, no stash[/]")
    c.print()
    c.print(f"  [header]Promoting[/] [feature]sin-7-empty-state[/] [muted]{SYM_ARROW} main[/]")
    c.print(f"  [success]{SYM_CHECK}[/] [repo]test-api[/]  [muted]checkout[/] [branch]sin-7-empty-state[/]")
    c.print(f"  [success]{SYM_CHECK}[/] [repo]test-ui[/]   [muted]stayed on[/] [branch]main[/]  [muted](not in feature scope)[/]")
    c.print()
    c.print(f"  [success]{SYM_CHECK} Switched.[/] [muted]Main is now[/] [feature]sin-7-empty-state[/]")
    c.print()
    return c.export_svg(title="canopy switch")


# ─── canopy status ──────────────────────────────────────────────────────
def gen_status() -> str:
    c = _con()
    c.print()
    c.print("[muted]$[/] [info]canopy status[/]")
    c.print()
    c.print(f"  [header]canopy-test[/]  [path]~/projects/canopy-test[/]")
    c.print(f"  [muted]{'─' * 60}[/]")
    c.print()
    c.print(f"  [repo]test-api[/]  [muted]· canonical[/]")
    c.print(f"    [muted]{SYM_BRANCH}[/] [branch]sin-7-empty-state[/]  [clean]{SYM_CLEAN} clean[/]  [ahead]↑1[/]")
    c.print(f"    [muted]9c2e1abc[/]")
    c.print()
    c.print(f"  [repo]test-ui[/]  [muted]· default[/]")
    c.print(f"    [muted]{SYM_BRANCH}[/] [branch]main[/]  [clean]{SYM_CLEAN} clean[/]")
    c.print(f"    [muted]def4567g[/]")
    c.print()
    c.print(f"  [header]Active[/]  [feature]sin-7-empty-state[/]  [linear]{SYM_LINK} SIN-7: Empty-state illustration[/]")
    c.print()
    return c.export_svg(title="canopy status")


# ─── canopy init ────────────────────────────────────────────────────────
def gen_init() -> str:
    c = _con()
    c.print()
    c.print("[muted]$[/] [info]canopy init[/]")
    c.print()
    c.print(f"  [header]Found 2 repos[/]")
    c.print(f"  [repo]test-api[/]  [path]~/projects/canopy-test/canopy-test-api[/]")
    c.print(f"  [repo]test-ui[/]   [path]~/projects/canopy-test/canopy-test-ui[/]")
    c.print()
    c.print(f"  [header]Drift hooks (2)[/]")
    c.print(f"  [repo]test-api[/]  [success]{SYM_CHECK}[/] [muted]post-checkout installed[/]")
    c.print(f"  [repo]test-ui[/]   [success]{SYM_CHECK}[/] [muted]post-checkout installed[/]")
    c.print()
    c.print(f"  [header]Claude Code agent setup[/]")
    c.print(f"  skill   [success]{SYM_CHECK}[/] installed  [muted]~/.claude/skills/using-canopy/SKILL.md[/]")
    c.print(f"  mcp     [success]{SYM_CHECK}[/] registered [muted]./.mcp.json[/]")
    c.print()
    c.print(f"  [muted]Restart Claude Code to pick up the skill + MCP. Skip with --no-agent.[/]")
    c.print()
    return c.export_svg(title="canopy init")


# ─── canopy commit ──────────────────────────────────────────────────────
def gen_commit() -> str:
    c = _con()
    c.print()
    c.print("[muted]$[/] [info]canopy commit -m \"wire cache hit-rate metric\"[/]")
    c.print()
    c.print(f"  [header]Committing[/] [feature]sin-6-cache-stats[/] [muted]across 2 repos[/]")
    c.print(f"  [success]{SYM_CHECK}[/] [repo]test-api[/]  [muted]1 file →[/] [muted]a3f9c2e1[/]")
    c.print(f"  [success]{SYM_CHECK}[/] [repo]test-ui[/]   [muted]2 files →[/] [muted]b8d4e5f7[/]")
    c.print()
    c.print(f"  [success]{SYM_CHECK} Committed.[/] [muted]Run[/] [info]canopy push[/] [muted]to publish.[/]")
    c.print()
    return c.export_svg(title="canopy commit")


# ─── canopy push ────────────────────────────────────────────────────────
def gen_push() -> str:
    c = _con()
    c.print()
    c.print("[muted]$[/] [info]canopy push[/]")
    c.print()
    c.print(f"  [header]Pushing[/] [feature]sin-6-cache-stats[/]")
    c.print(f"  [success]{SYM_CHECK}[/] [repo]test-api[/]  [muted]→[/] [path]origin/sin-6-cache-stats[/]  [ahead]2 commits[/]")
    c.print(f"  [success]{SYM_CHECK}[/] [repo]test-ui[/]   [muted]→[/] [path]origin/sin-6-cache-stats[/]  [ahead]1 commit[/]")
    c.print()
    return c.export_svg(title="canopy push")


# ─── canopy triage ──────────────────────────────────────────────────────
def gen_triage() -> str:
    c = _con()
    c.print()
    c.print("[muted]$[/] [info]canopy triage[/]")
    c.print()
    c.print(f"  [header]Triage  [muted](5 active features)[/][/]")
    c.print(f"  [muted]{'─' * 60}[/]")
    c.print()
    c.print(f"  [error]changes_requested[/]  [feature]doc-1001-paired[/]  [linear]{SYM_LINK} SIN-3[/]")
    c.print(f"    [muted]2 unresolved threads · canonical · ↑3[/]")
    c.print()
    c.print(f"  [warning]review_required[/]   [feature]sin-6-cache-stats[/]  [linear]{SYM_LINK} SIN-6[/]")
    c.print(f"    [muted]PR opened 2h ago · 0 reviewers · ↑2[/]")
    c.print()
    c.print(f"  [success]approved[/]          [feature]doc-1004-bot-feedback[/]  [linear]{SYM_LINK} SIN-4[/]")
    c.print(f"    [muted]ready to merge · 1 repo · ↑1[/]")
    c.print()
    return c.export_svg(title="canopy triage")


# ─── canopy review (refresh in new theme) ───────────────────────────────
def gen_review() -> str:
    c = _con()
    c.print()
    c.print("[muted]$[/] [info]canopy review sin-6-cache-stats[/]")
    c.print()
    c.print(f"  [feature]sin-6-cache-stats[/]  [linear]{SYM_LINK} SIN-6[/]")
    c.print(f"  [muted]{'─' * 60}[/]")
    c.print(f"  [repo]test-api[/]  [success]PR #142[/]  [warning]changes_requested[/]")
    c.print(f"    [path]github.com/acme/test-api/pull/142[/]")
    c.print(f"  [repo]test-ui[/]   [muted]no PR yet[/]")
    c.print()
    c.print(f"  [warning]2 actionable threads[/]  [muted](1 likely-resolved hidden)[/]")
    c.print()
    c.print(f"  [repo]test-api[/]  [muted]#142[/]")
    c.print(f"    [path]src/api/cache.py:42[/]")
    c.print(f"      [info]alice[/]: \"rename hit_rate → cache_hit_rate for clarity\"")
    c.print(f"    [path]src/api/cache.py:67[/]")
    c.print(f"      [info]bob[/]: \"add a TTL-expiry metric alongside\"")
    c.print()
    return c.export_svg(title="canopy review")


# ─── canopy state ───────────────────────────────────────────────────────
def gen_state() -> str:
    c = _con()
    c.print()
    c.print("[muted]$[/] [info]canopy state sin-6-cache-stats[/]")
    c.print()
    c.print(f"  [feature]sin-6-cache-stats[/]  [linear]{SYM_LINK} SIN-6[/]")
    c.print(f"  [muted]{'─' * 60}[/]")
    c.print(f"  [header]State[/]    [warning]needs_work[/]")
    c.print(f"  [header]Slot[/]     [success]canonical[/]   [muted](checked out in main)[/]")
    c.print()
    c.print(f"  [header]Repos[/]")
    c.print(f"  [repo]test-api[/]  [success]{SYM_CHECK}[/] [muted]hooks ok[/]  [dirty]{SYM_DIRTY} 1 dirty[/]  [ahead]↑2[/]")
    c.print(f"  [repo]test-ui[/]   [success]{SYM_CHECK}[/] [muted]clean[/]")
    c.print()
    c.print(f"  [header]Next actions[/]")
    c.print(f"  [info]1.[/] Address 2 unresolved review threads on PR #142")
    c.print(f"  [info]2.[/] [muted]canopy commit + canopy push to publish fixes[/]")
    c.print()
    return c.export_svg(title="canopy state")


def gen_list() -> str:
    c = _con()
    c.print()
    c.print("[muted]$[/] [info]canopy list[/]")
    c.print()
    c.print(f"  [feature]sin-6-cache-stats[/]  [linear]{SYM_LINK} SIN-6[/]  [muted]2 repos · canonical[/]")
    c.print(f"    [repo]test-api[/]  [dirty]{SYM_DIRTY} 1 dirty[/]  [ahead]↑2[/]")
    c.print(f"    [repo]test-ui[/]   [clean]clean[/]")
    c.print(f"  [feature]sin-7-empty-state[/]  [linear]{SYM_LINK} SIN-7[/]  [muted]1 repo · warm[/]")
    c.print(f"    [repo]test-ui[/]   [ahead]↑1[/]")
    c.print(f"  [feature]doc-1001-paired[/]  [muted]2 repos · cold[/]")
    c.print(f"    [repo]test-api[/]  [branch]doc-1001[/]")
    c.print(f"    [repo]test-ui[/]   [branch]doc-1001[/]")
    c.print()
    return c.export_svg(title="canopy list")


def gen_done() -> str:
    c = _con()
    c.print()
    c.print("[muted]$[/] [info]canopy done sin-6-cache-stats[/]")
    c.print()
    c.print(f"  [header]Done: sin-6-cache-stats[/]")
    c.print(f"  [muted]{'─' * 60}[/]")
    c.print(f"  [muted]Worktrees removed[/]")
    c.print(f"  [success]{SYM_CHECK}[/] [repo]test-api[/]  [muted].canopy/worktrees/sin-6-cache-stats/test-api[/]")
    c.print(f"  [muted]Branches deleted[/]")
    c.print(f"  [success]{SYM_CHECK}[/] [repo]test-api[/]  [branch]sin-6-cache-stats[/]")
    c.print(f"  [success]{SYM_CHECK}[/] [repo]test-ui[/]   [branch]sin-6-cache-stats[/]")
    c.print(f"  [muted]{'─' * 60}[/]")
    c.print(f"  [success]{SYM_CHECK} Archived in features.json[/]")
    c.print()
    return c.export_svg(title="canopy done")


def gen_drift() -> str:
    c = _con()
    c.print()
    c.print("[muted]$[/] [info]canopy drift[/]")
    c.print()
    c.print(f"  [warning]Drift detected[/]  [muted]across 2 repos[/]")
    c.print(f"  [muted]{'─' * 60}[/]")
    c.print(f"  [repo]test-api[/]  [muted]expected:[/] [branch]sin-6-cache-stats[/]  [muted]actual:[/] [error]main[/]")
    c.print(f"  [repo]test-ui[/]   [muted]aligned ✓[/]")
    c.print()
    c.print(f"  [muted]Run[/] [info]canopy switch sin-6-cache-stats[/] [muted]to realign all repos.[/]")
    c.print()
    return c.export_svg(title="canopy drift")


GENERATORS = {
    "canopy-banner": gen_banner,
    "cli-switch":   gen_switch,
    "cli-status":   gen_status,
    "cli-init":     gen_init,
    "cli-commit":   gen_commit,
    "cli-push":     gen_push,
    "cli-triage":   gen_triage,
    "cli-review":   gen_review,
    "cli-state":    gen_state,
    "cli-list":     gen_list,
    "cli-done":     gen_done,
    "cli-drift":    gen_drift,
}


if __name__ == "__main__":
    out_dir = Path("docs")
    out_dir.mkdir(exist_ok=True)
    for name, fn in GENERATORS.items():
        svg = fn()
        path = out_dir / f"{name}.svg"
        path.write_text(svg)
        print(f"  wrote {path}")
