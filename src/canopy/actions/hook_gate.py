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


@dataclass
class GitSegment:
    """One ``git ...`` command with its resolved execution directory."""
    argv: list[str]                    # full tokens, argv[0] == "git"
    effective_dir: Path
    dir_known: bool = True             # False ⇒ fail open on this segment

    @property
    def argv_after_globals(self) -> list[str]:
        """argv with ``git`` + global flags stripped → starts at subcommand."""
        i = 1
        n = len(self.argv)
        while i < n:
            tok = self.argv[i]
            if tok == "-C" or tok == "-c":
                i += 2
                continue
            if tok.startswith("--git-dir") or tok.startswith("--work-tree"):
                # exotic — subcommand detection still works; dir override
                # already handled (fail-open) in resolve_segments
                i += 1 if "=" in tok else 2
                continue
            if tok.startswith("-"):
                i += 1
                continue
            return self.argv[i:]
        return []


_UNRESOLVABLE = ("$", "~", "`")   # vars/home/expansion → don't guess


def _resolve_path(base: Path, raw: str) -> tuple[Path, bool]:
    token = raw.strip().strip('"').strip("'")
    if not token or any(m in token for m in _UNRESOLVABLE):
        return base, False
    p = Path(token)
    return (p if p.is_absolute() else (base / p)), True


def resolve_segments(command: str, cwd: Path) -> list[GitSegment]:
    """Walk the command's top-level segments tracking the effective dir.

    Returns only git segments. ``cd`` updates the tracked dir for later
    segments; ``git -C <path>`` overrides for that segment only. An
    unresolvable ``cd`` (variables, ``~``, ``cd -``) poisons dir_known
    for everything after it.
    """
    out: list[GitSegment] = []
    cur = Path(cwd)
    known = True
    for part in split_top_level(command):
        try:
            argv = shlex.split(part, posix=True)
        except ValueError:
            continue                    # unparseable segment: skip, fail open
        if not argv:
            continue
        if argv[0] == "cd":
            if len(argv) < 2 or argv[1] == "-":
                known = False
                continue
            cur, known = _resolve_path(cur, argv[1])
            continue
        if argv[0] != "git":
            continue
        seg_dir, seg_known = cur, known
        # git -C <path> (repeatable, cumulative per git semantics — apply in order)
        i = 1
        while i < len(argv) - 1:
            if argv[i] == "-C":
                seg_dir, ok = _resolve_path(seg_dir, argv[i + 1])
                seg_known = seg_known and ok
                i += 2
                continue
            if argv[i].startswith("--git-dir") or argv[i].startswith("--work-tree"):
                seg_known = False       # too exotic to judge — fail open
            if not argv[i].startswith("-"):
                break
            i += 1
        out.append(GitSegment(argv=argv, effective_dir=seg_dir, dir_known=seg_known))
    return out


# Gated git subcommands. checkout/switch are deliberately ABSENT: they are
# the recovery action for wrong-branch states; blocking them traps the
# agent. Branch safety is enforced on commit/push instead.
MUTATION_SUBCOMMANDS = frozenset({
    "commit", "push", "merge", "rebase", "stash", "reset",
    "cherry-pick", "add", "rm", "mv", "am", "revert",
})


def is_mutation(seg: GitSegment) -> bool:
    sub = seg.argv_after_globals
    return bool(sub) and sub[0] in MUTATION_SUBCOMMANDS
