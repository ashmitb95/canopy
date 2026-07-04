"""The intended-focus pointer (.canopy/state/active.json).

Set by ``start`` to record which feature the session intends to work on
BEFORE any repo has a branch (lazy growth). Decoupled from
``slots.canonical`` on purpose: canonical means "checked out and gated"
and is set only at the first ``join``; ``active`` means "this is what I'm
focused on" and can precede any checkout. ``context`` reports
``active = slots.canonical.feature or active.json``.
"""
from __future__ import annotations

import json
import os

from ..workspace.workspace import Workspace


def _path(workspace: Workspace):
    return workspace.config.root / ".canopy" / "state" / "active.json"


def get_active(workspace: Workspace) -> str | None:
    p = _path(workspace)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        return data.get("active_feature") if isinstance(data, dict) else None
    except (ValueError, OSError):
        return None


def set_active(workspace: Workspace, feature: str) -> None:
    p = _path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps({"active_feature": feature}, indent=2) + "\n")
    os.replace(tmp, p)


def clear_active(workspace: Workspace) -> None:
    p = _path(workspace)
    if p.exists():
        p.unlink()
