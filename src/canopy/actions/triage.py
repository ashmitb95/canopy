"""triage(author) — the agent's daily entry point.

Enumerates open PRs across all configured repos, groups by feature lane
(explicit from features.json or implicit by shared branch name), runs
each group's review comments through the temporal classifier, and tags
each feature with a priority tier:

    changes_requested  > review_required_with_bot_comments
                       > review_required
                       > approved

Designed for the user's morning workflow: ``canopy triage`` returns a
single ordered list of "what needs my attention right now".
"""
from __future__ import annotations

from typing import Any

from ..integrations import github as gh
from ..workspace.workspace import Workspace
from . import slots as slots_mod
from .aliases import _resolve_owner_slug
from .pr_map import _fetch_open_prs, _group_by_feature, _select_repos
from .review_filter import classify_threads


_PRIORITY_ORDER = {
    "changes_requested": 0,
    "review_required_with_bot_comments": 1,
    "review_required": 2,
    "approved": 3,
    "unknown": 4,
}


def triage(
    workspace: Workspace,
    author: str = "@me",
    repos: list[str] | None = None,
) -> dict[str, Any]:
    """Return prioritized list of features needing user attention.

    Args:
        workspace: loaded workspace.
        author: GitHub username/handle to filter PRs by; ``@me`` is
            the gh CLI shorthand for the authenticated user.
        repos: subset of canopy repos to scan (default: all).

    Returns:
        ``{author, canonical_feature, features: [{feature, linear_issue,
        linear_url, linear_title, priority, is_canonical, physical_state,
        repos: {<r>: {pr_number, pr_url, pr_title, branch, review_decision,
        actionable_count, likely_resolved_count, has_actionable_bot_thread,
        physical_state, path}}}]}`` ordered most-urgent first.

        ``physical_state`` per feature is ``canonical | warm | cold | none``
        (none = no worktree, branch may not even be checked out anywhere).
        Per-repo ``physical_state`` + ``path`` lets the agent decide
        whether to switch first or just `canopy_run` against the recorded
        path.

    Raises:
        BlockerError: if no GitHub transport is available, or if a
            requested repo is unknown.
    """
    target_repos = _select_repos(workspace, repos)
    prs_by_repo = _fetch_open_prs(workspace, target_repos, author)
    feature_groups = _group_by_feature(workspace, prs_by_repo)
    state = slots_mod.read_state(workspace)
    canonical_feature = state.canonical.feature if state and state.canonical else None
    enriched = [_enrich(workspace, g, canonical_feature) for g in feature_groups]
    enriched.sort(key=lambda f: _PRIORITY_ORDER.get(f["priority"], 99))
    return {
        "author": author,
        "canonical_feature": canonical_feature,
        "features": enriched,
    }


def _enrich(
    workspace: Workspace, group: dict, canonical_feature: str | None,
) -> dict:
    feature_name = group["feature"]
    is_canonical = canonical_feature == feature_name
    per_repo: dict[str, dict] = {}
    for canopy_repo, pr in group["repos"].items():
        owner, slug = _resolve_owner_slug(workspace, canopy_repo)
        comments, _resolved = gh.get_review_comments(
            workspace.config.root, owner, slug, pr["number"],
        )
        state = workspace.get_repo(canopy_repo)
        classification = classify_threads(
            comments, state.abs_path, pr.get("head_branch") or "",
        )
        actionable = classification["actionable_threads"]

        # Physical state per repo: where this feature lives right now.
        slot_id = slots_mod.slot_for_feature(workspace, feature_name)
        wt = (
            slots_mod.slot_worktree_path(workspace, slot_id, canopy_repo)
            if slot_id else None
        )
        if is_canonical:
            phys = "canonical"
            path = str(state.abs_path.resolve())
        elif wt is not None and wt.exists() and (wt / ".git").exists():
            phys = "warm"
            path = str(wt.resolve())
        else:
            phys = "cold"
            path = ""    # no on-disk home yet; switch will create one

        per_repo[canopy_repo] = {
            "pr_number": pr["number"],
            "pr_url": pr.get("url", ""),
            "pr_title": pr.get("title", ""),
            "branch": pr.get("head_branch", ""),
            "review_decision": pr.get("review_decision", ""),
            "actionable_count": len(actionable),
            "likely_resolved_count": len(classification["likely_resolved_threads"]),
            "has_actionable_bot_thread": any(
                t.get("author_type") == "Bot" for t in actionable
            ),
            "physical_state": phys,
            "path": path,
        }

    # Top-level physical_state is the highest-resolution per-repo state.
    # canonical > warm > cold. (If repos disagree we report the warmest.)
    states = {r["physical_state"] for r in per_repo.values()}
    if "canonical" in states:
        feat_phys = "canonical"
    elif "warm" in states:
        feat_phys = "warm" if states <= {"warm", "cold"} else "mixed"
    else:
        feat_phys = "cold"

    return {
        "feature": feature_name,
        "linear_issue": group["linear_issue"],
        "linear_url": group["linear_url"],
        "linear_title": group["linear_title"],
        "priority": _compute_priority(per_repo),
        "is_canonical": is_canonical,
        "physical_state": feat_phys,
        "repos": per_repo,
    }


def _compute_priority(per_repo: dict[str, dict]) -> str:
    decisions = {info.get("review_decision", "") for info in per_repo.values()}
    bot_actionable = any(
        info.get("has_actionable_bot_thread") for info in per_repo.values()
    )

    if "CHANGES_REQUESTED" in decisions:
        return "changes_requested"
    non_empty = {d for d in decisions if d}
    if non_empty and non_empty <= {"APPROVED"}:
        return "approved"
    if bot_actionable:
        return "review_required_with_bot_comments"
    return "review_required"
