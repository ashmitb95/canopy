"""Generate CLI preview SVGs for docs using Rich Console export."""
import sys
sys.path.insert(0, "src")

from rich.console import Console
from rich.theme import Theme

CANOPY_THEME = Theme({
    "header": "bold bright_green",
    "subheader": "bold white",
    "repo": "bold cyan",
    "branch": "yellow",
    "feature": "bold magenta",
    "path": "dim",
    "dirty": "bold red",
    "clean": "green",
    "ahead": "green",
    "behind": "red",
    "info": "dim cyan",
    "success": "bold green",
    "warning": "bold yellow",
    "error": "bold red",
    "muted": "dim",
    "linear": "bold blue",
})

SYM_CHECK = "✓"
SYM_CROSS = "✗"
SYM_ARROW = "→"
SYM_LINK = "🔗"


def gen_list():
    c = Console(theme=CANOPY_THEME, record=True, width=72)
    c.print()
    # Feature 1: auth-flow with Linear + worktree
    c.print(f"  [feature]auth-flow[/]  [linear]{SYM_LINK} ENG-412 Add OAuth2 login[/]  [muted]wt[/]")
    c.print(f"    [repo]api[/] [dirty]*[/] [ahead]↑2[/]  [repo]ui[/] [ahead]↑1[/]")
    # Feature 2: payment-flow with Linear + worktree
    c.print(f"  [feature]payment-flow[/]  [linear]{SYM_LINK} ENG-501 Stripe integration[/]  [muted]wt[/]")
    c.print(f"    [repo]api[/] [ahead]↑3[/]  [repo]ui[/] [dirty]*[/] [ahead]↑1[/]")
    # Feature 3: branch-only, no linear
    c.print(f"  [feature]fix-nav-bug[/]")
    c.print(f"    [repo]ui[/] [dirty]*[/]  [muted]api[/]")
    c.print()
    return c.export_svg(title="canopy list")


def gen_done():
    c = Console(theme=CANOPY_THEME, record=True, width=72)
    c.print()
    c.print(f"  [header]Done: auth-flow[/]")
    c.print(f"  [muted]{'─' * 52}[/]")
    c.print(f"  [muted]Worktrees removed:[/]")
    c.print(f"  [success]{SYM_CHECK}[/] [repo]api[/]  [muted].canopy/worktrees/auth-flow/api[/]")
    c.print(f"  [success]{SYM_CHECK}[/] [repo]ui[/]   [muted].canopy/worktrees/auth-flow/ui[/]")
    c.print(f"  [muted]{'─' * 52}[/]")
    c.print(f"  [muted]Branches:[/]")
    c.print(f"  [success]{SYM_CHECK}[/] [repo]api[/]  deleted")
    c.print(f"  [success]{SYM_CHECK}[/] [repo]ui[/]   deleted")
    c.print(f"  [muted]{'─' * 52}[/]")
    c.print(f"  [success]{SYM_CHECK}[/] Archived in features.json")
    c.print()
    return c.export_svg(title="canopy done auth-flow")


def gen_config():
    c = Console(theme=CANOPY_THEME, record=True, width=72)
    c.print()
    c.print(f"  [info]name[/] = my-product")
    c.print(f"  [info]max_worktrees[/] = 5")
    c.print()
    return c.export_svg(title="canopy config")


def gen_review():
    c = Console(theme=CANOPY_THEME, record=True, width=72)
    c.print()
    c.print(f"  [header]Review: auth-flow[/]")
    c.print(f"  [repo]api[/]  [linear]{SYM_LINK} #42[/] Add OAuth2 endpoints")
    c.print(f"    [path]https://github.com/acme/api/pull/42[/]")
    c.print(f"  [repo]ui[/]   [linear]{SYM_LINK} #18[/] Login page component")
    c.print(f"    [path]https://github.com/acme/ui/pull/18[/]")
    c.print(f"  [muted]{'─' * 52}[/]")
    c.print(f"  [warning]3 unresolved comments[/]")
    c.print()
    c.print(f"  [repo]api[/]  [muted]#42[/]")
    c.print(f"    [path]src/auth/oauth.py[/]")
    c.print(f"      [muted]L42[/] [info]reviewer1[/]: Token refresh should handle 401 gracefully")
    c.print(f"      [muted]L89[/] [info]reviewer2[/]: Missing rate limit on /token endpoint")
    c.print(f"  [repo]ui[/]   [muted]#18[/]")
    c.print(f"    [path]src/components/Login.tsx[/]")
    c.print(f"      [muted]L15[/] [info]reviewer1[/]: Use redirect URI from env, not hardcoded")
    c.print(f"  [muted]{'─' * 52}[/]")
    c.print(f"  [success]{SYM_CHECK}[/] Pre-commit hooks passed")
    c.print(f"  [repo]api[/]  [success]{SYM_CHECK} hooks[/]  [ahead]2 staged[/]")
    c.print(f"  [repo]ui[/]   [success]{SYM_CHECK} hooks[/]  [ahead]1 staged[/]")
    c.print()
    return c.export_svg(title="canopy review auth-flow")


if __name__ == "__main__":
    for name, fn in [("cli-list", gen_list), ("cli-done", gen_done),
                     ("cli-config", gen_config), ("cli-review", gen_review)]:
        svg = fn()
        path = f"docs/{name}.svg"
        with open(path, "w") as f:
            f.write(svg)
        print(f"  wrote {path}")
