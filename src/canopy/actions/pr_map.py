"""pr_map — core PR-mapping (branch ↔ PR ↔ feature lane).

Extracted from triage.py in the phase-5 prune. This is the mapping half —
fetch open PRs, resolve owner/slug, group by feature lane. The *tiers* half
(priority/enrichment) stays in triage. registry's remote overlay imports
`_fetch_open_prs` from here; nothing here pulls in the temporal review
classifier or the priority logic.
"""
from __future__ import annotations

from ..integrations import github as gh
from ..workspace.workspace import Workspace
from .aliases import _resolve_owner_slug
from .errors import BlockerError


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
         ``auth-flow`` (api) + ``auth-flow-v2`` (ui) into one
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
