"""Slot state — single source of truth for canopy's canonical + warm features.

State file: .canopy/state/slots.json (atomic temp+rename writes).

Schema::

    {
      "version": 1,
      "slot_count": 2,
      "canonical": {feature, activated_at, per_repo_paths},
      "previous_canonical": str | null,
      "slots": {"worktree-1": {feature, occupied_at}, ...},
      "last_touched": {feature: iso, ...},
      "in_flight": {feature_being_promoted, previously_canonical,
                     started_at, per_repo_completed, failed_repo,
                     error_what} | null
    }

Validation on read: a missing canonical path clears ``canonical`` only —
the slots/last_touched maps are independent of the canonical pointer and
must NOT be discarded when the canonical entry is stale. Catastrophic
cases (file missing, JSON unparseable, top-level not a dict) still
return None.

Missing slot dirs → silently drop from the returned state.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..workspace.workspace import Workspace


SLOTS_DIR = ".canopy/worktrees"


@dataclass
class CanonicalEntry:
    feature: str
    activated_at: str
    per_repo_paths: dict[str, str]


@dataclass
class SlotEntry:
    feature: str
    occupied_at: str


@dataclass
class SlotState:
    slot_count: int = 2
    canonical: CanonicalEntry | None = None
    previous_canonical: str | None = None
    slots: dict[str, SlotEntry] = field(default_factory=dict)
    last_touched: dict[str, str] = field(default_factory=dict)
    in_flight: dict | None = None
    bootstrap: dict[str, dict[str, str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "version": 1,
            "slot_count": self.slot_count,
            "previous_canonical": self.previous_canonical,
            "slots": {
                sid: {"feature": e.feature, "occupied_at": e.occupied_at}
                for sid, e in self.slots.items()
            },
            "last_touched": dict(self.last_touched),
            "in_flight": dict(self.in_flight) if self.in_flight else None,
            "bootstrap": {sid: dict(m) for sid, m in self.bootstrap.items()},
        }
        if self.canonical is not None:
            d["canonical"] = {
                "feature": self.canonical.feature,
                "activated_at": self.canonical.activated_at,
                "per_repo_paths": dict(self.canonical.per_repo_paths),
            }
        else:
            d["canonical"] = None
        return d


def _state_path(workspace: Workspace) -> Path:
    return workspace.config.root / ".canopy" / "state" / "slots.json"


def _slots_root(workspace: Workspace) -> Path:
    return workspace.config.root / SLOTS_DIR


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_state(workspace: Workspace) -> SlotState | None:
    path = _state_path(workspace)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    # Canonical staleness check — stale canonical is NOT fatal to the
    # rest of the state. Slots and last_touched are independent of the
    # canonical pointer; clear canonical only and preserve the rest.
    canonical_raw = data.get("canonical")
    canonical: CanonicalEntry | None = None
    if isinstance(canonical_raw, dict) and canonical_raw.get("feature"):
        per_repo = canonical_raw.get("per_repo_paths") or {}
        if not isinstance(per_repo, dict):
            # Malformed canonical block — treat as no canonical, keep rest.
            canonical = None
        else:
            stale = any(not Path(p).exists() for p in per_repo.values())
            if stale:
                canonical = None
            else:
                canonical = CanonicalEntry(
                    feature=canonical_raw["feature"],
                    activated_at=canonical_raw.get("activated_at", ""),
                    per_repo_paths=dict(per_repo),
                )

    slots_raw = data.get("slots") or {}
    slots_root = _slots_root(workspace)
    slots_out: dict[str, SlotEntry] = {}
    for sid, entry in slots_raw.items():
        if not isinstance(entry, dict):
            continue
        # Drop slots whose dir is gone (stale on filesystem)
        if not (slots_root / sid).exists():
            continue
        slots_out[sid] = SlotEntry(
            feature=entry.get("feature", ""),
            occupied_at=entry.get("occupied_at", ""),
        )

    in_flight_raw = data.get("in_flight")
    in_flight = (
        dict(in_flight_raw) if isinstance(in_flight_raw, dict) else None
    )

    return SlotState(
        slot_count=int(data.get("slot_count", 2)),
        canonical=canonical,
        previous_canonical=data.get("previous_canonical"),
        slots=slots_out,
        last_touched={
            str(k): str(v) for k, v in (data.get("last_touched") or {}).items()
        },
        in_flight=in_flight,
        bootstrap={
            str(k): {str(rk): str(rv) for rk, rv in (v or {}).items()}
            for k, v in (data.get("bootstrap") or {}).items()
        },
    )


@contextlib.contextmanager
def _slots_lock(workspace: Workspace):
    """Advisory cross-process lock serializing a slots.json read-modify-write.

    The lost-update race (a detached bootstrap process and the main switch
    both reading, mutating, then writing slots.json) requires holding the
    lock across the WHOLE read->modify->write, not just the write. Callers
    that do such an RMW must wrap the entire sequence in this context.

    ``write_state`` itself does NOT acquire this lock (its unique-tmp +
    atomic replace is already collision-safe on its own), so a locked RMW
    can call ``write_state`` without self-deadlocking on a non-reentrant
    flock. Same pattern as git/hooks.py.
    """
    lock_path = _state_path(workspace).parent / "slots.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def write_state(workspace: Workspace, state: SlotState) -> None:
    path = _state_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique temp in the same dir so concurrent processes never collide on a
    # shared tmp name (the old fixed ".json.tmp" was moved out from under a
    # racing writer -> FileNotFoundError). Atomic rename onto the final path.
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp",
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(state.to_dict(), indent=2))
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise


def slot_worktree_path(workspace: Workspace, slot_id: str, repo: str) -> Path:
    """Filesystem location of a slot's repo subdir."""
    return _slots_root(workspace) / slot_id / repo


def slot_for_feature(workspace: Workspace, feature: str) -> str | None:
    """Return the slot id currently holding ``feature``, or None."""
    state = read_state(workspace)
    if state is None:
        return None
    for sid, entry in state.slots.items():
        if entry.feature == feature:
            return sid
    return None


def feature_for_slot(workspace: Workspace, slot_id: str) -> str | None:
    """Return the feature currently in ``slot_id``, or None."""
    state = read_state(workspace)
    if state is None or slot_id not in state.slots:
        return None
    return state.slots[slot_id].feature


def allocate_slot(state: SlotState) -> str | None:
    """Return the lowest-index free slot id, or None if all are full."""
    occupied = set(state.slots.keys())
    for i in range(1, state.slot_count + 1):
        sid = f"worktree-{i}"
        if sid not in occupied:
            return sid
    return None


def set_bootstrap_status(workspace: Workspace, sid: str, repo: str, status: str) -> None:
    """Record ``status`` (installing|ready|failed) for ``repo`` in slot ``sid``."""
    with _slots_lock(workspace):
        state = read_state(workspace) or SlotState(slot_count=workspace.config.slots)
        state.bootstrap.setdefault(sid, {})[repo] = status
        write_state(workspace, state)


def get_bootstrap_status(workspace: Workspace, sid: str, repo: str) -> str | None:
    """Return the recorded bootstrap status for ``repo`` in slot ``sid``, or None."""
    state = read_state(workspace)
    if state is None:
        return None
    return state.bootstrap.get(sid, {}).get(repo)


def lru_evictee(
    state: SlotState, *, exclude: set[str] | None = None,
) -> str | None:
    """Pick the LRU-coldest occupant feature from the warm slots.

    Returns None when no eligible candidate. Sorting is deterministic:
    (last_touched ASC, feature name ASC) — features with no timestamp
    sort as oldest.
    """
    exclude = exclude or set()
    candidates = [
        e.feature for e in state.slots.values() if e.feature not in exclude
    ]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda f: (state.last_touched.get(f, ""), f),
    )[0]
