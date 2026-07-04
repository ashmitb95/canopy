"""Tests for auto-bootstrap on slot creation (the swappable seam)."""
from __future__ import annotations


def _ws(root):
    from canopy.workspace.workspace import Workspace
    from canopy.workspace.config import load_config
    return Workspace(load_config(root))


def test_fast_steps_run_sync_deps_deferred(workspace_with_slots, monkeypatch):
    from canopy.actions import slot_bootstrap, bootstrap
    fast_steps_seen = []
    monkeypatch.setattr(bootstrap, "bootstrap_repo",
                        lambda *a, **k: fast_steps_seen.append(k.get("steps")) or {"status": "ok"})
    spawned = []
    monkeypatch.setattr(slot_bootstrap, "_spawn_deps_background",
                        lambda ws, feature, sid: spawned.append((feature, sid)))
    ws = workspace_with_slots            # Y warm in worktree-1
    slot_bootstrap.bootstrap_on_slot_create(ws, "Y", "worktree-1")
    assert fast_steps_seen                       # fast steps ran synchronously
    # fast steps must be the env/ide/hooks set, NOT deps
    assert all("deps" not in (s or ()) for s in fast_steps_seen)
    assert spawned == [("Y", "worktree-1")]      # deps deferred to background


def test_deps_worker_records_ready(workspace_with_slots, monkeypatch):
    from canopy.actions import slot_bootstrap, slots as sm, bootstrap
    ws = workspace_with_slots
    monkeypatch.setattr(bootstrap, "bootstrap_repo",
                        lambda *a, **k: {"deps": {"status": "ok"}})
    slot_bootstrap._run_deps_now(ws, "Y", "worktree-1")
    assert sm.get_bootstrap_status(ws, "worktree-1", "repo-a") == "ready"


def test_deps_worker_records_failed(workspace_with_slots, monkeypatch):
    from canopy.actions import slot_bootstrap, slots as sm, bootstrap
    ws = workspace_with_slots
    monkeypatch.setattr(bootstrap, "bootstrap_repo",
                        lambda *a, **k: {"deps": {"status": "failed", "exit_code": 1}})
    slot_bootstrap._run_deps_now(ws, "Y", "worktree-1")
    assert sm.get_bootstrap_status(ws, "worktree-1", "repo-a") == "failed"


def test_bootstrap_never_raises_on_slot_create(workspace_with_slots, monkeypatch):
    from canopy.actions import slot_bootstrap, bootstrap
    monkeypatch.setattr(bootstrap, "bootstrap_repo",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(slot_bootstrap, "_spawn_deps_background", lambda *a: None)
    # must swallow the fast-step error, not raise
    slot_bootstrap.bootstrap_on_slot_create(workspace_with_slots, "Y", "worktree-1")
