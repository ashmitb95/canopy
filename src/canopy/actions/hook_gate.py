"""PreToolUse Bash gate — blocks git mutations from the wrong place.

Evidence base (35 days of work-machine transcripts, see
canopy-4.0-distillation.md#evidence): the agent's cwd never leaves the
workspace parent; repo work happens via ``cd <repo> && git ...`` chains.
So the gate resolves the EFFECTIVE directory per command segment (tracking
``cd`` and ``git -C``) and only judges git mutation segments.

Fail-open contract: any parse failure, unresolvable path, or internal
error ⇒ allow. The gate blocks only when it is sure the mutation targets
the wrong place. Exit codes at the CLI layer: 0 = allow, 2 = block
(reason on stderr, which Claude Code feeds back to the model).
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def split_top_level(command: str) -> list[str]:
    """Split a shell command on top-level ``&&``, ``||``, ``;``, ``|``.

    Quote- and subshell-aware: operators inside '...', "...", $(...),
    backticks, or (...) do not split. Best-effort — this is a gate
    heuristic, not a shell. Unbalanced input returns whatever was
    accumulated (callers fail open on weirdness).
    """
    parts: list[str] = []
    buf: list[str] = []
    depth = 0          # () and $() nesting
    quote: str | None = None   # "'", '"', or '`'
    i, n = 0, len(command)
    while i < n:
        ch = command[i]
        if quote:
            buf.append(ch)
            if ch == quote and command[i - 1] != "\\":
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "(":
            depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
            i += 1
            continue
        if depth == 0:
            two = command[i:i + 2]
            if two in ("&&", "||"):
                parts.append("".join(buf).strip())
                buf = []
                i += 2
                continue
            if ch in (";", "|") and two != "||":
                parts.append("".join(buf).strip())
                buf = []
                i += 1
                continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf).strip())
    return [p for p in parts if p]
