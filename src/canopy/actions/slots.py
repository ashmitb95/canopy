"""Slot state — single source of truth for canopy's canonical + warm features.

State file: .canopy/state/slots.json (atomic temp+rename writes).

Schema::

    {
      "version": 1,
      "slot_count": 2,
      "canonical": {feature, activated_at, per_repo_paths},
      "previous_canonical": str | null,
      "slots": {"worktree-1": {feature, occupied_at}, ...},
      "last_touched": {feature: iso, ...}
    }

Validation on read: missing canonical paths → return None (stale).
Missing slot dirs → silently drop from the returned state.
"""
from __future__ import annotations

import json
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

    # Canonical staleness check
    canonical_raw = data.get("canonical")
    canonical: CanonicalEntry | None = None
    if isinstance(canonical_raw, dict) and canonical_raw.get("feature"):
        per_repo = canonical_raw.get("per_repo_paths") or {}
        if not isinstance(per_repo, dict):
            return None
        for p in per_repo.values():
            if not Path(p).exists():
                return None  # stale
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

    return SlotState(
        slot_count=int(data.get("slot_count", 2)),
        canonical=canonical,
        previous_canonical=data.get("previous_canonical"),
        slots=slots_out,
        last_touched={
            str(k): str(v) for k, v in (data.get("last_touched") or {}).items()
        },
    )


def write_state(workspace: Workspace, state: SlotState) -> None:
    path = _state_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state.to_dict(), indent=2))
    tmp.replace(path)


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
