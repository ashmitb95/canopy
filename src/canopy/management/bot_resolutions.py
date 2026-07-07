"""Persistent log of bot review-comments addressed by canopy commits (M3).

State file: ``<workspace_root>/.canopy/state/bot_resolutions.json``

Schema (an append-only mapping; each key is a stringified GitHub comment ID)::

    {
      "123456": {
        "feature": "sin-6-cache-stats",
        "repo": "test-api",
        "commit_sha": "abc123de",
        "addressed_at": "2026-05-02T17:30:00Z",
        "comment_title": "rename hit_rate to cache_hit_rate",
        "comment_url": "https://github.com/owner/repo/pull/142#discussion_r123456"
      }
    }

Written by ``commit --address``; read by the ``bot_comments_status`` rollup
and by ``feature_state`` to subtract resolved bot comments from the
actionable count surfaced in the agent dashboard.

Writes are atomic (temp file + ``os.replace``) so concurrent record calls
across worktrees don't corrupt the file.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_STATE_DIR = ".canopy/state"
_STATE_FILE = "bot_resolutions.json"


def _state_path(workspace_root: Path) -> Path:
    return workspace_root / _STATE_DIR / _STATE_FILE


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_resolutions(workspace_root: Path) -> dict[str, dict[str, Any]]:
    """Read the resolution log. Returns an empty dict when no file exists."""
    path = _state_path(workspace_root)
    if not path.exists():
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def is_resolved(workspace_root: Path, comment_id: str | int) -> bool:
    """True iff this comment id is in the resolution log."""
    return str(comment_id) in load_resolutions(workspace_root)


def resolutions_for_feature(
    workspace_root: Path, feature: str,
) -> dict[str, dict[str, Any]]:
    """Filter the log to entries tagged with this feature name."""
    return {
        cid: entry
        for cid, entry in load_resolutions(workspace_root).items()
        if entry.get("feature") == feature
    }


def record_resolution(
    workspace_root: Path,
    *,
    comment_id: str | int,
    feature: str,
    repo: str,
    commit_sha: str,
    comment_title: str,
    comment_url: str = "",
    addressed_at: str | None = None,
) -> dict[str, Any]:
    """Append a resolution entry. Last-write-wins on duplicate comment_id.

    Returns the entry written. Creates the state directory if missing.
    """
    path = _state_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = load_resolutions(workspace_root)
    entry = {
        "feature": feature,
        "repo": repo,
        "commit_sha": commit_sha,
        "addressed_at": addressed_at or _now_iso(),
        "comment_title": comment_title,
        "comment_url": comment_url,
    }
    existing[str(comment_id)] = entry
    _atomic_write(path, existing)
    return entry


def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON atomically: tmp file in same dir, then os.replace."""
    fd, tmp = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
