"""Persist preflight results so feature_state can tell IN_PROGRESS from READY_TO_COMMIT.

State file: ``<workspace_root>/.canopy/state/preflight.json``

Schema (one entry per feature)::

    {
      "<feature_name>": {
        "passed": bool,
        "ran_at": "ISO 8601",
        "head_sha_per_repo": {"<repo>": "sha"},
        "all_passed": bool,
        "summary": "..."
      }
    }

A preflight result is "fresh" for a repo when the recorded HEAD sha
equals the repo's current HEAD. If any repo's HEAD has moved since the
recorded run, the preflight is stale (state machine treats it as
"not run").
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..git import repo as git
from ..workspace.workspace import Workspace


def _state_file(workspace_root: Path) -> Path:
    return workspace_root / ".canopy" / "state" / "preflight.json"


def read_state(workspace_root: Path) -> dict[str, Any]:
    """Return ``{<feature>: {passed, ran_at, head_sha_per_repo, ...}}``."""
    path = _state_file(workspace_root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def record_result(
    workspace_root: Path,
    feature: str,
    *,
    passed: bool,
    head_sha_per_repo: dict[str, str],
    summary: str = "",
) -> None:
    """Persist a preflight outcome for a feature."""
    path = _state_file(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = read_state(workspace_root)
    state[feature] = {
        "passed": passed,
        "ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head_sha_per_repo": dict(head_sha_per_repo),
        "summary": summary,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)


def is_fresh(
    workspace: Workspace,
    feature: str,
    repo_branches: dict[str, str],
) -> tuple[bool, dict[str, Any] | None]:
    """True if the recorded preflight is still valid for the current HEAD per repo.

    Returns ``(fresh, entry)``:
      - fresh=True only when the entry exists AND each repo's recorded
        sha equals current HEAD sha for the expected branch.
      - entry is the recorded dict (None if no entry).
    """
    state = read_state(workspace.config.root)
    entry = state.get(feature)
    if not entry:
        return False, None

    recorded = entry.get("head_sha_per_repo") or {}
    for repo_name, branch in repo_branches.items():
        try:
            state_obj = workspace.get_repo(repo_name)
        except KeyError:
            return False, entry
        current = git.sha_of(state_obj.abs_path, branch)
        if not current or recorded.get(repo_name) != current:
            return False, entry
    return True, entry
