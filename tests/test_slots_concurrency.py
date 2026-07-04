"""Concurrency: parallel RMW of slots.json must not lose updates or crash."""
from __future__ import annotations
import multiprocessing as mp


def _ws(root):
    from pathlib import Path
    from canopy.workspace.workspace import Workspace
    from canopy.workspace.config import load_config
    return Workspace(load_config(Path(root)))


def _worker(root, sid, repo, n):
    from canopy.actions import slots as sm
    ws = _ws(root)
    for i in range(n):
        sm.set_bootstrap_status(ws, sid, repo, "installing" if i % 2 else "ready")


def test_concurrent_bootstrap_status_writes_preserve_canonical(canopy_toml_for_workspace):
    from canopy.actions import slots as sm
    root = canopy_toml_for_workspace
    ws = _ws(root)
    # seed a canonical that must survive concurrent bootstrap-status writers
    sm.write_state(ws, sm.SlotState(
        slot_count=2,
        canonical=sm.CanonicalEntry(feature="X", activated_at=sm.now_iso(),
                                    per_repo_paths={"repo-a": str(root / "repo-a")}),
    ))
    procs = [mp.Process(target=_worker, args=(str(root), f"worktree-{k}", "repo-a", 25))
             for k in range(1, 5)]
    for p in procs: p.start()
    for p in procs: p.join()
    state = sm.read_state(ws)
    assert state is not None
    assert state.canonical is not None and state.canonical.feature == "X"  # NOT clobbered
    # every worker's slot recorded a status (no lost slots)
    for k in range(1, 5):
        assert f"worktree-{k}" in state.bootstrap
