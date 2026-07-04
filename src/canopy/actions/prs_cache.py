"""Offline fallback cache for the remote PR overlay (.canopy/state/prs.json).

NOT the source of truth — the source is a live GitHub fetch. This cache is
served only when a live fetch is impossible (offline/rate-limited) and to
the dashboard, always flagged with ``fetched_at`` so staleness is visible.
Feature-centric shape (matches triage._group_by_feature output).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from ..workspace.workspace import Workspace


def _path(workspace: Workspace):
    return workspace.config.root / ".canopy" / "state" / "prs.json"


def read(workspace: Workspace) -> dict[str, Any] | None:
    """Return ``{fetched_at, features}`` or None if absent/corrupt."""
    p = _path(workspace)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        if isinstance(data, dict) and "features" in data:
            return data
    except (ValueError, OSError):
        pass
    return None


def write(workspace: Workspace, features: dict[str, Any]) -> None:
    """Persist the feature→repo→PR map with a fresh timestamp (atomic)."""
    p = _path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "features": features,
    }
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(tmp, p)
