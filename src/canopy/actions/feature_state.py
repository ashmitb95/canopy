"""feature_state(feature) — single source of truth for the dashboard CTAs.

Composes drift detection (P1) + dirty/branch state (workspace) + ahead/behind
(git) + temporal-filtered review comments (P4) + recorded preflight result
(``preflight_state``) + GitHub PR data (gh CLI fallback or MCP) into one
of these states:

    drifted          -- branches not on the feature; first thing to fix
    needs_work       -- review feedback exists (CHANGES_REQUESTED or
                        actionable threads from any reviewer)
    in_progress      -- aligned, dirty tree, no fresh preflight
    ready_to_commit  -- aligned, dirty tree, preflight passed for current HEAD
    ready_to_push    -- aligned, clean, ahead of remote
    awaiting_review  -- aligned, clean, pushed, PRs open, no actionable threads
    approved         -- all PRs approved
    no_prs           -- aligned, clean, no PRs anywhere

The state result also carries a ``next_actions`` list — the dashboard
renders the first one as the primary CTA, the rest as secondary. Same
data the agent uses to decide what to do next, so the human and the
agent stay in lockstep.
"""
from __future__ import annotations

from typing import Any

from ..git import repo as git
from ..integrations import github as gh
from ..workspace.workspace import Workspace
from .aliases import (
    repos_for_feature, resolve_feature, _resolve_owner_slug,
)
from .preflight_state import is_fresh
from .review_filter import classify_threads


def feature_state(workspace: Workspace, feature: str) -> dict[str, Any]:
    """Compute the feature's current state + suggested next actions.

    Args:
        workspace: loaded workspace.
        feature: feature alias (resolved through the standard alias layer).

    Returns ``{feature, state, summary, next_actions, warnings}`` —
    summary fields aggregate per-repo state so the dashboard can render
    a feature card without re-querying.
    """
    feature_name = resolve_feature(workspace, feature)
    workspace.refresh()

    repo_branches = repos_for_feature(workspace, feature_name)
    if not repo_branches:
        return _shell_result(feature_name, "no_prs",
                              note="no repos resolved for feature")

    # Drift check from LIVE git state (not heads.json, which may be empty
    # if the post-checkout hook hasn't run). The hook + heads.json power
    # canopy drift's fast path; feature_state prefers correctness.
    drift_info = _live_drift(workspace, repo_branches)
    if drift_info["drifted_repos"] or drift_info["missing_repos"]:
        return _drifted_result(feature_name, drift_info)

    # Aligned. Gather per-repo facts.
    per_repo = _per_repo_facts(workspace, feature_name, repo_branches)
    summary = _summarize(per_repo)
    preflight_fresh, preflight_entry = is_fresh(
        workspace, feature_name, repo_branches,
    )
    summary["preflight"] = _preflight_summary(preflight_entry, preflight_fresh)

    state, next_actions, warnings = _decide_state(
        feature_name, per_repo, summary, preflight_fresh, preflight_entry,
    )

    return {
        "feature": feature_name,
        "state": state,
        "summary": summary,
        "next_actions": next_actions,
        "warnings": warnings,
    }


def _per_repo_facts(
    workspace: Workspace, feature_name: str, repo_branches: dict[str, str],
) -> dict[str, dict]:
    """Gather facts per repo: dirty, ahead/behind, PR, comments."""
    out: dict[str, dict] = {}
    for repo_name, branch in repo_branches.items():
        try:
            state = workspace.get_repo(repo_name)
        except KeyError:
            continue
        repo_path = state.abs_path

        facts: dict[str, Any] = {
            "branch": branch,
            "exists_locally": git.branch_exists(repo_path, branch),
        }
        if not facts["exists_locally"]:
            out[repo_name] = facts
            continue

        try:
            facts["is_dirty"] = git.is_dirty(repo_path)
            facts["dirty_count"] = git.dirty_file_count(repo_path)
        except git.GitError:
            facts["is_dirty"] = False
            facts["dirty_count"] = 0

        try:
            facts["head_sha"] = git.sha_of(repo_path, branch)
        except git.GitError:
            facts["head_sha"] = ""

        remote_ref = f"origin/{branch}"
        facts["has_upstream"] = bool(git.sha_of(repo_path, remote_ref))
        if facts["has_upstream"]:
            try:
                ahead, behind = git.divergence(repo_path, branch, remote_ref)
                facts["ahead"] = ahead
                facts["behind"] = behind
            except Exception:
                facts["ahead"] = 0
                facts["behind"] = 0
        else:
            facts["ahead"] = 0
            facts["behind"] = 0

        # PR + comment data.
        try:
            owner, slug = _resolve_owner_slug(workspace, repo_name)
        except Exception:
            owner, slug = "", ""
        facts["owner"] = owner
        facts["repo_slug"] = slug
        facts["pr"] = None
        facts["actionable_count"] = 0
        facts["likely_resolved_count"] = 0
        facts["review_decision"] = ""
        if owner and slug:
            try:
                pr = gh.find_pull_request(
                    workspace.config.root, owner, slug, branch,
                )
            except gh.GitHubNotConfiguredError:
                pr = None
            if pr:
                facts["pr"] = pr
                facts["review_decision"] = pr.get("review_decision", "")
                try:
                    comments, _ = gh.get_review_comments(
                        workspace.config.root, owner, slug, pr["number"],
                    )
                    classification = classify_threads(comments, repo_path, branch)
                    facts["actionable_count"] = len(classification["actionable_threads"])
                    facts["likely_resolved_count"] = len(classification["likely_resolved_threads"])
                except Exception:
                    pass

        out[repo_name] = facts
    return out


def _summarize(per_repo: dict[str, dict]) -> dict[str, Any]:
    dirty_repos = [r for r, f in per_repo.items() if f.get("is_dirty")]
    ahead_repos = {
        r: f.get("ahead", 0) for r, f in per_repo.items() if f.get("ahead", 0) > 0
    }
    actionable_total = sum(f.get("actionable_count", 0) for f in per_repo.values())
    likely_resolved_total = sum(
        f.get("likely_resolved_count", 0) for f in per_repo.values()
    )
    decisions = {
        r: f.get("review_decision", "") for r, f in per_repo.items() if f.get("pr")
    }
    pr_count = sum(1 for f in per_repo.values() if f.get("pr"))
    return {
        "dirty_repos": dirty_repos,
        "ahead_repos": ahead_repos,
        "actionable_count": actionable_total,
        "likely_resolved_count": likely_resolved_total,
        "review_decisions": decisions,
        "pr_count": pr_count,
        "repos": {r: {k: v for k, v in f.items() if k != "pr"}
                   for r, f in per_repo.items()},
        "prs": {r: f["pr"] for r, f in per_repo.items() if f.get("pr")},
    }


def _preflight_summary(entry, fresh: bool) -> dict[str, Any]:
    if not entry:
        return {"ran": False, "fresh": False}
    return {
        "ran": True,
        "fresh": fresh,
        "passed": entry.get("passed", False),
        "ran_at": entry.get("ran_at", ""),
    }


def _decide_state(
    feature_name: str,
    per_repo: dict[str, dict],
    summary: dict[str, Any],
    preflight_fresh: bool,
    preflight_entry,
) -> tuple[str, list[dict], list[dict]]:
    decisions = summary["review_decisions"]
    actionable = summary["actionable_count"]
    dirty = bool(summary["dirty_repos"])
    ahead = bool(summary["ahead_repos"])
    pr_count = summary["pr_count"]
    warnings: list[dict] = []
    next_actions: list[dict] = []

    if dirty:
        if preflight_fresh and preflight_entry and preflight_entry.get("passed"):
            state = "ready_to_commit"
            next_actions = [
                {"action": "commit", "args": {"feature": feature_name},
                 "primary": True, "label": "Commit",
                 "preview": f"{len(summary['dirty_repos'])} repo(s) staged"},
                {"action": "preflight", "args": {"feature": feature_name},
                 "primary": False, "label": "Re-run preflight"},
            ]
        else:
            state = "in_progress"
            if preflight_entry and not preflight_fresh:
                warnings.append({
                    "code": "preflight_stale",
                    "what": "preflight result is stale (HEAD has moved since last run)",
                })
            next_actions = [
                {"action": "preflight", "args": {"feature": feature_name},
                 "primary": True, "label": "Run preflight"},
                {"action": "stash", "args": {"feature": feature_name},
                 "primary": False, "label": "Stash changes"},
            ]
        return state, next_actions, warnings

    # Clean working tree from here on.
    if ahead:
        # If branch isn't pushed yet (no upstream OR ahead > 0),
        # the next action is push.
        next_actions = [
            {"action": "push", "args": {"feature": feature_name},
             "primary": True, "label": "Push",
             "preview": ", ".join(f"{r}: +{n}" for r, n in summary['ahead_repos'].items())},
        ]
        # If PRs already exist + we have actionable comments, also surface
        # 'address review comments' as secondary.
        if actionable > 0:
            next_actions.append({
                "action": "address_review_comments",
                "args": {"feature": feature_name},
                "primary": False,
                "label": "Address review comments",
            })
        return "ready_to_push", next_actions, warnings

    # Aligned, clean, caught up to remote (or nothing to push).
    if actionable > 0 or _any_changes_requested(decisions):
        next_actions = [
            {"action": "address_review_comments",
             "args": {"feature": feature_name},
             "primary": True, "label": "Address review comments",
             "preview": f"{actionable} actionable thread(s)"},
            {"action": "comments", "args": {"feature": feature_name},
             "primary": False, "label": "View comments"},
        ]
        return "needs_work", next_actions, warnings

    if pr_count == 0:
        # Aligned, clean, but no PRs — likely needs PR creation
        next_actions = [
            {"action": "pr_create", "args": {"feature": feature_name},
             "primary": True, "label": "Open PR(s)"},
        ]
        return "no_prs", next_actions, warnings

    non_empty = {d for d in decisions.values() if d}
    if non_empty and non_empty <= {"APPROVED"}:
        next_actions = [
            {"action": "merge", "args": {"feature": feature_name},
             "primary": True, "label": "Merge",
             "preview": "all PRs approved (manual or via UI)"},
        ]
        return "approved", next_actions, warnings

    next_actions = [
        {"action": "refresh", "args": {"feature": feature_name},
         "primary": True, "label": "Refresh",
         "preview": "waiting on review"},
    ]
    return "awaiting_review", next_actions, warnings


def _any_changes_requested(decisions: dict[str, str]) -> bool:
    return "CHANGES_REQUESTED" in decisions.values()


def _live_drift(
    workspace: Workspace, repo_branches: dict[str, str],
) -> dict[str, Any]:
    """Check actual git state vs expected per repo. Returns
    ``{drifted_repos, missing_repos, expected, actual}``."""
    drifted: list[str] = []
    missing: list[str] = []
    expected: dict[str, str] = {}
    actual: dict[str, str | None] = {}
    for repo_name, expected_branch in repo_branches.items():
        expected[repo_name] = expected_branch
        try:
            state = workspace.get_repo(repo_name)
        except KeyError:
            missing.append(repo_name)
            actual[repo_name] = None
            continue
        if not git.branch_exists(state.abs_path, expected_branch):
            missing.append(repo_name)
            actual[repo_name] = None
            continue
        try:
            current = git.current_branch(state.abs_path)
        except git.GitError:
            current = None
        actual[repo_name] = current
        if current != expected_branch:
            drifted.append(repo_name)
    return {
        "drifted_repos": drifted,
        "missing_repos": missing,
        "expected": expected,
        "actual": actual,
    }


def _drifted_result(feature_name: str, drift_info: dict) -> dict[str, Any]:
    drifted = drift_info["drifted_repos"]
    missing = drift_info["missing_repos"]
    return {
        "feature": feature_name,
        "state": "drifted",
        "summary": {
            "alignment": {
                "aligned": False,
                "expected": drift_info["expected"],
                "actual": drift_info["actual"],
                "drifted_repos": drifted,
                "missing_repos": missing,
            },
        },
        "next_actions": [
            {"action": "realign", "args": {"feature": feature_name},
             "primary": True, "label": "Realign",
             "preview": (
                 f"checkout expected branch in "
                 f"{', '.join(drifted + missing)}"
             )},
        ],
        "warnings": [],
    }


def _shell_result(feature_name: str, state: str, *, note: str = "") -> dict[str, Any]:
    return {
        "feature": feature_name,
        "state": state,
        "summary": {"note": note} if note else {},
        "next_actions": [],
        "warnings": [],
    }
