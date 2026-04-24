"""Directory-safe shell exec for agents.

Eliminates the agent's ``cd <wrong-dir> && command`` mistake class by
making the agent pass ``(repo, command, feature?)`` semantically.
canopy resolves the working directory itself.

Trust boundary: the command string is shell-executed without
sanitization. The agent IS the trust boundary. The point of this tool
is path correctness, not command sandboxing.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from ..actions.errors import BlockerError, FailedError, FixAction
from ..workspace.workspace import Workspace


def run_in_repo(
    workspace: Workspace,
    repo: str,
    command: str,
    feature: str | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Run a shell command in a canopy-managed repo or worktree.

    Resolution: if ``feature`` is set and a worktree exists for
    ``(feature, repo)``, the command runs in the worktree. Otherwise it
    runs in the repo's main path.

    Returns ``{exit_code, stdout, stderr, cwd, duration_ms}``.

    Raises:
        BlockerError: if ``repo`` is unknown to the workspace, or
            ``feature`` is set but doesn't exist.
        FailedError: if the command times out.
    """
    cwd = _resolve_cwd(workspace, repo, feature)

    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as e:
        elapsed_ms = (time.monotonic() - started) * 1000
        raise FailedError(
            code="timeout",
            what=f"command exceeded {timeout_seconds}s timeout",
            actual={"cwd": str(cwd), "command": command},
            details={
                "duration_ms": int(elapsed_ms),
                "timeout_seconds": timeout_seconds,
                "stdout": e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or ""),
                "stderr": e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or ""),
            },
        )
    elapsed_ms = (time.monotonic() - started) * 1000

    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "cwd": str(cwd),
        "duration_ms": int(elapsed_ms),
    }


def _resolve_cwd(workspace: Workspace, repo: str, feature: str | None) -> Path:
    repo_names = {r.config.name for r in workspace.repos}
    if repo not in repo_names:
        raise BlockerError(
            code="unknown_repo",
            what=f"no repo named '{repo}' in workspace",
            expected={"available_repos": sorted(repo_names)},
            actual={"repo": repo},
            fix_actions=[
                FixAction(action="status", args={}, safe=True,
                          preview="canopy status lists configured repos"),
            ],
        )

    if feature is None:
        return workspace.get_repo(repo).abs_path

    from ..features.coordinator import FeatureCoordinator
    coordinator = FeatureCoordinator(workspace)
    try:
        resolved = coordinator._resolve_name(feature)
    except ValueError as e:
        raise BlockerError(
            code="ambiguous_feature",
            what=str(e),
            details={"feature": feature},
        )

    features = coordinator._load_features()
    if resolved not in features:
        raise BlockerError(
            code="unknown_feature",
            what=f"no feature lane named '{feature}'",
            actual={"feature": feature},
            details={"resolved": resolved},
        )

    paths = coordinator.resolve_paths(resolved)
    if repo in paths:
        return Path(paths[repo])

    # Repo isn't in the feature lane — fall back to the repo's main path
    # rather than failing. Caller likely just wants the directory; if the
    # repo isn't part of the feature, the worktree route doesn't apply.
    return workspace.get_repo(repo).abs_path
