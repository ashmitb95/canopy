"""Thread resolution log — persistent record of threads resolved via canopy.

State file: .canopy/state/thread_resolutions.json (atomic temp+rename writes).

Schema::

    {
      "PRRT_abc": {
        "resolved_by_canopy_at": "2026-05-29T12:00:00Z",
        "feature": "auth-flow",
        "via_command": "resolve" | "commit_address" | "reply_resolve",
        "via_commit_sha": "abc1234" | null
      }
    }

Used by the resume brief to attribute "resolved by canopy" vs "resolved on
GitHub directly" — only canopy-initiated resolutions appear here.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _state_path(workspace_root: Path) -> Path:
    return workspace_root / ".canopy" / "state" / "thread_resolutions.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(workspace_root: Path) -> dict:
    """Return the full log dict. Missing file returns an empty dict."""
    path = _state_path(workspace_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def record(
    workspace_root: Path,
    *,
    thread_id: str,
    feature: str,
    via_command: str,
    via_commit_sha: str | None = None,
) -> dict:
    """Append or overwrite a thread resolution entry. Returns the entry written.

    Atomic write: mkstemp in same dir → write → os.replace.
    """
    log = load(workspace_root)
    entry = {
        "resolved_by_canopy_at": _now_iso(),
        "feature": feature,
        "via_command": via_command,
        "via_commit_sha": via_commit_sha,
    }
    log[thread_id] = entry

    path = _state_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return entry


def filter_since(workspace_root: Path, since_iso: str) -> dict:
    """Return only entries with ``resolved_by_canopy_at`` >= ``since_iso``.

    Comparison is lexicographic on the ISO 8601 Z strings (safe because they
    are always produced in the same zero-padded format by ``_now_iso``).
    """
    log = load(workspace_root)
    return {
        tid: entry
        for tid, entry in log.items()
        if isinstance(entry, dict)
        and entry.get("resolved_by_canopy_at", "") >= since_iso
    }
