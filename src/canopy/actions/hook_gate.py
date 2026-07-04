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


@dataclass
class GateDecision:
    allow: bool
    code: str = ""       # "outside_repo" | "trunk_branch_drift" | "slot_branch_drift" | "push_unknown_branch"
    reason: str = ""     # fed to the model on deny — must name the fix


def _repo_dirs(workspace) -> dict[Path, tuple[str, str | None]]:
    """Map of every legal mutation dir → (repo_name, slot_id | None).

    Trunk checkouts map to (repo, None); slot worktrees to (repo, slot_id).
    """
    from . import slots as slots_mod

    dirs: dict[Path, tuple[str, str | None]] = {}
    repo_names = [rs.config.name for rs in workspace.repos]
    for rs in workspace.repos:
        dirs[rs.abs_path.resolve()] = (rs.config.name, None)
    state = slots_mod.read_state(workspace)
    if state is not None:
        for sid in state.slots:
            for name in repo_names:
                p = slots_mod.slot_worktree_path(workspace, sid, name)
                if p.exists():
                    dirs[p.resolve()] = (name, sid)
    return dirs


def _locate(dirs: dict[Path, tuple[str, str | None]], d: Path):
    """Return (repo_root, repo_name, slot_id) if d is at/under a legal dir."""
    d = d.resolve()
    for root, (name, sid) in dirs.items():
        if d == root or root in d.parents:
            return root, name, sid
    return None


def gate_command(workspace, command: str, cwd: Path) -> GateDecision:
    """Decide allow/deny for one Bash command. Pure — no I/O beyond git reads."""
    segments = [s for s in resolve_segments(command, cwd) if is_mutation(s)]
    if not segments:
        return GateDecision(allow=True)
    dirs = _repo_dirs(workspace)
    for seg in segments:
        if not seg.dir_known:
            continue                      # fail open on this segment
        hit = _locate(dirs, seg.effective_dir)
        if hit is None:
            repo_list = ", ".join(sorted(n for n, s in dirs.values() if s is None))
            return GateDecision(
                allow=False, code="outside_repo",
                reason=(
                    f"canopy: blocked `git {seg.argv_after_globals[0]}` — "
                    f"effective directory {seg.effective_dir} is not inside a "
                    f"workspace repo. Repos: {repo_list} (under "
                    f"{workspace.config.root}). Re-run from inside the target "
                    f"repo, e.g. `cd <repo> && git ...`, or use `canopy run`."
                ),
            )
        repo_root, repo_name, slot_id = hit
        if seg.argv_after_globals[0] in _BRANCH_CHECK_SUBCOMMANDS:
            deny = _check_branch(workspace, repo_root, repo_name, slot_id, seg)
            if deny is not None:
                return deny
    return GateDecision(allow=True)


_BRANCH_CHECK_SUBCOMMANDS = frozenset({"commit", "push"})


def _branch_owner_map(workspace) -> dict[tuple[str, str], str]:
    """(repo_name, branch_name) → feature, for all registered features."""
    from ..features.coordinator import FeatureCoordinator

    out: dict[tuple[str, str], str] = {}
    try:
        features = FeatureCoordinator(workspace)._load_features()
    except Exception:
        return out
    for feat, data in (features or {}).items():
        branches = (data or {}).get("branches") or {}
        for repo_name in (data or {}).get("repos") or []:
            out[(repo_name, branches.get(repo_name, feat))] = feat
    return out


def _check_branch(workspace, repo_root: Path, repo_name: str,
                  slot_id: str | None, seg: GitSegment) -> GateDecision | None:
    """Return a deny decision if the location's branch is drifted, else None."""
    from . import slots as slots_mod
    from ..git import repo as git

    try:
        current = git.current_branch(repo_root)
    except Exception:
        return None                              # fail open
    owners = _branch_owner_map(workspace)
    owner = owners.get((repo_name, current))
    state = slots_mod.read_state(workspace)

    if slot_id is None:
        # Trunk: allowed = default_branch, canonical feature's branch,
        # or any unregistered branch.
        canonical = state.canonical.feature if state and state.canonical else None
        default = workspace.get_repo(repo_name).config.default_branch
        if current == default or owner is None or owner == canonical:
            return None
        return GateDecision(
            allow=False, code="trunk_branch_drift",
            reason=(
                f"canopy: blocked `git {seg.argv_after_globals[0]}` in trunk "
                f"{repo_name} — it is on '{current}' (feature '{owner}') but "
                f"the canonical feature is '{canonical}'. Run "
                f"`canopy switch {owner}` to make '{owner}' official, or "
                f"`canopy switch {canonical}` to restore the trunk branch."
            ),
        )
    # Slot: current branch must be the occupant feature's branch for this repo.
    entry = state.slots.get(slot_id) if state else None
    if entry is None:
        return None                              # doctor's problem, not the gate's
    from .aliases import repos_for_feature
    expected = (repos_for_feature(workspace, entry.feature) or {}).get(repo_name)
    if expected is None or current == expected:
        return None
    return GateDecision(
        allow=False, code="slot_branch_drift",
        reason=(
            f"canopy: blocked `git {seg.argv_after_globals[0]}` in {slot_id} "
            f"({repo_name}) — it is on '{current}' but the slot belongs to "
            f"feature '{entry.feature}' (branch '{expected}'). Run "
            f"`git checkout {expected}` in this worktree, or `canopy doctor`."
        ),
    )
