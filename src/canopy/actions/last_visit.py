"""Per-feature last-visit anchor for the feature-resume brief.

State file: .canopy/state/visits.json
Schema: {"<feature>": {"last_visit": "ISO", "previous_visit": "ISO|null"}}

Bumped by switch (T13). Read by resume (T6+). Atomic temp+replace writes.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..workspace.workspace import Workspace


_STATE = ".canopy/state/visits.json"


def _path(workspace: Workspace) -> Path:
    return workspace.config.root / _STATE


def _load(workspace: Workspace) -> dict[str, dict[str, Any]]:
    p = _path(workspace)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save(workspace: Workspace, data: dict) -> None:
    p = _path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{p.name}.", suffix=".tmp", dir=str(p.parent)
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def get_last_visit(workspace: Workspace, feature: str) -> dict[str, Any] | None:
    """Return the visit entry for a feature, or None if not visited."""
    return _load(workspace).get(feature)


def mark_visited(workspace: Workspace, feature: str) -> str:
    """Bump last_visit to now; carry old value to previous_visit.

    Returns the new timestamp (ISO 8601 Z format).
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = _load(workspace)
    prev = data.get(feature, {}).get("last_visit")
    data[feature] = {"last_visit": now, "previous_visit": prev}
    _save(workspace, data)
    return now


def reset_anchor(workspace: Workspace, feature: str) -> bool:
    """Drop the feature entry from the visits log.

    Returns True if the entry existed and was removed, False otherwise.
    """
    data = _load(workspace)
    if feature not in data:
        return False
    del data[feature]
    _save(workspace, data)
    return True
