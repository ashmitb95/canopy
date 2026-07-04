"""Auto-bootstrap on slot creation — the PROVISIONAL timing seam.

Fast steps (env, ide, hooks) run synchronously so the worktree is
immediately usable for edit/commit/push. Deps install runs in the
background with status recorded in slots.json; failure is a loud state,
not a silent hole. Swap the strategy here without touching switch.
"""
from __future__ import annotations

import os
import subprocess
import sys

from ..workspace.workspace import Workspace

_FAST_STEPS = ("env", "ide", "hooks")


def bootstrap_on_slot_create(workspace: Workspace, feature: str, sid: str) -> None:
    from . import bootstrap, slots as sm
    from .aliases import repos_for_feature
    for repo_name in (repos_for_feature(workspace, feature) or {}):
        wt = sm.slot_worktree_path(workspace, sid, repo_name)
        if not (wt / ".git").exists():
            continue
        try:
            bootstrap.bootstrap_repo(workspace, feature, repo_name, wt, steps=_FAST_STEPS)
        except Exception:
            pass  # fast-step failure is non-fatal; deps status carries the load
        try:
            sm.set_bootstrap_status(workspace, sid, repo_name, "installing")
        except Exception:
            pass
    try:
        _spawn_deps_background(workspace, feature, sid)
    except Exception:
        pass


def _spawn_deps_background(workspace: Workspace, feature: str, sid: str) -> None:
    """Detach a `canopy worktree bootstrap --deps` for this slot."""
    if os.environ.get("CANOPY_NO_BG_BOOTSTRAP"):
        return
    subprocess.Popen(
        [sys.executable, "-m", "canopy.cli.main", "worktree", "bootstrap",
         "--deps", feature, "--_slot", sid],
        cwd=str(workspace.config.root),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _run_deps_now(workspace: Workspace, feature: str, sid: str) -> None:
    """The body the detached process runs: install deps, record status."""
    from . import bootstrap, slots as sm
    from .aliases import repos_for_feature
    for repo_name in (repos_for_feature(workspace, feature) or {}):
        wt = sm.slot_worktree_path(workspace, sid, repo_name)
        if not (wt / ".git").exists():
            continue
        try:
            res = bootstrap.bootstrap_repo(workspace, feature, repo_name, wt, steps=("deps",))
            ok = res.get("deps", {}).get("status") in ("ok", "skipped")
        except Exception:
            ok = False
        sm.set_bootstrap_status(workspace, sid, repo_name, "ready" if ok else "failed")
