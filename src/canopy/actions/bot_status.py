"""Per-feature bot-comment rollup (M3).

Composes the live actionable bot threads (from ``feature_state._per_repo_facts``)
with the persistent resolution log (``bot_resolutions.json``) into a single
``{feature, repos: {<repo>: {pr_number, total, resolved, unresolved, threads}},
all_resolved}`` shape that the CLI / MCP / dashboard share.

A "bot comment" here means an actionable thread whose author was classified as
a bot per ``feature_state._is_bot_comment`` (GitHub-typed bot AND, when
``review_bots`` is set in canopy.toml augments, substring-matching the
configured list).
"""
from __future__ import annotations

from typing import Any

from . import active_feature as af
from .aliases import repos_for_feature, resolve_feature
from .bot_resolutions import resolutions_for_feature
from .errors import BlockerError, FixAction
from .feature_state import _per_repo_facts, resolve_repo_paths
from ..workspace.workspace import Workspace


def bot_comments_status(
    workspace: Workspace,
    feature: str | None = None,
) -> dict[str, Any]:
    """Build the rollup. Falls back to the canonical feature when ``feature`` is None."""
    feature_name = _resolve_feature_name(workspace, feature)
    repo_branches = repos_for_feature(workspace, feature_name)
    if not repo_branches:
        raise BlockerError(
            code="empty_feature",
            what=f"feature '{feature_name}' has no associated repos",
        )

    repo_paths, _has_wt = resolve_repo_paths(workspace, feature_name, repo_branches)
    facts = _per_repo_facts(workspace, feature_name, repo_branches, repo_paths)
    resolutions = resolutions_for_feature(workspace.config.root, feature_name)

    repos_out: dict[str, dict[str, Any]] = {}
    all_resolved = True
    any_bot_comment_seen = False

    for repo_name, repo_facts in facts.items():
        pr = repo_facts.get("pr") or {}
        bot_threads = repo_facts.get("actionable_bot_threads", [])
        # Resolution entries scoped to this repo (so we report a sensible
        # `resolved` count per PR even when other repos have their own).
        repo_resolutions = {
            cid: entry
            for cid, entry in resolutions.items()
            if entry.get("repo") == repo_name
        }
        unresolved_threads = [
            _thread_summary(t, resolved=False, resolution=None) for t in bot_threads
        ]
        resolved_threads = [
            _resolved_summary(cid, entry)
            for cid, entry in sorted(repo_resolutions.items())
        ]
        threads = resolved_threads + unresolved_threads

        total = len(threads)
        if total > 0:
            any_bot_comment_seen = True
        if unresolved_threads:
            all_resolved = False

        repos_out[repo_name] = {
            "pr_number": pr.get("number"),
            "pr_url": pr.get("url", ""),
            "total": total,
            "resolved": len(resolved_threads),
            "unresolved": len(unresolved_threads),
            "threads": threads,
        }

    return {
        "feature": feature_name,
        "repos": repos_out,
        "all_resolved": all_resolved if any_bot_comment_seen else True,
        "any_bot_comments": any_bot_comment_seen,
    }


def _resolve_feature_name(workspace: Workspace, feature: str | None) -> str:
    if feature:
        return resolve_feature(workspace, feature)
    active = af.read_active(workspace)
    if active is None:
        raise BlockerError(
            code="no_canonical_feature",
            what="no active feature; pass --feature or run `canopy switch <name>` first",
            fix_actions=[
                FixAction(action="switch", args={}, safe=False,
                          preview="canopy switch <feature> sets the canonical slot"),
            ],
        )
    return active.feature


def _thread_summary(
    thread: dict, *, resolved: bool, resolution: dict | None,
) -> dict[str, Any]:
    out = {
        "id": thread.get("id"),
        "author": thread.get("author", ""),
        "path": thread.get("path", ""),
        "line": thread.get("line", 0),
        "url": thread.get("url", ""),
        "body_preview": (thread.get("body") or "").splitlines()[0][:120] if thread.get("body") else "",
        "resolved": resolved,
    }
    if resolution:
        out["resolved_by_commit"] = resolution.get("commit_sha", "")
        out["addressed_at"] = resolution.get("addressed_at", "")
    return out


def _resolved_summary(comment_id: str, entry: dict) -> dict[str, Any]:
    return {
        "id": comment_id,
        "author": "",
        "path": "",
        "line": 0,
        "url": entry.get("comment_url", ""),
        "body_preview": entry.get("comment_title", ""),
        "resolved": True,
        "resolved_by_commit": entry.get("commit_sha", ""),
        "addressed_at": entry.get("addressed_at", ""),
    }
