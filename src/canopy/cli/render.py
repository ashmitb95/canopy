"""CLI rendering for action errors and results.

Mirrors the structured shape from canopy.actions.errors so the human-facing
output and the agent-facing JSON describe the same thing. The renderer
accepts either a live ``ActionError`` instance or a serialized ``dict``
(useful when the source is an MCP response).
"""
from __future__ import annotations

from typing import Any

from rich.console import Console

from ..actions.errors import ActionError
from .ui import console as default_console


_STATUS_GLYPH = {"blocked": "✗", "failed": "✗"}
_STATUS_LABEL = {"blocked": "blocked", "failed": "failed"}


def render_blocker(
    err: ActionError | dict[str, Any],
    *,
    action: str | None = None,
    console: Console | None = None,
) -> None:
    """Render a structured error to the console.

    Args:
        err: an ``ActionError`` or a ``to_dict()``-shaped dict.
        action: name of the action that produced the error (e.g., ``"ship"``).
            Used for the header line. Optional but recommended.
        console: rich Console to write to. Defaults to canopy's themed one.
    """
    out = console or default_console
    payload = err.to_dict() if isinstance(err, ActionError) else dict(err)

    status = payload.get("status", "failed")
    code = payload.get("code", "unknown")
    what = payload.get("what", "")
    glyph = _STATUS_GLYPH.get(status, "✗")
    label = _STATUS_LABEL.get(status, status)
    head = f"{action or 'action'} {label}: {what}" if what else f"{action or 'action'} {label}: {code}"

    out.print()
    out.print(f"  [error]{glyph}[/] {head}  [muted]({code})[/]")

    expected = payload.get("expected")
    actual = payload.get("actual")
    if expected is not None or actual is not None:
        out.print()
        if expected is not None:
            out.print(f"    [muted]expected:[/]  {_fmt_value(expected)}")
        if actual is not None:
            out.print(f"    [muted]actual:  [/]  {_fmt_value(actual)}")

    fix_actions = payload.get("fix_actions") or []
    if fix_actions:
        out.print()
        out.print("    [header]fix:[/]")
        for fa in fix_actions:
            label_parts = [f"canopy {fa['action']}"]
            args = fa.get("args") or {}
            for k, v in args.items():
                if k == "feature":
                    label_parts.append(str(v))
                elif isinstance(v, bool) and v:
                    label_parts.append(f"--{k}")
                elif not isinstance(v, bool):
                    label_parts.append(f"--{k} {v}")
            cmd = " ".join(label_parts)
            tag = "[muted](safe)[/]" if fa.get("safe") else "[warning](needs review)[/]"
            out.print(f"      [info]{cmd}[/]  {tag}")
            preview = fa.get("preview")
            if preview:
                out.print(f"        [muted]{preview}[/]")

    details = payload.get("details") or {}
    if details:
        out.print()
        out.print("    [muted]details:[/]")
        for k, v in details.items():
            out.print(f"      [muted]{k}:[/] {_fmt_value(v)}")
    out.print()


def _fmt_value(v: Any) -> str:
    """Render a value compactly. Dicts inline as key=value pairs, lists as commas."""
    if isinstance(v, dict):
        if not v:
            return "{}"
        return ", ".join(f"{k}={_fmt_value(val)}" for k, val in v.items())
    if isinstance(v, (list, tuple)):
        if not v:
            return "[]"
        return ", ".join(_fmt_value(x) for x in v)
    return str(v)
