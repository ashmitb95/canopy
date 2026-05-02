"""Workspace + install integrity checker and repair primitive.

The recovery entry point. When something feels off — a canopy command
fails opaquely, state files look stale, the agent's setup didn't propagate
across machines — this module diagnoses and (optionally) repairs.

Two flavors of check, same shape:

  * **State-integrity** (10 categories): the workspace's own bookkeeping —
    ``heads.json``, ``active_feature.json``, ``preflight.json``,
    ``features.json``, ``.canopy/worktrees/``, per-repo post-checkout hooks,
    branch existence per feature.
  * **Install-staleness** (6 categories): the canopy installation around
    the workspace — CLI binary version, MCP server version, workspace
    ``.mcp.json`` entry, the bundled skill at ``~/.claude/skills/``, and
    duplicate vsix install dirs.

Each check function is pure (read-only) and returns a list of ``Issue``
records. Each repair function takes one ``Issue`` and returns a
``RepairResult``. The orchestrator ``doctor()`` runs the checks (filtered
by category and/or feature scope) and optionally invokes repairs.

The CLI consumes the result via :mod:`canopy.cli.render`; the MCP tool
returns the ``to_dict()`` shape directly. Same structure across surfaces.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .. import __version__
from ..git import hooks as canopy_hooks
from ..git import repo as git
from ..workspace.workspace import Workspace


Severity = Literal["info", "warn", "error"]


# ── Result types ─────────────────────────────────────────────────────────


@dataclass
class Issue:
    """A single diagnosed problem.

    Mirrors :class:`canopy.actions.errors.BlockerError`'s shape so consumers
    that already render structured errors can reuse their machinery. Unlike
    BlockerError, an ``Issue`` is non-raising — checks return lists of them.
    """
    code: str
    severity: Severity
    what: str
    expected: Any = None
    actual: Any = None
    repo: str | None = None
    feature: str | None = None
    fix_action: str | None = None     # human-readable hint (one line)
    auto_fixable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "what": self.what,
            "auto_fixable": self.auto_fixable,
        }
        if self.expected is not None:
            out["expected"] = self.expected
        if self.actual is not None:
            out["actual"] = self.actual
        if self.repo is not None:
            out["repo"] = self.repo
        if self.feature is not None:
            out["feature"] = self.feature
        if self.fix_action is not None:
            out["fix_action"] = self.fix_action
        if self.details:
            out["details"] = dict(self.details)
        return out


@dataclass
class RepairResult:
    code: str
    success: bool
    action_taken: str
    error: str | None = None
    reload_required: bool = False
    repo: str | None = None
    feature: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "success": self.success,
            "action_taken": self.action_taken,
        }
        if self.error is not None:
            out["error"] = self.error
        if self.reload_required:
            out["reload_required"] = True
        if self.repo is not None:
            out["repo"] = self.repo
        if self.feature is not None:
            out["feature"] = self.feature
        return out


# ── Categories ───────────────────────────────────────────────────────────

# Every code maps to (category, check_fn, repair_fn-or-None). The orchestrator
# walks this table — adding a new check is one new entry plus the two
# functions, no other plumbing changes needed.
STATE_CATEGORIES = {
    "heads",
    "active_feature",
    "worktrees",
    "hooks",
    "preflight",
    "features",
    "branches",
}
INSTALL_CATEGORIES = {"cli", "mcp", "skill", "vsix"}
ALL_CATEGORIES = STATE_CATEGORIES | INSTALL_CATEGORIES


# ── State-integrity checks ───────────────────────────────────────────────

def check_heads_stale(workspace: Workspace) -> list[Issue]:
    """heads.json branch+sha vs ``git rev-parse HEAD`` per repo."""
    state = canopy_hooks.read_heads_state(workspace.config.root)
    if not state:
        return []
    issues: list[Issue] = []
    for rs in workspace.repos:
        recorded = state.get(rs.config.name)
        if not recorded:
            continue
        if not rs.abs_path.exists():
            continue
        try:
            current_sha = git.head_sha(rs.abs_path)
            current_branch = git.current_branch(rs.abs_path)
        except git.GitError:
            continue
        recorded_sha = recorded.get("sha", "")
        recorded_branch = recorded.get("branch", "")
        if recorded_sha != current_sha or recorded_branch != current_branch:
            issues.append(Issue(
                code="heads_stale",
                severity="warn",
                what=f"heads.json out of sync for {rs.config.name}",
                expected={"branch": current_branch, "sha": current_sha},
                actual={"branch": recorded_branch, "sha": recorded_sha},
                repo=rs.config.name,
                fix_action="rewrite heads.json from live git",
                auto_fixable=True,
            ))
    return issues


def check_active_feature_orphan(workspace: Workspace) -> list[Issue]:
    """active_feature.json points at a feature missing from features.json."""
    af = _read_raw_active_feature(workspace.config.root)
    if not af:
        return []
    feature = af.get("feature")
    if not feature:
        return []
    features = _load_features_raw(workspace.config.root)
    if feature in features:
        return []
    return [Issue(
        code="active_feature_orphan",
        severity="error",
        what=f"active_feature.json points at unknown feature '{feature}'",
        expected="feature recorded in features.json",
        actual=f"'{feature}' not in features.json",
        feature=feature,
        fix_action="clear active_feature.json",
        auto_fixable=True,
    )]


def check_active_feature_path_missing(workspace: Workspace) -> list[Issue]:
    """active_feature.json lists per_repo_paths that don't exist on disk."""
    af = _read_raw_active_feature(workspace.config.root)
    if not af:
        return []
    feature = af.get("feature") or ""
    paths = af.get("per_repo_paths") or {}
    if not isinstance(paths, dict):
        return []
    issues: list[Issue] = []
    for repo_name, p in paths.items():
        if not isinstance(p, str):
            continue
        if not Path(p).exists():
            issues.append(Issue(
                code="active_feature_path_missing",
                severity="error",
                what=f"active_feature.json path missing for {repo_name}",
                expected=p,
                actual="(does not exist)",
                repo=repo_name,
                feature=feature,
                fix_action="re-resolve paths from features.json + worktree info",
                auto_fixable=True,
            ))
    return issues


def check_worktree_orphan(workspace: Workspace) -> list[Issue]:
    """Worktree directories under .canopy/worktrees/ not referenced by any feature."""
    wt_root = workspace.config.root / ".canopy" / "worktrees"
    if not wt_root.exists():
        return []
    features = _load_features_raw(workspace.config.root)
    issues: list[Issue] = []
    for feat_dir in sorted(wt_root.iterdir()):
        if not feat_dir.is_dir():
            continue
        feature_name = feat_dir.name
        feature_data = features.get(feature_name)
        feature_repos = (feature_data or {}).get("repos") or []
        for repo_dir in sorted(feat_dir.iterdir()):
            if not repo_dir.is_dir():
                continue
            repo_name = repo_dir.name
            if feature_data is None or repo_name not in feature_repos:
                issues.append(Issue(
                    code="worktree_orphan",
                    severity="warn",
                    what=f"orphan worktree dir at {feat_dir.name}/{repo_name}",
                    expected="feature × repo referenced in features.json",
                    actual=str(repo_dir),
                    repo=repo_name,
                    feature=feature_name,
                    fix_action=f"git worktree remove --force {repo_dir}",
                    auto_fixable=True,
                ))
    return issues


def check_worktree_missing(workspace: Workspace) -> list[Issue]:
    """features.json lists worktree_paths for a feature×repo, but the dir is gone."""
    features = _load_features_raw(workspace.config.root)
    issues: list[Issue] = []
    for name, data in features.items():
        if not isinstance(data, dict):
            continue
        if data.get("status", "active") != "active":
            continue
        wt_paths = data.get("worktree_paths") or {}
        if not isinstance(wt_paths, dict):
            continue
        for repo_name, p in wt_paths.items():
            if not isinstance(p, str):
                continue
            if not Path(p).exists():
                issues.append(Issue(
                    code="worktree_missing",
                    severity="error",
                    what=f"feature '{name}' worktree missing in {repo_name}",
                    expected=p,
                    actual="(does not exist)",
                    repo=repo_name,
                    feature=name,
                    fix_action="clear worktree_paths entry; mark cold for repo",
                    auto_fixable=True,
                ))
    return issues


def check_hook_missing(workspace: Workspace) -> list[Issue]:
    """Each managed repo should have canopy's post-checkout hook installed."""
    issues: list[Issue] = []
    for rs in workspace.repos:
        if not rs.abs_path.exists():
            continue
        status = canopy_hooks.hook_status(rs.abs_path)
        if status.get("installed"):
            continue
        if status.get("foreign_hook"):
            issues.append(Issue(
                code="hook_missing",
                severity="error",
                what=f"foreign post-checkout hook at {status['hook_path']}",
                expected="canopy post-checkout hook (chained behind any user hook)",
                actual="non-canopy hook present",
                repo=rs.config.name,
                fix_action="canopy hooks install (chains the existing hook)",
                auto_fixable=True,
            ))
        else:
            issues.append(Issue(
                code="hook_missing",
                severity="error",
                what=f"no post-checkout hook in {rs.config.name}",
                expected="canopy post-checkout hook installed",
                actual="(no hook)",
                repo=rs.config.name,
                fix_action="canopy hooks install",
                auto_fixable=True,
            ))
    return issues


def check_hook_chained_unsafe(workspace: Workspace) -> list[Issue]:
    """Canopy installed but a chained hook is referenced and missing/broken."""
    issues: list[Issue] = []
    for rs in workspace.repos:
        if not rs.abs_path.exists():
            continue
        hooks_dir = canopy_hooks.resolve_hooks_dir(rs.abs_path)
        canopy_hook = hooks_dir / "post-checkout"
        chained = hooks_dir / "post-checkout.canopy-chained"
        if not canopy_hook.exists():
            continue
        text = canopy_hook.read_text()
        # Our hook references the chained file by name; if the chained marker
        # is referenced but the file is missing or non-executable, surface it.
        if "post-checkout.canopy-chained" not in text:
            continue
        if not chained.exists():
            # Reference is benign — the hook checks before exec'ing — but
            # it might indicate the user expected a chained hook.
            continue
        if not os.access(chained, os.X_OK):
            issues.append(Issue(
                code="hook_chained_unsafe",
                severity="warn",
                what=f"chained hook is not executable in {rs.config.name}",
                expected="executable post-checkout.canopy-chained",
                actual=str(chained),
                repo=rs.config.name,
                fix_action="canopy hooks install --reinstall",
                auto_fixable=True,
            ))
    return issues


def check_preflight_stale(workspace: Workspace) -> list[Issue]:
    """preflight.json recorded a result; HEAD has moved → result is no longer valid."""
    path = workspace.config.root / ".canopy" / "state" / "preflight.json"
    if not path.exists():
        return []
    try:
        state = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(state, dict):
        return []
    issues: list[Issue] = []
    for feature, entry in state.items():
        if not isinstance(entry, dict):
            continue
        recorded = entry.get("head_sha_per_repo") or {}
        if not isinstance(recorded, dict):
            continue
        for repo_name, sha in recorded.items():
            try:
                rs = workspace.get_repo(repo_name)
            except KeyError:
                # Unknown repo — features_unknown_repo will also flag this
                continue
            if not rs.abs_path.exists():
                continue
            try:
                current = git.head_sha(rs.abs_path)
            except git.GitError:
                continue
            if current and current != sha:
                issues.append(Issue(
                    code="preflight_stale",
                    severity="info",
                    what=f"preflight result for '{feature}' is stale ({repo_name})",
                    expected={"sha": current},
                    actual={"sha": sha},
                    repo=repo_name,
                    feature=feature,
                    fix_action="clear stale preflight entry",
                    auto_fixable=True,
                ))
                break  # one issue per feature is enough
    return issues


def check_features_unknown_repo(workspace: Workspace) -> list[Issue]:
    """features.json references a repo not in canopy.toml."""
    features = _load_features_raw(workspace.config.root)
    known = {rc.name for rc in workspace.config.repos}
    issues: list[Issue] = []
    for name, data in features.items():
        if not isinstance(data, dict):
            continue
        if data.get("status", "active") != "active":
            continue
        for repo_name in data.get("repos", []) or []:
            if repo_name not in known:
                issues.append(Issue(
                    code="features_unknown_repo",
                    severity="error",
                    what=f"feature '{name}' references unknown repo '{repo_name}'",
                    expected=f"repo '{repo_name}' in canopy.toml",
                    actual="(not configured)",
                    repo=repo_name,
                    feature=name,
                    fix_action="restore the repo or `canopy done` the feature",
                    auto_fixable=False,
                ))
    return issues


def check_branches_missing(workspace: Workspace) -> list[Issue]:
    """Feature has branches[repo] (or implicit branch=name) that doesn't exist locally."""
    features = _load_features_raw(workspace.config.root)
    issues: list[Issue] = []
    for name, data in features.items():
        if not isinstance(data, dict):
            continue
        if data.get("status", "active") != "active":
            continue
        repos = data.get("repos") or []
        branches_map = data.get("branches") or {}
        for repo_name in repos:
            try:
                rs = workspace.get_repo(repo_name)
            except KeyError:
                continue  # features_unknown_repo handles this
            if not rs.abs_path.exists():
                continue
            expected = branches_map.get(repo_name) or name
            try:
                exists = git.branch_exists(rs.abs_path, expected)
            except git.GitError:
                exists = False
            if not exists:
                issues.append(Issue(
                    code="branches_missing",
                    severity="error",
                    what=f"feature '{name}' branch '{expected}' missing in {repo_name}",
                    expected=expected,
                    actual="(no local branch)",
                    repo=repo_name,
                    feature=name,
                    fix_action="restore the branch or `canopy done` the feature",
                    auto_fixable=False,
                ))
    return issues


# ── Install-staleness checks ─────────────────────────────────────────────


def check_cli_stale(workspace: Workspace) -> list[Issue]:
    """`canopy --version` (PATH) is older than the running ``__version__``."""
    cli = shutil.which("canopy")
    if not cli:
        return [Issue(
            code="cli_stale",
            severity="warn",
            what="`canopy` not found on PATH",
            expected=f"canopy {__version__} on PATH",
            actual="(not found)",
            fix_action="reinstall canopy (pipx install canopy or pip install canopy)",
            auto_fixable=False,
        )]
    installed = _read_binary_version(cli)
    if installed is None:
        return []   # can't determine; don't flag
    if _is_older(installed, __version__):
        return [Issue(
            code="cli_stale",
            severity="warn",
            what=f"installed canopy CLI ({installed}) is older than {__version__}",
            expected=__version__,
            actual=installed,
            fix_action="reinstall canopy (pipx upgrade canopy or pip install -U canopy)",
            auto_fixable=False,
            details={"path": cli},
        )]
    return []


def check_mcp_stale(workspace: Workspace) -> list[Issue]:
    """`canopy-mcp --version` is older than the running ``__version__``."""
    mcp_bin = shutil.which("canopy-mcp")
    if not mcp_bin:
        return [Issue(
            code="mcp_stale",
            severity="error",
            what="`canopy-mcp` not found on PATH",
            expected=f"canopy-mcp {__version__} on PATH",
            actual="(not found)",
            fix_action="reinstall canopy (provides the canopy-mcp entry point)",
            auto_fixable=False,
        )]
    installed = _read_binary_version(mcp_bin)
    if installed is None:
        return []
    if _is_older(installed, __version__):
        return [Issue(
            code="mcp_stale",
            severity="error",
            what=f"installed canopy-mcp ({installed}) is older than {__version__}",
            expected=__version__,
            actual=installed,
            fix_action="reinstall canopy (pipx upgrade canopy or pip install -U canopy)",
            auto_fixable=False,
            details={"path": mcp_bin},
        )]
    return []


def check_mcp_missing_in_workspace(workspace: Workspace) -> list[Issue]:
    """workspace .mcp.json lacks a canopy entry, or its CANOPY_ROOT is wrong."""
    from ..agent_setup import mcp_config_path

    target = mcp_config_path(workspace.config.root)
    expected_root = str(workspace.config.root.resolve())
    if not target.exists():
        return [Issue(
            code="mcp_missing_in_workspace",
            severity="error",
            what=".mcp.json missing in workspace",
            expected=f"canopy entry with CANOPY_ROOT={expected_root}",
            actual="(file not present)",
            fix_action="canopy setup-agent (writes .mcp.json)",
            auto_fixable=True,
            details={"path": str(target)},
        )]
    try:
        cfg = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return [Issue(
            code="mcp_missing_in_workspace",
            severity="error",
            what=f".mcp.json is invalid: {e}",
            expected="valid JSON with mcpServers.canopy entry",
            actual="(parse error)",
            fix_action="fix or remove .mcp.json, then `canopy setup-agent`",
            auto_fixable=False,
            details={"path": str(target)},
        )]
    servers = (cfg.get("mcpServers") if isinstance(cfg, dict) else {}) or {}
    entry = servers.get("canopy") if isinstance(servers, dict) else None
    if not isinstance(entry, dict) or entry.get("command") != "canopy-mcp":
        return [Issue(
            code="mcp_missing_in_workspace",
            severity="error",
            what="no canopy entry in .mcp.json",
            expected=f"canopy entry with CANOPY_ROOT={expected_root}",
            actual="(missing or wrong command)",
            fix_action="canopy setup-agent (adds canopy entry)",
            auto_fixable=True,
            details={"path": str(target)},
        )]
    actual_root = (entry.get("env") or {}).get("CANOPY_ROOT", "")
    if actual_root != expected_root:
        return [Issue(
            code="mcp_missing_in_workspace",
            severity="error",
            what="canopy entry CANOPY_ROOT does not match workspace root",
            expected=expected_root,
            actual=actual_root,
            fix_action="canopy setup-agent --reinstall (rewrites entry)",
            auto_fixable=True,
            details={"path": str(target)},
        )]
    return []


def check_skill_missing(workspace: Workspace) -> list[Issue]:
    """No SKILL.md at ~/.claude/skills/using-canopy/."""
    from ..agent_setup import skill_install_target

    target = skill_install_target()
    if target.exists():
        return []
    return [Issue(
        code="skill_missing",
        severity="warn",
        what="using-canopy skill not installed",
        expected=str(target),
        actual="(not present)",
        fix_action="canopy setup-agent",
        auto_fixable=True,
    )]


def check_skill_stale(workspace: Workspace) -> list[Issue]:
    """Installed SKILL.md doesn't byte-match the bundled source."""
    from ..agent_setup import _SKILL_SOURCE, skill_install_target

    target = skill_install_target()
    if not target.exists():
        return []  # missing, not stale — skill_missing handles it
    try:
        installed = target.read_text()
        bundled = _SKILL_SOURCE.read_text()
    except OSError:
        return []
    if installed == bundled:
        return []
    is_canopy = "name: using-canopy" in installed
    if not is_canopy:
        # foreign skill at our path — install_skill won't overwrite without
        # --reinstall, so flag for user attention.
        return [Issue(
            code="skill_stale",
            severity="warn",
            what="foreign skill at using-canopy path",
            expected="canopy's bundled skill",
            actual="(non-canopy content)",
            fix_action="canopy setup-agent --reinstall (overwrites)",
            auto_fixable=False,
            details={"path": str(target)},
        )]
    return [Issue(
        code="skill_stale",
        severity="warn",
        what="using-canopy skill content drifted from bundled source",
        expected="byte-equal with bundled skill",
        actual="(diff)",
        fix_action="canopy setup-agent --reinstall",
        auto_fixable=True,
        details={"path": str(target)},
    )]


_VSIX_PREFIX = "singularityinc.canopy-"


def check_mcp_orphans(workspace: Workspace) -> list[Issue]:
    """Detect orphaned ``canopy-mcp`` processes (parent died, reparented to PID 1).

    Stale MCP servers accumulate when an editor / agent disconnects without
    cleanly closing stdin — the server keeps running waiting for input
    that never comes. Each orphan is idle but holds a venv-Python process
    + a few MB of RSS. ``--fix`` reaps them with SIGTERM (then SIGKILL
    after a short grace) so the process table stays clean.

    See test-findings F-3 (~8 stale processes accumulated over a week of
    real use of canopy-test before this was added).
    """
    pids = _list_orphan_canopy_mcp_pids()
    if not pids:
        return []
    return [Issue(
        code="mcp_orphans",
        severity="info",
        what=f"{len(pids)} orphaned canopy-mcp process(es) found (PPID=1)",
        expected="0 orphans (each MCP server should exit when its parent disconnects)",
        actual=str(len(pids)),
        fix_action="canopy doctor --fix reaps them (SIGTERM, then SIGKILL after 2s)",
        auto_fixable=True,
        details={"pids": pids},
    )]


def _list_orphan_canopy_mcp_pids() -> list[int]:
    """Return PIDs of running ``canopy-mcp`` processes whose parent is PID 1.

    Uses ``ps`` (cross-platform on macOS + Linux) — no extra dependency.
    Skips the current process and its ancestors so a doctor invocation
    from inside an MCP context can't report itself.
    """
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,command="],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    self_pid = os.getpid()
    self_ppid = os.getppid()
    skip = {self_pid, self_ppid}
    out_pids: list[int] = []
    for line in out.stdout.splitlines():
        try:
            pid_s, ppid_s, command = line.lstrip().split(None, 2)
            pid, ppid = int(pid_s), int(ppid_s)
        except (ValueError, IndexError):
            continue
        if pid in skip or ppid in skip:
            continue
        if "canopy-mcp" not in command:
            continue
        if ppid == 1:
            out_pids.append(pid)
    return sorted(out_pids)


def check_vsix_duplicates(workspace: Workspace) -> list[Issue]:
    """Multiple ``singularityinc.canopy-*`` dirs in ~/.vscode/extensions/."""
    ext_dir = Path.home() / ".vscode" / "extensions"
    if not ext_dir.exists():
        return []
    candidates = sorted(
        d for d in ext_dir.iterdir()
        if d.is_dir() and d.name.startswith(_VSIX_PREFIX)
    )
    if len(candidates) <= 1:
        return []
    return [Issue(
        code="vsix_duplicates",
        severity="info",
        what=f"{len(candidates)} canopy vsix install dirs found",
        expected="1 install dir",
        actual=str(len(candidates)),
        fix_action="canopy doctor --clean-vsix (keeps newest)",
        auto_fixable=True,
        details={"paths": [str(p) for p in candidates]},
    )]


# ── Check registry ───────────────────────────────────────────────────────

# code → (category, check_fn). Registry-driven so `--fix=<category>` and
# feature-scoped runs are simple filters.
_CHECKS: dict[str, tuple[str, Any]] = {
    "heads_stale": ("heads", check_heads_stale),
    "active_feature_orphan": ("active_feature", check_active_feature_orphan),
    "active_feature_path_missing": ("active_feature", check_active_feature_path_missing),
    "worktree_orphan": ("worktrees", check_worktree_orphan),
    "worktree_missing": ("worktrees", check_worktree_missing),
    "hook_missing": ("hooks", check_hook_missing),
    "hook_chained_unsafe": ("hooks", check_hook_chained_unsafe),
    "preflight_stale": ("preflight", check_preflight_stale),
    "features_unknown_repo": ("features", check_features_unknown_repo),
    "branches_missing": ("branches", check_branches_missing),
    "cli_stale": ("cli", check_cli_stale),
    "mcp_stale": ("mcp", check_mcp_stale),
    "mcp_missing_in_workspace": ("mcp", check_mcp_missing_in_workspace),
    "skill_missing": ("skill", check_skill_missing),
    "skill_stale": ("skill", check_skill_stale),
    "mcp_orphans": ("mcp", check_mcp_orphans),
    "vsix_duplicates": ("vsix", check_vsix_duplicates),
}


# ── Repairs ──────────────────────────────────────────────────────────────


def repair_heads_stale(workspace: Workspace, issue: Issue) -> RepairResult:
    """Rewrite heads.json from live git for the affected repo."""
    repo_name = issue.repo
    if not repo_name:
        return RepairResult(code=issue.code, success=False, action_taken="",
                            error="missing repo on issue")
    try:
        rs = workspace.get_repo(repo_name)
    except KeyError as e:
        return RepairResult(code=issue.code, success=False, action_taken="",
                            error=str(e), repo=repo_name)
    state_path = workspace.config.root / ".canopy" / "state" / "heads.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = canopy_hooks.read_heads_state(workspace.config.root)
    except Exception:
        state = {}
    try:
        sha = git.head_sha(rs.abs_path)
        branch = git.current_branch(rs.abs_path)
    except git.GitError as e:
        return RepairResult(code=issue.code, success=False, action_taken="",
                            error=str(e), repo=repo_name)
    state[repo_name] = {
        "branch": branch, "sha": sha, "prev_sha": sha,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    tmp = state_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(state_path)
    return RepairResult(
        code=issue.code, success=True, repo=repo_name,
        action_taken=f"rewrote heads.json[{repo_name}] from live HEAD",
    )


def repair_active_feature_orphan(workspace: Workspace, issue: Issue) -> RepairResult:
    """Clear active_feature.json (feature it points at no longer exists)."""
    path = workspace.config.root / ".canopy" / "state" / "active_feature.json"
    if path.exists():
        path.unlink()
    return RepairResult(
        code=issue.code, success=True, feature=issue.feature,
        action_taken="removed active_feature.json",
    )


def repair_active_feature_path_missing(workspace: Workspace, issue: Issue) -> RepairResult:
    """Re-resolve per_repo_paths from features.json + worktree info, or clear if unrecoverable."""
    path = workspace.config.root / ".canopy" / "state" / "active_feature.json"
    if not path.exists():
        return RepairResult(code=issue.code, success=True,
                            action_taken="active_feature.json already absent")
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        path.unlink()
        return RepairResult(code=issue.code, success=True,
                            action_taken="removed unparseable active_feature.json",
                            error=str(e))
    feature = data.get("feature")
    features = _load_features_raw(workspace.config.root)
    feature_data = features.get(feature) if isinstance(feature, str) else None
    if not feature_data or not isinstance(feature_data, dict):
        path.unlink()
        return RepairResult(code=issue.code, success=True, feature=feature,
                            action_taken="removed active_feature.json (no recoverable feature)")
    new_paths: dict[str, str] = {}
    wt_paths = feature_data.get("worktree_paths") or {}
    for repo_name in feature_data.get("repos", []):
        if isinstance(wt_paths, dict) and isinstance(wt_paths.get(repo_name), str):
            p = wt_paths[repo_name]
            if Path(p).exists():
                new_paths[repo_name] = p
                continue
        # Fallback: main repo path from canopy.toml
        try:
            rs = workspace.get_repo(repo_name)
        except KeyError:
            continue
        if rs.abs_path.exists():
            new_paths[repo_name] = str(rs.abs_path)
    data["per_repo_paths"] = new_paths
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)
    return RepairResult(
        code=issue.code, success=True, feature=feature, repo=issue.repo,
        action_taken=f"re-resolved per_repo_paths ({len(new_paths)} repos)",
    )


def repair_worktree_orphan(workspace: Workspace, issue: Issue) -> RepairResult:
    """Remove the orphan worktree directory via ``git worktree remove --force``.

    Falls back to ``rmtree`` if git refuses (e.g., the directory isn't a
    registered worktree any more).
    """
    repo_name = issue.repo
    feature = issue.feature
    if not repo_name or not feature:
        return RepairResult(code=issue.code, success=False, action_taken="",
                            error="missing repo/feature on issue")
    target = workspace.config.root / ".canopy" / "worktrees" / feature / repo_name
    if not target.exists():
        return RepairResult(code=issue.code, success=True,
                            action_taken="orphan dir already gone",
                            repo=repo_name, feature=feature)
    # Try canonical git worktree remove against the parent repo. The repo
    # might itself be a worktree; resolve to the main path before issuing.
    try:
        rs = workspace.get_repo(repo_name)
        repo_root = git.worktree_main_path(rs.abs_path) or rs.abs_path
        git.worktree_remove(repo_root, target, force=True)
        return RepairResult(code=issue.code, success=True, repo=repo_name,
                            feature=feature,
                            action_taken=f"git worktree remove --force {target}")
    except (KeyError, git.GitError):
        # fall through to rmtree
        pass
    try:
        shutil.rmtree(target)
    except OSError as e:
        return RepairResult(code=issue.code, success=False, repo=repo_name,
                            feature=feature, action_taken="",
                            error=f"rmtree failed: {e}")
    # Cleanup empty parent feature dir
    parent = target.parent
    try:
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass
    return RepairResult(code=issue.code, success=True, repo=repo_name,
                        feature=feature,
                        action_taken=f"rmtree {target} (git worktree remove unavailable)")


def repair_worktree_missing(workspace: Workspace, issue: Issue) -> RepairResult:
    """Drop the worktree_paths entry for this repo from features.json."""
    feature = issue.feature
    repo_name = issue.repo
    if not feature or not repo_name:
        return RepairResult(code=issue.code, success=False, action_taken="",
                            error="missing repo/feature on issue")
    features = _load_features_raw(workspace.config.root)
    data = features.get(feature)
    if not isinstance(data, dict):
        return RepairResult(code=issue.code, success=True, feature=feature,
                            action_taken="feature no longer in features.json")
    wt_paths = data.get("worktree_paths")
    if isinstance(wt_paths, dict) and repo_name in wt_paths:
        wt_paths.pop(repo_name)
        if not wt_paths:
            data.pop("worktree_paths", None)
            data.pop("use_worktrees", None)
        _save_features_raw(workspace.config.root, features)
        return RepairResult(code=issue.code, success=True, feature=feature,
                            repo=repo_name,
                            action_taken=f"cleared worktree_paths[{repo_name}] in features.json")
    return RepairResult(code=issue.code, success=True, feature=feature,
                        repo=repo_name,
                        action_taken="no worktree_paths entry to clear")


def repair_hook_missing(workspace: Workspace, issue: Issue) -> RepairResult:
    """Reinstall the post-checkout hook for the affected repo."""
    repo_name = issue.repo
    if not repo_name:
        return RepairResult(code=issue.code, success=False, action_taken="",
                            error="missing repo on issue")
    try:
        rs = workspace.get_repo(repo_name)
    except KeyError as e:
        return RepairResult(code=issue.code, success=False, action_taken="",
                            error=str(e), repo=repo_name)
    if not rs.abs_path.exists():
        return RepairResult(code=issue.code, success=False, repo=repo_name,
                            action_taken="",
                            error=f"repo path does not exist: {rs.abs_path}")
    result = canopy_hooks.install_hook(
        rs.abs_path, repo_name, workspace.config.root,
    )
    return RepairResult(code=issue.code, success=True, repo=repo_name,
                        action_taken=f"hook {result.action} at {result.path}")


def repair_hook_chained_unsafe(workspace: Workspace, issue: Issue) -> RepairResult:
    """Make the chained hook executable (or reinstall via ``install_hook``)."""
    repo_name = issue.repo
    if not repo_name:
        return RepairResult(code=issue.code, success=False, action_taken="",
                            error="missing repo on issue")
    try:
        rs = workspace.get_repo(repo_name)
    except KeyError as e:
        return RepairResult(code=issue.code, success=False, action_taken="",
                            error=str(e), repo=repo_name)
    hooks_dir = canopy_hooks.resolve_hooks_dir(rs.abs_path)
    chained = hooks_dir / "post-checkout.canopy-chained"
    if chained.exists() and not os.access(chained, os.X_OK):
        mode = chained.stat().st_mode
        chained.chmod(mode | 0o111)
        return RepairResult(code=issue.code, success=True, repo=repo_name,
                            action_taken=f"chmod +x {chained}")
    return RepairResult(code=issue.code, success=True, repo=repo_name,
                        action_taken="nothing to do")


def repair_preflight_stale(workspace: Workspace, issue: Issue) -> RepairResult:
    """Drop stale preflight entries (whose recorded sha doesn't match HEAD)."""
    feature = issue.feature
    path = workspace.config.root / ".canopy" / "state" / "preflight.json"
    if not path.exists():
        return RepairResult(code=issue.code, success=True, feature=feature,
                            action_taken="preflight.json absent")
    try:
        state = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        path.unlink()
        return RepairResult(code=issue.code, success=True, feature=feature,
                            action_taken="removed unparseable preflight.json")
    if isinstance(state, dict) and feature and feature in state:
        state.pop(feature, None)
    if not state:
        path.unlink()
        return RepairResult(code=issue.code, success=True, feature=feature,
                            action_taken=f"removed empty preflight.json")
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)
    return RepairResult(code=issue.code, success=True, feature=feature,
                        action_taken=f"cleared preflight entry for '{feature}'")


def repair_mcp_missing_in_workspace(workspace: Workspace, issue: Issue) -> RepairResult:
    """Run ``install_mcp(workspace_root, reinstall=True)``."""
    from ..agent_setup import install_mcp
    result = install_mcp(workspace.config.root, reinstall=True)
    return RepairResult(
        code=issue.code,
        success=result.action != "skipped",
        action_taken=f"install_mcp: {result.action} at {result.path}",
        error=result.reason if result.action == "skipped" else None,
    )


def repair_skill_missing(workspace: Workspace, issue: Issue) -> RepairResult:
    from ..agent_setup import install_skill
    result = install_skill()
    return RepairResult(
        code=issue.code,
        success=result.action != "skipped",
        action_taken=f"install_skill: {result.action} at {result.path}",
        error=result.reason if result.action == "skipped" else None,
    )


def repair_skill_stale(workspace: Workspace, issue: Issue) -> RepairResult:
    from ..agent_setup import install_skill
    result = install_skill(reinstall=True)
    return RepairResult(
        code=issue.code,
        success=result.action != "skipped",
        action_taken=f"install_skill --reinstall: {result.action} at {result.path}",
        error=result.reason if result.action == "skipped" else None,
    )


def repair_mcp_orphans(workspace: Workspace, issue: Issue) -> RepairResult:
    """SIGTERM listed orphan PIDs, then SIGKILL after a 2s grace.

    Skips PIDs we don't own (EPERM) silently — there's no graceful
    recovery for a non-owned orphan and reporting one would just be noise.
    """
    pids = list(issue.details.get("pids") or [])
    if not pids:
        return RepairResult(code=issue.code, success=True,
                            action_taken="no orphans to reap")
    sent: list[int] = []
    failed: list[str] = []
    for pid in pids:
        try:
            os.kill(int(pid), signal.SIGTERM)
            sent.append(int(pid))
        except ProcessLookupError:
            continue   # already gone — fine
        except PermissionError:
            failed.append(f"{pid}: permission denied")
            continue
        except Exception as e:  # noqa: BLE001
            failed.append(f"{pid}: {e}")
            continue
    # Grace period for clean shutdown, then SIGKILL stragglers.
    if sent:
        time.sleep(2.0)
        for pid in sent:
            try:
                os.kill(pid, 0)   # probe — does the pid still exist?
            except ProcessLookupError:
                continue   # gone, good
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                continue
            except Exception as e:  # noqa: BLE001
                failed.append(f"{pid}: SIGKILL: {e}")
    action = f"reaped {len(sent)} orphan(s)"
    if failed:
        return RepairResult(
            code=issue.code, success=bool(sent),
            action_taken=action, error="; ".join(failed),
        )
    return RepairResult(code=issue.code, success=True, action_taken=action)


def repair_vsix_duplicates(workspace: Workspace, issue: Issue) -> RepairResult:
    """Remove all but the newest matching extension dir."""
    paths = [Path(p) for p in (issue.details.get("paths") or [])]
    if len(paths) <= 1:
        return RepairResult(code=issue.code, success=True,
                            action_taken="nothing to clean")
    paths.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    keep = paths[0]
    removed: list[str] = []
    errors: list[str] = []
    for p in paths[1:]:
        try:
            shutil.rmtree(p)
            removed.append(p.name)
        except OSError as e:
            errors.append(f"{p.name}: {e}")
    if errors:
        return RepairResult(
            code=issue.code, success=not removed and False or True,
            action_taken=f"kept {keep.name}; removed {len(removed)}",
            error="; ".join(errors),
        )
    return RepairResult(code=issue.code, success=True,
                        action_taken=f"kept {keep.name}; removed {len(removed)} stale dirs")


_REPAIRS: dict[str, Any] = {
    "heads_stale": repair_heads_stale,
    "active_feature_orphan": repair_active_feature_orphan,
    "active_feature_path_missing": repair_active_feature_path_missing,
    "worktree_orphan": repair_worktree_orphan,
    "worktree_missing": repair_worktree_missing,
    "hook_missing": repair_hook_missing,
    "hook_chained_unsafe": repair_hook_chained_unsafe,
    "preflight_stale": repair_preflight_stale,
    "mcp_missing_in_workspace": repair_mcp_missing_in_workspace,
    "skill_missing": repair_skill_missing,
    "skill_stale": repair_skill_stale,
    "mcp_orphans": repair_mcp_orphans,
    "vsix_duplicates": repair_vsix_duplicates,
    # cli_stale, mcp_stale, features_unknown_repo, branches_missing have
    # no auto-fix — repair returns surfaced advice via the issue's
    # `fix_action` instead.
}


# ── Orchestrator ─────────────────────────────────────────────────────────


def doctor(
    workspace: Workspace,
    *,
    fix: bool = False,
    fix_categories: list[str] | None = None,
    feature: str | None = None,
    clean_vsix: bool = False,
) -> dict[str, Any]:
    """Run the diagnostic suite, optionally repair, return a structured report.

    Args:
        workspace: loaded ``Workspace``.
        fix: if True, run repairs for every auto-fixable issue (subject to
            ``fix_categories`` and the ``clean_vsix`` gate).
        fix_categories: if set, only repair issues in these categories
            (state-integrity: heads/active_feature/worktrees/hooks/preflight/
            features/branches; install: cli/mcp/skill/vsix). Unknown
            categories are silently ignored. Implies ``fix=True``.
        feature: if set, scope feature-bearing checks to this feature only.
            Workspace-wide checks (heads_stale, hook_missing, install-
            staleness) still run in full.
        clean_vsix: required to repair ``vsix_duplicates`` even with ``fix=True``
            — vsix removal is destructive and opt-in.
    """
    if fix_categories is not None:
        fix = True

    all_issues: list[Issue] = []
    for code, (_category, fn) in _CHECKS.items():
        try:
            issues = fn(workspace)
        except Exception as e:  # noqa: BLE001 — checks must never crash the doctor
            issues = [Issue(
                code=code,
                severity="warn",
                what=f"check raised: {e}",
                fix_action="report bug",
                auto_fixable=False,
            )]
        if feature is not None:
            issues = [i for i in issues if i.feature in (None, feature) or i.code in {
                "heads_stale", "hook_missing", "hook_chained_unsafe",
                "cli_stale", "mcp_stale", "mcp_missing_in_workspace",
                "mcp_orphans", "skill_missing", "skill_stale", "vsix_duplicates",
            }]
        all_issues.extend(issues)

    fixed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    if fix:
        for issue in all_issues:
            category, _ = _CHECKS[issue.code]
            if fix_categories is not None and category not in set(fix_categories):
                continue
            if issue.code == "vsix_duplicates" and not clean_vsix:
                skipped.append({
                    **issue.to_dict(),
                    "skip_reason": "vsix repair requires --clean-vsix",
                })
                continue
            repair_fn = _REPAIRS.get(issue.code)
            if repair_fn is None or not issue.auto_fixable:
                skipped.append({**issue.to_dict(), "skip_reason": "no auto-fix"})
                continue
            try:
                result = repair_fn(workspace, issue)
            except Exception as e:  # noqa: BLE001
                result = RepairResult(code=issue.code, success=False,
                                       action_taken="", error=str(e))
            fixed.append(result.to_dict())

    counts = {"errors": 0, "warnings": 0, "info": 0}
    for i in all_issues:
        if i.severity == "error":
            counts["errors"] += 1
        elif i.severity == "warn":
            counts["warnings"] += 1
        else:
            counts["info"] += 1

    return {
        "workspace": workspace.config.name,
        "workspace_root": str(workspace.config.root),
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "issues": [i.to_dict() for i in all_issues],
        "summary": counts,
        "fixed": fixed,
        "skipped": skipped,
    }


# ── helpers ──────────────────────────────────────────────────────────────


def _read_raw_active_feature(workspace_root: Path) -> dict[str, Any] | None:
    """Read .canopy/state/active_feature.json without the stale-path filter
    that ``actions.active_feature.read_active`` applies — we WANT to see
    stale paths so we can report them.
    """
    path = workspace_root / ".canopy" / "state" / "active_feature.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _load_features_raw(workspace_root: Path) -> dict[str, Any]:
    path = workspace_root / ".canopy" / "features.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_features_raw(workspace_root: Path, features: dict[str, Any]) -> None:
    path = workspace_root / ".canopy" / "features.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(features, indent=2))
    tmp.replace(path)


def _read_binary_version(binary_path: str) -> str | None:
    """Run ``<binary> --version`` and return the version token, or None."""
    try:
        out = subprocess.run(
            [binary_path, "--version"],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    parts = out.stdout.strip().split()
    return parts[-1] if parts else None


def _is_older(installed: str, source: str) -> bool:
    """Return True iff ``installed < source`` under loose semver comparison.

    Falls back to lexical comparison for non-numeric components. Equality
    or "newer than source" returns False.
    """
    try:
        a = tuple(int(x) for x in installed.split(".")[:3])
        b = tuple(int(x) for x in source.split(".")[:3])
        return a < b
    except (ValueError, AttributeError):
        return installed != source and installed < source
