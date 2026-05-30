"""feature_resume — switch-aware compound action.

Single command takes an alias and gets the user back in business:
  1. Resolve alias to feature name.
  2. If feature isn't canonical, switch to it (which will bump last_visit once T13 lands).
  3. Compute "since prior anchor" sections (commits, threads, drafts...).
  4. Compute current_state (feature_state, CI, bot rollup, branch position).
  5. Build intent_hints from the deltas + current state.
  6. If no switch happened, bump last_visit at the end.
  7. Return the complete brief.

Refreshes from GitHub/Linear on every call. No caching at this layer.

Single-bump invariant: last_visit moves exactly once per feature_resume call.
  - switch ran  → switch bumps (T13). Resume does NOT bump again.
  - no switch   → resume bumps at the end, after delta is computed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..workspace.workspace import Workspace
from . import last_visit as lv
from . import slots as slots_mod
from .aliases import resolve_feature
from .switch import switch


def feature_resume(workspace: Workspace, alias: str) -> dict[str, Any]:
    """Resolve alias, switch-if-needed, build and return the resume brief."""
    feature = resolve_feature(workspace, alias)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Capture prior anchor BEFORE any switch can move it.
    prior_visit = lv.get_last_visit(workspace, feature)
    prior_iso: str | None = prior_visit["last_visit"] if prior_visit else None

    # 2. Switch-if-needed. Read slot state to decide.
    switch_summary: dict | None = None
    state = slots_mod.read_state(workspace)
    is_canonical = (
        state is not None
        and state.canonical is not None
        and state.canonical.feature == feature
    )
    if not is_canonical:
        switch_summary = switch(workspace, feature)
        # T13 will make switch bump last_visit internally. Until then, the
        # single-bump invariant is: resume does NOT bump when switch ran.

    # 3. Empty containers — T7–T12 expand _populate_since / _populate_current.
    since: dict[str, Any] = {
        "commits": {},
        "threads_new": [],
        "threads_resolved_on_github": [],
        "threads_resolved_by_canopy": [],
        "ci_status_delta": {},
        "draft_replies_pending": 0,
        "historian_excerpt": "",
    }
    current: dict[str, Any] = {
        "feature_state": None,
        "open_thread_count": 0,
        "ci_summary_per_repo": {},
        "bot_unresolved_total": 0,
        "draft_replies_summary": {"addressed_total": 0, "unaddressed_total": 0},
        "branch_position_per_repo": {},
        "linear_issue": None,
        "linear_url": None,
    }

    # 4. Populate sections (prior_iso may be None on first visit).
    if prior_iso is not None:
        since = _populate_since(workspace, feature, prior_iso, since)
    current = _populate_current(workspace, feature, current)

    # 5. Build intent hints from populated shapes.
    intent_hints = _intent_hints(since, current, prior_iso is None)

    # 6. Single-bump: only bump when switch didn't already run.
    if switch_summary is None:
        lv.mark_visited(workspace, feature)

    # 7. Window duration (None on first visit).
    window_hours = _hours_between(prior_iso, now_iso) if prior_iso is not None else None

    # Strip transport-only internal key before returning.
    current.pop("__feature_name__", None)

    return {
        "version": 1,
        "feature": feature,
        "now": now_iso,
        "last_visit": prior_iso,          # the PRIOR anchor, not freshly bumped
        "first_visit": prior_iso is None,
        "window_hours": window_hours,
        "switch_performed": switch_summary is not None,
        "switch_summary": switch_summary,
        "intent_hints": intent_hints,
        "since_last_visit": since,
        "current_state": current,
    }


# ── Section populators (stubs) ────────────────────────────────────────────────
# T7–T12 fill these in. T6 leaves the shapes as-is.

def _populate_since(
    workspace: Workspace,
    feature: str,
    last_visit_iso: str,
    since: dict[str, Any],
) -> dict[str, Any]:
    """T7-T12 fill this. T7 populates commits."""
    since["commits"] = _commits_since(workspace, feature, last_visit_iso)
    return since


def _commits_since(workspace: Workspace, feature: str, since_iso: str) -> dict[str, list]:
    """Populate per-repo commits authored after since_iso on the feature branch.

    Returns {repo_name: [commit dicts]} where each commit has
    {sha, short_sha, at, author, subject}. Per-repo errors (missing branch,
    git failures) silently default to empty list; exceptions don't crash the brief.
    """
    from ..git import repo as git
    from .aliases import repos_for_feature

    out: dict[str, list] = {}
    repos_map = repos_for_feature(workspace, feature)

    for repo_name, branch in repos_map.items():
        try:
            state = workspace.get_repo(repo_name)
            out[repo_name] = git.log_since(state.abs_path, branch, since_iso)
        except Exception:
            # Missing repo in workspace, or git error — default to empty list.
            out[repo_name] = []

    return out


def _populate_current(
    workspace: Workspace,
    feature: str,
    current: dict[str, Any],
) -> dict[str, Any]:
    """T9-T11 fill this. T6 only seeds the internal __feature_name__ key."""
    current["__feature_name__"] = feature
    return current


# ── Intent hints ──────────────────────────────────────────────────────────────

def _intent_hints(
    since: dict[str, Any],
    current: dict[str, Any],
    first_visit: bool,
) -> list[dict]:
    """Build prioritized next-action suggestions from the brief data.

    Hints are derived, not stored — recomputed on every call. Ordering by
    ``priority`` field; the agent typically reads top 3.
    """
    hints: list[dict] = []

    # Address new comments (highest priority — reviewer activity is most
    # actionable thing after returning).
    new_threads = since.get("threads_new") or []
    if new_threads:
        hints.append({
            "kind": "address_comments",
            "summary": f"{len(new_threads)} new PR comment(s) since last visit",
            "suggested_tool": "review_comments",
            "suggested_args": {"alias": current.get("__feature_name__")},
            "priority": 1,
        })

    # Align with default branch (the user's "align with dev" intent path).
    behind_per_repo = {
        r: info.get("behind", 0)
        for r, info in (current.get("branch_position_per_repo") or {}).items()
        if info.get("behind", 0) > 0
    }
    if behind_per_repo:
        worst = max(behind_per_repo.items(), key=lambda kv: kv[1])
        hints.append({
            "kind": "align_with_default",
            "summary": (
                f"behind default by {worst[1]} commits in {worst[0]}"
                + (
                    f" (+ {len(behind_per_repo) - 1} other repos)"
                    if len(behind_per_repo) > 1
                    else ""
                )
            ),
            "suggested_tool": "log",
            "suggested_args": {"repo": worst[0]},
            "priority": 2,
        })

    # Post drafted replies.
    drafts = current.get("draft_replies_summary") or {}
    if drafts.get("addressed_total", 0) > 0:
        hints.append({
            "kind": "post_drafts",
            "summary": f"{drafts['addressed_total']} draft replies ready",
            "suggested_tool": "draft_replies",
            "suggested_args": {"alias": current.get("__feature_name__")},
            "priority": 3,
        })

    # CI failing.
    ci = current.get("ci_summary_per_repo") or {}
    failing = [r for r, status in ci.items() if status == "failing"]
    if failing:
        hints.append({
            "kind": "investigate_ci",
            "summary": f"CI failing in {', '.join(failing)}",
            "suggested_tool": "pr_checks",
            "suggested_args": {"alias": current.get("__feature_name__")},
            "priority": 1,   # ties with comments — both are blockers
        })

    # First-visit special case: hint to read the linear issue.
    if first_visit and current.get("linear_issue"):
        hints.append({
            "kind": "read_issue",
            "summary": f"first visit — read {current['linear_issue']}",
            "suggested_tool": "linear_get_issue",
            "suggested_args": {"alias": current.get("linear_issue")},
            "priority": 1,
        })

    hints.sort(key=lambda h: h["priority"])
    return hints


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hours_between(start_iso: str, end_iso: str) -> float:
    """Return elapsed hours between two ISO-Z timestamps."""
    def _parse(s: str) -> datetime:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    return (_parse(end_iso) - _parse(start_iso)).total_seconds() / 3600.0
