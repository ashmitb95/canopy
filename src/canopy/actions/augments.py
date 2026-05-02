"""Per-workspace augment resolver (M2).

Augments are user-customizable behavioral overrides stored in canopy.toml.
Two-tier: workspace-level defaults under ``[augments]``, per-repo overrides
under ``[[repos]] augments = {...}``. Per-repo wins on key collision.

Consumed by:
- ``integrations/precommit.py`` — ``preflight_cmd`` overrides auto-detection.
- (planned) ``actions/feature_state.py`` — ``review_bots`` filters bot-vs-human
  comment classification (M3 bot-tracking).
- (planned) future ``canopy test`` command — ``test_cmd`` per-repo.

The resolver is intentionally lenient: missing keys return ``None`` / empty
collections rather than raising. Validation that catches typos lives in
``canopy doctor`` (deferred).
"""
from __future__ import annotations

from typing import Any

from ..workspace.config import WorkspaceConfig


def repo_augments(workspace: WorkspaceConfig, repo_name: str) -> dict[str, Any]:
    """Merge workspace ``[augments]`` defaults with the per-repo override.

    Per-repo wins on key collision. If the repo isn't in the workspace, the
    workspace-level defaults are returned unchanged — useful when callers have
    a path but haven't resolved which RepoConfig it belongs to.
    """
    workspace_defaults = workspace.augments or {}
    repo = next((r for r in workspace.repos if r.name == repo_name), None)
    overrides = (repo.augments if repo else None) or {}
    return {**workspace_defaults, **overrides}


def bot_authors(workspace: WorkspaceConfig) -> list[str]:
    """Return the configured bot-author substrings, lowercased.

    Reads ``augments.review_bots`` from workspace defaults. Per-repo overrides
    are deliberately ignored — bot authorship is a workspace-level concern
    (the same CodeRabbit account comments across all repos in a workspace).

    Returns an empty list when unset, in which case callers should fall back
    to whatever default bot detection they had before (typically the
    ``author_type == "Bot"`` substring check on the GitHub PR-comment payload).
    """
    raw = (workspace.augments or {}).get("review_bots", [])
    if not isinstance(raw, list):
        return []
    return [str(s).lower() for s in raw if s]
