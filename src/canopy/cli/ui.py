"""
Rich CLI UI helpers for canopy.

Provides consistent styling, spinners, and formatting across all commands.
All human-readable output goes through these helpers. --json output bypasses them.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from rich.console import Console
from rich.theme import Theme
from rich.tree import Tree
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.spinner import Spinner
from rich.live import Live
from rich.status import Status

# ── Theme ────────────────────────────────────────────────────────────────

CANOPY_THEME = Theme({
    "header":    "bold",                    # weight, not color — let default-fg shine
    "subheader": "bold dim",
    "repo":      "bold",
    "branch":    "color(180)",              # muted khaki
    "feature":   "bold color(218)",         # soft pink — primary accent
    "path":      "color(245)",              # warm grey
    "dirty":     "color(218)",              # soft pink (dirty ≠ error)
    "clean":     "dim",
    "ahead":     "color(151)",              # sage
    "behind":    "color(174)",              # dusty rose
    "info":      "dim",
    "success":   "color(151)",              # sage
    "warning":   "color(218)",              # soft pink
    "error":     "bold color(174)",         # dusty rose
    "muted":     "color(244)",              # warm grey, slightly darker
    "linear":    "color(146)",              # muted lavender
})

console = Console(theme=CANOPY_THEME)


# ── Symbols ──────────────────────────────────────────────────────────────

SYM_CHECK = "✓"
SYM_CROSS = "✗"
SYM_DOT = "●"
SYM_ARROW = "→"
SYM_TREE = "├──"
SYM_TREE_LAST = "└──"
SYM_BRANCH = "⎇"
SYM_DIRTY = "◌"
SYM_CLEAN = "◉"
SYM_LINK = "↗"


# ── Spinners ─────────────────────────────────────────────────────────────

@contextmanager
def spinner(message: str) -> Generator[Status, None, None]:
    """Show a spinner while work is in progress."""
    with console.status(f"[info]{message}[/]", spinner="dots") as status:
        yield status


# ── Formatters ───────────────────────────────────────────────────────────

def status_badge(dirty: bool, dirty_count: int = 0) -> str:
    """Format a dirty/clean status badge."""
    if dirty:
        label = f"{dirty_count} dirty" if dirty_count else "dirty"
        return f"[dirty]{SYM_DIRTY} {label}[/]"
    return f"[clean]{SYM_CLEAN} clean[/]"


def divergence_str(ahead: int = 0, behind: int = 0) -> str:
    """Format ahead/behind as colored arrows."""
    parts = []
    if ahead:
        parts.append(f"[ahead]↑{ahead}[/]")
    if behind:
        parts.append(f"[behind]↓{behind}[/]")
    return " ".join(parts)


def repo_line(name: str, branch: str = "", dirty: bool = False,
              dirty_count: int = 0, ahead: int = 0, behind: int = 0,
              path: str = "") -> Text:
    """Build a formatted line for a repo entry."""
    text = Text()
    text.append(f"  {name}", style="repo")
    if branch:
        text.append(f"  {SYM_BRANCH} ", style="muted")
        text.append(branch, style="branch")

    parts = []
    if dirty:
        label = f"{dirty_count} dirty" if dirty_count else "dirty"
        parts.append(f"[dirty]{label}[/]")
    if ahead:
        parts.append(f"[ahead]+{ahead}[/]")
    if behind:
        parts.append(f"[behind]-{behind}[/]")
    if parts:
        text.append("  ")
        # Can't use rich markup inside Text.append, so use plain
        text.append("(", style="muted")
        for i, p in enumerate(parts):
            if "dirty" in p:
                text.append(p.replace("[dirty]", "").replace("[/]", ""), style="dirty")
            elif "+" in p:
                text.append(p.replace("[ahead]", "").replace("[/]", ""), style="ahead")
            elif "-" in p:
                text.append(p.replace("[behind]", "").replace("[/]", ""), style="behind")
            if i < len(parts) - 1:
                text.append(", ", style="muted")
        text.append(")", style="muted")

    if path:
        text.append(f"\n    {path}", style="path")
    return text


def section_header(title: str) -> None:
    """Print a section header."""
    console.print()
    console.print(f"  [header]{title}[/]")


def print_success(message: str) -> None:
    """Print a success message with checkmark."""
    console.print(f"  [success]{SYM_CHECK}[/] {message}")


def print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"  [warning]![/] {message}")


def print_error(message: str) -> None:
    """Print an error message."""
    console.print(f"  [error]{SYM_CROSS}[/] {message}")


def separator() -> None:
    """Print a dim separator line."""
    console.print(f"  [muted]{'─' * 52}[/]")
