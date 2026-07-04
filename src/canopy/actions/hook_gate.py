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

import re as _re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_GIT_WORD = _re.compile(r"\bgit\b")


def _heredoc_delimiter(command: str, i: int) -> tuple[str, int, bool] | None:
    """If ``command[i:]`` starts a heredoc redirection (``<<``/``<<-`` plus
    a delimiter word in any of the <<EOF / <<-EOF / <<'EOF' / <<"EOF" /
    <<\\EOF forms), return (delimiter, index just past the delimiter
    token, tab_indent_ok — True for ``<<-``); else None. ``<<<``
    herestrings are not heredocs (guarded on both sides so the scan
    cannot re-enter at the middle ``<``)."""
    n = len(command)
    if command[i:i + 2] != "<<" or command[i + 2:i + 3] == "<":
        return None
    if i > 0 and command[i - 1] == "<":
        return None                       # tail of a <<< herestring
    j = i + 2
    tab_indent_ok = False
    if j < n and command[j] == "-":
        tab_indent_ok = True
        j += 1
    while j < n and command[j] in " \t":
        j += 1
    if j < n and command[j] in ("'", '"'):
        k = command.find(command[j], j + 1)
        if k == -1 or k == j + 1:
            return None                   # unterminated/empty quoted delim
        return command[j + 1:k], k + 1, tab_indent_ok
    if j < n and command[j] == "\\":
        j += 1                            # <<\EOF — POSIX quoted form
    k = j
    while k < n and (command[k].isalnum() or command[k] == "_"):
        k += 1
    if k == j:
        return None                       # no delimiter word
    return command[j:k], k, tab_indent_ok


def split_top_level(command: str) -> list[str]:
    """Split a shell command on top-level ``&&``, ``||``, ``;``, ``|``,
    and unquoted newlines.

    Quote- and subshell-aware: operators inside '...', "...", $(...),
    backticks, or (...) do not split. Heredoc-aware: after an unquoted
    depth-0 ``<<DELIM``, all splitting is suppressed until the line that
    equals DELIM exactly (``<<-`` also accepts leading tabs); splitting
    resumes after that terminator line. Best-effort — this is a gate
    heuristic, not a shell. Unbalanced input returns whatever was
    accumulated (callers fail open on weirdness).
    """
    parts: list[str] = []
    buf: list[str] = []
    depth = 0          # () and $() nesting
    quote: str | None = None   # "'", '"', or '`'
    heredoc: str | None = None  # pending heredoc terminator word
    heredoc_tabs = False        # <<- form: terminator may be tab-indented
    i, n = 0, len(command)
    while i < n:
        ch = command[i]
        if heredoc is not None:
            # Inside a heredoc: copy verbatim — no quote/operator handling.
            buf.append(ch)
            if ch == "\n":
                j = command.find("\n", i + 1)
                end = j if j != -1 else n
                line = command[i + 1:end]
                if heredoc_tabs:
                    line = line.lstrip("\t")
                if line == heredoc:
                    buf.append(command[i + 1:end])
                    heredoc = None
                    i = end       # the newline after the terminator splits
                    continue
            i += 1
            continue
        if quote:
            buf.append(ch)
            if ch == quote and command[i - 1] != "\\":
                quote = None
            i += 1
            continue
        if depth == 0 and ch == "<":
            hd = _heredoc_delimiter(command, i)
            if hd is not None:
                heredoc, end_tok, heredoc_tabs = hd
                buf.append(command[i:end_tok])
                i = end_tok
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
            if ch in (";", "|", "\n") and two != "||":
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
    token = raw.strip()
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
            rest = argv[1:]
            while rest and rest[0] in ("-P", "-L", "-e", "--"):
                rest = rest[1:]
            if not rest or rest[0].startswith("-"):
                known = False
                continue
            cur, known = _resolve_path(cur, rest[0])
            continue
        if argv[0] != "git":
            continue
        seg_dir, seg_known = cur, known
        # git -C <path> (repeatable, cumulative per git semantics — apply in order)
        i = 1
        while i < len(argv) - 1:
            if argv[i] == "-c":
                i += 2
                continue
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
    "commit", "push", "merge", "rebase", "reset",
    "cherry-pick", "add", "rm", "mv", "am", "revert",
})

# ``stash`` alone is a mutation subcommand, but its own sub-verb decides:
# push/pop/apply/drop/clear/save/branch mutate; list/show are reads. A flag
# right after ``stash`` (``stash -u``, ``stash --keep-index``) is an
# implicit ``stash push`` — a mutation.
_STASH_MUTATING_SUBCOMMANDS = frozenset({
    "push", "pop", "apply", "drop", "clear", "save", "branch",
})


def is_mutation(seg: GitSegment) -> bool:
    sub = seg.argv_after_globals
    if not sub:
        return False
    if sub[0] == "stash":
        return (len(sub) == 1 or sub[1].startswith("-")
                or sub[1] in _STASH_MUTATING_SUBCOMMANDS)
    return sub[0] in MUTATION_SUBCOMMANDS


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
    """Decide allow/deny for one Bash command.

    No side effects; reads git + canopy state only (slots.json, features.json).
    """
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
        if seg.argv_after_globals[0] == "push":
            deny = _check_push_refspec(workspace, repo_root, repo_name, seg)
            if deny is not None:
                return deny
    return GateDecision(allow=True)


_BRANCH_CHECK_SUBCOMMANDS = frozenset({"commit", "push"})


_PUSH_VALUE_FLAGS = ("-o", "--push-option", "--repo", "--receive-pack", "--exec")


def _push_positional_args(args: list[str]) -> list[str]:
    """Positional (non-flag) tokens from a push argv, stopping at the first
    redirect/background operator so shell trailers (``2>&1``, ``> log``,
    ``&``) are never mistaken for a refspec."""
    positional: list[str] = []
    skip_next = False
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if ">" in a or "<" in a or a == "&":
            break                                 # redirect / background — stop
        if a.startswith("-"):
            if a in _PUSH_VALUE_FLAGS:
                skip_next = True                  # value is the next token
            continue
        positional.append(a)
    return positional


def _check_push_refspec(workspace, repo_root: Path, repo_name: str,
                        seg: GitSegment) -> GateDecision | None:
    """Deny pushes of branch names that don't exist in the effective repo."""
    from ..git import repo as git

    args = seg.argv_after_globals[1:]           # after "push"
    positional = _push_positional_args(args)
    if len(positional) < 2:
        return None                              # bare push / push origin
    refspecs = positional[1:]                    # after the remote
    if "--delete" in args or "-d" in args:
        return None
    for spec in refspecs:
        src = spec.split(":", 1)[0].lstrip("+")
        # «...» is the corpus miner's redaction placeholder for values it
        # scrubbed — never a real branch name, so don't try to resolve it.
        if not src or src in ("HEAD",) or "/" in src or "«" in src:
            continue                             # HEAD/tags-with-path/redacted
        try:
            if git.branch_exists(repo_root, src):
                continue
        except Exception:
            return None                          # fail open
        elsewhere = [
            rs.config.name for rs in workspace.repos
            if rs.config.name != repo_name and rs.abs_path.exists()
            and git.branch_exists(rs.abs_path, src)
        ]
        hint = (f" That branch exists in {', '.join(elsewhere)} — wrong repo?"
                if elsewhere else "")
        return GateDecision(
            allow=False, code="push_unknown_branch",
            reason=(
                f"canopy: blocked `git push` in {repo_name} — branch '{src}' "
                f"does not exist here (src refspec would fail).{hint} "
                f"Check the branch for THIS repo with `git branch --list` "
                f"or `canopy context`."
            ),
        )
    return None


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
        if canonical is None:
            reason = (
                f"canopy: blocked `git {seg.argv_after_globals[0]}` in trunk "
                f"{repo_name} — it is on '{current}' (feature '{owner}') but "
                f"no feature is canonical here. Run `canopy switch {owner}` "
                f"to make '{owner}' official."
            )
        else:
            reason = (
                f"canopy: blocked `git {seg.argv_after_globals[0]}` in trunk "
                f"{repo_name} — it is on '{current}' (feature '{owner}') but "
                f"the canonical feature is '{canonical}'. Run "
                f"`canopy switch {owner}` to make '{owner}' official, or "
                f"`canopy switch {canonical}` to restore the trunk branch."
            )
        return GateDecision(allow=False, code="trunk_branch_drift", reason=reason)
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


def _load_workspace_from(start: Path):
    """Walk up from ``start`` to find canopy.toml; None if not in a workspace."""
    from ..workspace.config import load_config
    from ..workspace.workspace import Workspace

    cur = Path(start).resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / "canopy.toml").exists():
            return Workspace(load_config(candidate))
    return None


def run_gate(payload: dict[str, Any]) -> tuple[int, str]:
    """Full PreToolUse decision from the raw hook payload.

    Returns (exit_code, stderr_message): (0, "") allow, (2, reason) block.
    NEVER raises — the CLI shim trusts this completely.
    """
    import os
    try:
        if os.environ.get("CANOPY_HOOKS_DISABLED") == "1":
            return 0, ""
        if payload.get("tool_name") != "Bash":
            return 0, ""
        command = (payload.get("tool_input") or {}).get("command") or ""
        if not _GIT_WORD.search(command):
            return 0, ""                     # fast path: skip workspace load
        cwd = payload.get("cwd") or "."
        workspace = _load_workspace_from(Path(cwd))
        if workspace is None:
            return 0, ""
        decision = gate_command(workspace, command, Path(cwd))
        if decision.allow:
            return 0, ""
        return 2, decision.reason
    except Exception:
        return 0, ""                          # fail open, always
