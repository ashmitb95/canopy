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
from .aliases import _resolve_owner_slug
from .errors import BlockerError
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
        ``{author, features: [{feature, linear_issue, linear_url,
        linear_title, priority, repos: {<r>: {pr_number, pr_url,
        pr_title, branch, review_decision, actionable_count,
        likely_resolved_count, has_actionable_bot_thread}}}]}``
        ordered most-urgent first.

    Raises:
        BlockerError: if no GitHub transport is available, or if a
            requested repo is unknown.
    """
    target_repos = _select_repos(workspace, repos)
    prs_by_repo = _fetch_open_prs(workspace, target_repos, author)
    feature_groups = _group_by_feature(workspace, prs_by_repo)
    enriched = [_enrich(workspace, g) for g in feature_groups]
    enriched.sort(key=lambda f: _PRIORITY_ORDER.get(f["priority"], 99))
    return {"author": author, "features": enriched}


def _fetch_open_prs(
    workspace: Workspace, target_repos: list[str], author: str,
) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for repo_name in target_repos:
        try:
            owner, slug = _resolve_owner_slug(workspace, repo_name)
        except BlockerError:
            # Repo with no parseable github remote — skip silently
            out[repo_name] = []
            continue
        try:
            out[repo_name] = gh.list_open_prs(
                workspace.config.root, owner, slug, author=author,
            )
        except gh.GitHubNotConfiguredError as e:
            raise BlockerError(
                code="github_not_configured",
                what="No GitHub transport available (MCP not configured, gh CLI not authed)",
                details={"repo": repo_name, "error": str(e)},
            )
    return out


def _group_by_feature(
    workspace: Workspace, prs_by_repo: dict[str, list[dict]],
) -> list[dict]:
    """Group PRs into feature lanes.

    Strategy:
      1. Build branch → [(canopy_repo, pr)] index.
      2. For each explicit feature in features.json, claim PRs whose
         branch == feature.name (v1: feature name == branch name) and
         whose repo is in feature.repos.
      3. Remaining branches with PRs become implicit features (one
         entry per branch, multi- or single-repo).
    """
    from ..features.coordinator import FeatureCoordinator

    by_branch: dict[str, list[tuple[str, dict]]] = {}
    for repo_name, prs in prs_by_repo.items():
        for pr in prs:
            branch = pr.get("head_branch") or ""
            if not branch:
                continue
            by_branch.setdefault(branch, []).append((repo_name, pr))

    coord = FeatureCoordinator(workspace)
    features = coord._load_features()
    consumed_branches: set[str] = set()
    groups: list[dict] = []

    for feature_name, feature_data in features.items():
        if feature_data.get("status") != "active":
            continue
        if feature_name not in by_branch:
            continue
        feature_repos = set(feature_data.get("repos") or [])
        repos_for_feature = {
            r: pr for r, pr in by_branch[feature_name]
            if not feature_repos or r in feature_repos
        }
        if not repos_for_feature:
            continue
        consumed_branches.add(feature_name)
        groups.append({
            "feature": feature_name,
            "linear_issue": feature_data.get("linear_issue", ""),
            "linear_url": feature_data.get("linear_url", ""),
            "linear_title": feature_data.get("linear_title", ""),
            "repos": repos_for_feature,
        })

    for branch, pr_pairs in by_branch.items():
        if branch in consumed_branches:
            continue
        groups.append({
            "feature": branch,
            "linear_issue": "",
            "linear_url": "",
            "linear_title": "",
            "repos": {r: pr for r, pr in pr_pairs},
        })

    return groups


def _enrich(workspace: Workspace, group: dict) -> dict:
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
        }

    return {
        "feature": group["feature"],
        "linear_issue": group["linear_issue"],
        "linear_url": group["linear_url"],
        "linear_title": group["linear_title"],
        "priority": _compute_priority(per_repo),
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


def _select_repos(workspace: Workspace, requested: list[str] | None) -> list[str]:
    all_names = [r.config.name for r in workspace.repos]
    if requested is None:
        return all_names
    unknown = [r for r in requested if r not in set(all_names)]
    if unknown:
        raise BlockerError(
            code="unknown_repo",
            what=f"unknown repos: {', '.join(unknown)}",
            expected={"available_repos": sorted(all_names)},
            details={"requested": list(requested)},
        )
    return list(requested)
