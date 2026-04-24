"""Temporal classification of PR review threads.

Compares each review comment's ``created_at`` to the branch's latest
commit timestamp and to commits that touched the comment's file. Splits
threads into actionable / likely_resolved / resolved so the agent's
context budget goes to comprehension, not to figuring out which feedback
is current.

Validated by the user against four real PRs (DOC-3008, DOC-3010,
DOC-3029, DOC-2827) — every comment classified correctly using only
timestamp + path matching, no NLP. Bot threads are NOT filtered by
author here: a ``claude[bot]`` thread may carry the only actionable
feedback, and the temporal heuristic handles staleness regardless.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..git import repo as git


def classify_threads(
    comments: list[dict],
    repo_path: Path,
    branch: str,
) -> dict[str, Any]:
    """Bucket review comments into actionable / likely_resolved.

    Algorithm (per the research doc):
        if comment.created_at > branch.latest_commit_at:
            ACTIONABLE  — posted after latest commit, not addressed yet
        elif any commit on branch after the comment touched the comment's path:
            LIKELY_RESOLVED  — file was modified after the comment
        else:
            ACTIONABLE  — old comment, file untouched since

    Args:
        comments: normalized comments from ``integrations.github.get_review_comments``.
            Each dict must have ``path``, ``created_at`` (ISO 8601), plus
            anything else the consumer wants. Comments with ``state == 'RESOLVED'``
            are excluded upstream by ``_normalize_comments``.
        repo_path: local repo path for git history lookups.
        branch: branch name to use as the comparison ref.

    Returns:
        ``{actionable_threads, likely_resolved_threads, resolved_thread_count,
           latest_commit_at}``.

        ``actionable_threads`` carry the full comment dict, plus
        ``classification_reason`` describing why they're flagged.
        ``likely_resolved_threads`` carry a slim summary: ``path``, ``author``,
        ``created_at``, plus ``addressed_by_commit`` (sha) and ``reason``.
    """
    latest_commit_at = git.commit_iso_date(repo_path, branch)
    latest_dt = _parse_iso(latest_commit_at)

    actionable: list[dict] = []
    likely_resolved: list[dict] = []

    for c in comments:
        created_at = c.get("created_at", "")
        created_dt = _parse_iso(created_at)
        path = c.get("path", "")

        if created_dt is None or latest_dt is None:
            # Missing timestamps — keep as actionable to be safe.
            actionable.append({**c, "classification_reason": "missing_timestamp"})
            continue

        if created_dt > latest_dt:
            actionable.append({
                **c,
                "classification_reason": "posted_after_latest_commit",
            })
            continue

        if not path:
            # Comment with no file path → can't temporally check; assume actionable.
            actionable.append({**c, "classification_reason": "no_path_to_check"})
            continue

        post_comment_commits = git.commits_touching_path(
            repo_path, branch, path, since=created_at,
        )
        if post_comment_commits:
            most_recent = post_comment_commits[0]
            likely_resolved.append({
                "path": path,
                "author": c.get("author", ""),
                "created_at": created_at,
                "body_excerpt": _excerpt(c.get("body", "")),
                "url": c.get("url", ""),
                "addressed_by_commit": most_recent["sha"],
                "addressed_by_short_sha": most_recent["short_sha"],
                "addressed_at": most_recent["committed_at"],
                "reason": (
                    f"commit {most_recent['short_sha']} touched this file "
                    f"after the comment"
                ),
            })
        else:
            actionable.append({
                **c,
                "classification_reason": "no_post_comment_commit_touched_file",
            })

    return {
        "actionable_threads": actionable,
        "likely_resolved_threads": likely_resolved,
        # ``resolved_thread_count`` reflects threads excluded upstream by
        # GitHub's isResolved field (not visible to us at this layer). The
        # caller may set it; default 0.
        "resolved_thread_count": 0,
        "latest_commit_at": latest_commit_at,
    }


def _parse_iso(s: str) -> datetime | None:
    """Parse an ISO 8601 timestamp; return None on failure."""
    if not s:
        return None
    # Accept both ``...Z`` and ``...+HH:MM`` forms.
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _excerpt(body: str, max_len: int = 120) -> str:
    body = " ".join(body.split())  # collapse whitespace
    if len(body) <= max_len:
        return body
    return body[: max_len - 1] + "…"
