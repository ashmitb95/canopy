"""Active-feature context state.

Single-file state at ``.canopy/state/active_feature.json`` records which
feature the user has declared as the focus. One writer (``canopy switch``);
many readers (``feature_state``, ``canopy_run``, IDE openers, dashboard).

Missing/empty file = no active feature = use main repos for everything
(default behavior). Writing is the only way to opt in.

Schema::

    {
      "feature":          "doc-3029",
      "activated_at":     "2026-04-26T17:34:21Z",
      "previous_feature": "doc-3010" | null,
      "per_repo_paths":   {"api": "/abs/...", "ui": "/abs/..."}
    }

Path lookup tells you the mode by location: paths under
``.canopy/worktrees/`` are worktrees; everything else is main-tree.

Validation happens on **read**, not write — if any per-repo path no
longer exists on disk, treat the entire entry as stale (callers fall
back to "no active feature").
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..workspace.workspace import Workspace


def _state_path(workspace: Workspace) -> Path:
    return workspace.config.root / ".canopy" / "state" / "active_feature.json"


@dataclass
class ActiveFeature:
    feature: str
    activated_at: str
    per_repo_paths: dict[str, str]
    previous_feature: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "activated_at": self.activated_at,
            "previous_feature": self.previous_feature,
            "per_repo_paths": dict(self.per_repo_paths),
        }


def read_active(workspace: Workspace) -> ActiveFeature | None:
    """Return the recorded active feature, or None if none is set or stale.

    Stale means: file present but at least one per-repo path doesn't exist
    on disk anymore (worktree was removed, repo was deleted). On stale,
    returns None so callers fall back to default behavior.
    """
    path = _state_path(workspace)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("feature"):
        return None

    per_repo_paths = data.get("per_repo_paths") or {}
    if not isinstance(per_repo_paths, dict):
        return None

    # Validate paths still exist; if any are missing, treat as stale.
    for p in per_repo_paths.values():
        if not Path(p).exists():
            return None

    return ActiveFeature(
        feature=data["feature"],
        activated_at=data.get("activated_at", ""),
        per_repo_paths=dict(per_repo_paths),
        previous_feature=data.get("previous_feature"),
    )


def write_active(
    workspace: Workspace,
    feature: str,
    per_repo_paths: dict[str, str],
) -> ActiveFeature:
    """Persist the active feature. Atomic via temp + rename.

    Bumps the existing entry's feature into ``previous_feature`` so the
    user can ``canopy switch -`` (future) to swap back.
    """
    path = _state_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)

    previous = read_active(workspace)
    previous_feature = previous.feature if previous and previous.feature != feature else (
        previous.previous_feature if previous else None
    )

    entry = ActiveFeature(
        feature=feature,
        activated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        per_repo_paths={k: str(v) for k, v in per_repo_paths.items()},
        previous_feature=previous_feature,
    )

    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entry.to_dict(), indent=2))
    tmp.replace(path)
    return entry


def clear_active(
    workspace: Workspace, *, only_if_feature: str | None = None,
) -> bool:
    """Remove the active-feature state file.

    With ``only_if_feature``, only clears when the recorded feature
    matches (used by ``canopy done <feature>`` to avoid clobbering
    unrelated active state). Returns True if a file was removed.
    """
    path = _state_path(workspace)
    if not path.exists():
        return False
    if only_if_feature is not None:
        current = read_active(workspace)
        if current is None or current.feature != only_if_feature:
            return False
    path.unlink()
    return True


def is_active(workspace: Workspace, feature: str) -> bool:
    """Check whether ``feature`` is the recorded active feature."""
    current = read_active(workspace)
    return current is not None and current.feature == feature


def paths_for_feature(
    workspace: Workspace, feature: str,
) -> dict[str, str] | None:
    """Return the recorded per-repo paths for ``feature`` if it is active.

    Returns None if ``feature`` is not the active feature. Callers should
    fall back to ``coordinator.resolve_paths(feature)`` (which considers
    worktrees + current branches) when this returns None.
    """
    current = read_active(workspace)
    if current is None or current.feature != feature:
        return None
    return dict(current.per_repo_paths)
