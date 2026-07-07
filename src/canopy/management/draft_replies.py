"""``canopy draft_replies`` — auto-draft "Done in <sha>" replies (M9).

For each unresolved PR review comment in the feature's repos, walk the
file's commit history since the comment was anchored. If anything
changed, the comment is "addressed" — render a template-based draft
reply the user can review and post.

This is template-based on purpose. The user reviews the draft before
posting; an LLM-generated reply isn't worth the cost/latency for text
they'll edit anyway. Future ``draft_replies --llm`` is reserved.

Read-only — generates text, never posts. Posting is a separate (future)
``post_replies`` action.
"""
from __future__ import annotations

import re
from typing import Any

from ..git import repo as git
from ..integrations import github as gh
from ..workspace.workspace import Workspace
from ..actions.aliases import resolve_pr_targets


def draft_replies(
    workspace: Workspace,
    alias: str,
    *,
    include_likely_resolved: bool = False,
) -> dict[str, Any]:
    """Per-PR draft-reply set for ``alias``.

    Args:
        workspace: loaded workspace.
        alias: feature name, ``<repo>#<n>``, or PR URL — same surface as
            the existing ``review_comments`` read.
        include_likely_resolved: also draft for the temporal classifier's
            ``likely_resolved`` set (weaker signal — comment looks
            resolved but no commit directly touched the line). Off by
            default; surface as `confidence: low` when on.

    Returns:
        ``{alias, repos: {<repo>: {pr_number, pr_url, addressed: [<draft>],
        unaddressed: [<comment>]}}, addressed_total, unaddressed_total}``.
    """
    from .review_filter import classify_threads

    targets = resolve_pr_targets(workspace, alias)
    repos: dict[str, dict] = {}
    addressed_total = 0
    unaddressed_total = 0

    for t in targets:
        comments, _ = gh.get_review_comments(
            workspace.config.root, t.owner, t.repo_slug, t.pr_number,
        )
        state = workspace.get_repo(t.repo)
        pr = gh.get_pull_request_by_number(
            workspace.config.root, t.owner, t.repo_slug, t.pr_number,
        )
        branch = (pr or {}).get("head_branch") or state.current_branch
        classification = classify_threads(comments, state.abs_path, branch)

        candidate_threads = list(classification.get("actionable_threads") or [])
        if include_likely_resolved:
            candidate_threads += list(classification.get("likely_resolved_threads") or [])

        addressed: list[dict] = []
        unaddressed: list[dict] = []
        for thread in candidate_threads:
            commit_id = thread.get("commit_id")
            path = thread.get("path") or ""
            if not commit_id or not path:
                # Old comment without anchor info — surface as low-confidence
                # unaddressed. Don't pretend we know.
                unaddressed.append({**thread, "reason": "missing_anchor"})
                continue
            history = git.log_for_path(state.abs_path, commit_id, path)
            classified = classify_comment(thread, history)
            if classified["status"] == "addressed":
                draft_text = render_reply(thread, classified["addressing_commits"],
                                          classified["confidence"])
                addressed.append({
                    "comment_id": thread.get("id"),
                    "comment_url": thread.get("url"),
                    "original_comment": {
                        "author": thread.get("author"),
                        "path": path,
                        "line": thread.get("line"),
                        "body": thread.get("body"),
                    },
                    "addressing_commits": classified["addressing_commits"],
                    "draft_reply": draft_text,
                    "confidence": classified["confidence"],
                })
            else:
                unaddressed.append({**thread, "reason": classified.get("reason", "no_commits")})

        addressed_total += len(addressed)
        unaddressed_total += len(unaddressed)
        repos[t.repo] = {
            "pr_number": t.pr_number,
            "pr_url": (pr or {}).get("url", ""),
            "addressed": addressed,
            "unaddressed": unaddressed,
        }

    return {
        "alias": alias,
        "addressed_total": addressed_total,
        "unaddressed_total": unaddressed_total,
        "repos": repos,
    }


# ── Pure helpers (testable in isolation) ────────────────────────────────

def classify_comment(comment: dict, history: list[dict]) -> dict[str, Any]:
    """Decide ``addressed`` vs ``unaddressed`` + a confidence tier.

    Confidence rules:
      - ``high``   single addressing commit, subject mentions a keyword
                   from the comment body
      - ``medium`` single addressing commit, no keyword overlap
      - ``low``    multiple addressing commits, OR likely-resolved
                   classifier promotion (caller signals via comment
                   metadata)
    """
    if not history:
        return {"status": "unaddressed", "addressing_commits": [],
                "confidence": "low", "reason": "no_commits"}

    if len(history) == 1:
        keyword_match = _has_keyword_overlap(comment.get("body") or "",
                                              history[0].get("subject") or "")
        confidence = "high" if keyword_match else "medium"
    else:
        confidence = "low"

    return {
        "status": "addressed",
        "addressing_commits": history,
        "confidence": confidence,
    }


def render_reply(comment: dict, commits: list[dict], confidence: str) -> str:
    """Generate a template-based draft reply.

    Three branches per the plan:
      1. Specific subject match    → "Done — <subject>. (<sha>)"
      2. Single commit fallback    → "Addressed in <sha>: <subject>."
      3. Multiple commits          → "Addressed across <N> commits — <shas>."
    """
    if not commits:
        return ""
    if len(commits) > 1:
        shas = ", ".join(c["sha"][:8] for c in commits)
        return f"Addressed across {len(commits)} commits — {shas}."

    commit = commits[0]
    subject = (commit.get("subject") or "").strip()
    short = (commit.get("sha") or "")[:8]
    if confidence == "high":
        # Keyword match → drop the redundant lead-in.
        return f"Done — {subject}. ({short})"
    return f"Addressed in {short}: {subject}."


# ── Internal ────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


def _has_keyword_overlap(body: str, subject: str) -> bool:
    """True iff body and subject share an identifier-shaped token (≥ 4 chars).

    Cheap proxy for "the commit subject mentions what the comment was
    about." Avoids stop-words by sticking to identifier shape and a
    minimum length threshold.
    """
    body_tokens = {t.lower() for t in _TOKEN_RE.findall(body) if len(t) >= 4}
    subj_tokens = {t.lower() for t in _TOKEN_RE.findall(subject) if len(t) >= 4}
    return bool(body_tokens & subj_tokens)
