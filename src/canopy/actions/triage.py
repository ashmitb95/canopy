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
from . import active_feature as af
from .aliases import _resolve_owner_slug
from .errors import BlockerError
from .evacuate import warm_worktree_path
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
    active = af.read_active(workspace)
    canonical_feature = active.feature if active else None
    enriched = [_enrich(workspace, g, canonical_feature) for g in feature_groups]
    enriched.sort(key=lambda f: _PRIORITY_ORDER.get(f["priority"], 99))
    return {
        "author": author,
        "canonical_feature": canonical_feature,
        "features": enriched,
    }


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
            from .errors import FixAction
            payload = e.payload or {}
            fix_actions = [
                FixAction(action=fa["action"], args=fa.get("args", {}),
                          safe=fa.get("safe", True), preview=fa.get("preview"))
                for fa in payload.get("fix_actions", [])
            ]
            raise BlockerError(
                code=payload.get("code", "github_not_configured"),
                what=payload.get("what", str(e)),
                fix_actions=fix_actions,
                details={"repo": repo_name},
            )
    return out


def _group_by_feature(
    workspace: Workspace, prs_by_repo: dict[str, list[dict]],
) -> list[dict]:
    """Group PRs into feature lanes.

    Strategy:
      1. Build (repo, branch) → pr index.
      2. For each explicit feature in features.json, claim PRs whose
         branch matches the lane's expected branch *for that repo*
         (using the per-repo ``branches`` override map when set, else
         feature name). This is what groups
         ``doc-1003-fixes`` (api) + ``DOC-1003-fixes-v2`` (ui) into one
         feature lane.
      3. Remaining (repo, branch) pairs that weren't consumed become
         implicit features: each branch becomes a feature, multi-repo
         when the same branch appears in 2+ repos, single-repo otherwise.
    """
    from ..features.coordinator import FeatureCoordinator

    by_repo_branch: dict[tuple[str, str], dict] = {}
    for repo_name, prs in prs_by_repo.items():
        for pr in prs:
            branch = pr.get("head_branch") or ""
            if not branch:
                continue
            by_repo_branch[(repo_name, branch)] = pr

    coord = FeatureCoordinator(workspace)
    features = coord._load_features()
    consumed: set[tuple[str, str]] = set()
    groups: list[dict] = []

    for feature_name, feature_data in features.items():
        if feature_data.get("status") != "active":
            continue
        feature_repos = list(feature_data.get("repos") or [])
        branches_map = feature_data.get("branches") or {}

        repos_for_feature: dict[str, dict] = {}
        for repo_name in feature_repos:
            expected_branch = branches_map.get(repo_name, feature_name)
            key = (repo_name, expected_branch)
            if key in by_repo_branch and key not in consumed:
                repos_for_feature[repo_name] = by_repo_branch[key]
                consumed.add(key)

        if not repos_for_feature:
            continue
        groups.append({
            "feature": feature_name,
            "linear_issue": feature_data.get("linear_issue", ""),
            "linear_url": feature_data.get("linear_url", ""),
            "linear_title": feature_data.get("linear_title", ""),
            "repos": repos_for_feature,
        })

    # Remaining (repo, branch) pairs become implicit feature groups.
    # Same branch across repos → one group; otherwise per-branch group.
    remaining_by_branch: dict[str, dict[str, dict]] = {}
    for (repo_name, branch), pr in by_repo_branch.items():
        if (repo_name, branch) in consumed:
            continue
        remaining_by_branch.setdefault(branch, {})[repo_name] = pr

    for branch, repos in remaining_by_branch.items():
        groups.append({
            "feature": branch,
            "linear_issue": "",
            "linear_url": "",
            "linear_title": "",
            "repos": repos,
        })

    return groups


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
        wt = warm_worktree_path(workspace, feature_name, canopy_repo)
        if is_canonical:
            phys = "canonical"
            path = str(state.abs_path.resolve())
        elif wt.exists() and (wt / ".git").exists():
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
