"""Alias resolution for read primitives.

The agent (and humans) pass a single alias like ``DOC-3029`` to any read
tool and canopy figures out what to fetch. Each tool also accepts its
native specific form for direct lookups when the caller already has a
concrete reference.

Supported alias forms:
  - Feature alias: feature name (e.g. ``auth-flow``) or Linear issue ID
    (e.g. ``DOC-3029``). Resolves via ``FeatureCoordinator._resolve_name``
    + ``features.json`` ``linear_issue`` field.
  - PR specific: ``<repo>#<pr_number>`` (e.g. ``docsum-api#1287``) or
    a GitHub PR URL.
  - Branch specific: ``<repo>:<branch>`` (e.g. ``docsum-api:doc-3029``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..workspace.workspace import Workspace
from .errors import BlockerError, FixAction


_LINEAR_ID = re.compile(r"^[A-Z]+-\d+$", re.IGNORECASE)
_PR_SPECIFIC = re.compile(r"^([A-Za-z0-9_.-]+)#(\d+)$")
_BRANCH_SPECIFIC = re.compile(r"^([A-Za-z0-9_.-]+):(.+)$")
_PR_URL = re.compile(r"^https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)")


@dataclass(frozen=True)
class PRTarget:
    repo: str           # canopy repo name
    owner: str          # github owner
    repo_slug: str      # github repo
    pr_number: int


@dataclass(frozen=True)
class BranchTarget:
    repo: str           # canopy repo name
    branch: str


def resolve_feature(workspace: Workspace, alias: str) -> str:
    """Resolve a feature alias to a canonical feature name.

    Strict: if no feature lane (explicit in features.json or implicit
    across multiple repos) matches, raises ``BlockerError(code='unknown_alias')``
    with the available feature list as ``expected``. Different from
    ``FeatureCoordinator._resolve_name`` which returns unknowns as-is.
    """
    from ..features.coordinator import FeatureCoordinator
    coord = FeatureCoordinator(workspace)
    try:
        resolved = coord._resolve_name(alias)
    except ValueError as e:
        raise BlockerError(
            code="ambiguous_alias",
            what=str(e),
            details={"alias": alias},
        )

    features = coord._load_features()
    if resolved in features:
        return resolved

    workspace.refresh()
    if resolved in workspace.active_features():
        return resolved

    raise BlockerError(
        code="unknown_alias",
        what=f"no feature lane matches alias '{alias}'",
        expected={
            "explicit_features": sorted(features.keys()),
            "implicit_features": sorted(workspace.active_features()),
        },
        details={"alias": alias, "resolved_to": resolved},
        fix_actions=[
            FixAction(action="list", args={}, safe=True,
                      preview="canopy list shows all feature lanes"),
        ],
    )


def resolve_linear_id(workspace: Workspace, alias: str) -> str:
    """Resolve an alias to a Linear issue ID.

    Accepts:
      - Linear ID directly (e.g. ``ENG-412``) — returned as-is.
      - Feature alias — looks up ``linear_issue`` from features.json.

    Raises ``BlockerError`` if no Linear ID can be derived.
    """
    if _LINEAR_ID.match(alias):
        return alias

    feature_name = resolve_feature(workspace, alias)

    from ..features.coordinator import FeatureCoordinator
    features = FeatureCoordinator(workspace)._load_features()
    feature = features.get(feature_name) or {}
    linear_id = feature.get("linear_issue")
    if not linear_id:
        raise BlockerError(
            code="no_linear_id",
            what=f"feature '{feature_name}' has no linked Linear issue",
            details={"alias": alias, "feature": feature_name},
            fix_actions=[
                FixAction(
                    action="feature_link_linear",
                    args={"feature": feature_name, "issue": "<ID>"},
                    safe=True,
                    preview="link a Linear issue ID to this feature lane",
                ),
            ],
        )
    return linear_id


def resolve_pr_targets(workspace: Workspace, alias: str) -> list[PRTarget]:
    """Resolve an alias to one or more PR targets.

    Accepts:
      - PR URL (specific PR)
      - ``<repo>#<n>`` (specific PR)
      - Feature alias (all PRs in the lane, across repos)
    """
    m = _PR_URL.match(alias)
    if m:
        owner, repo_slug, pr = m.group(1), m.group(2), int(m.group(3))
        canopy_repo = _find_canopy_repo_by_slug(workspace, owner, repo_slug)
        return [PRTarget(canopy_repo, owner, repo_slug, pr)]

    m = _PR_SPECIFIC.match(alias)
    if m:
        canopy_repo, pr = m.group(1), int(m.group(2))
        if canopy_repo not in {r.config.name for r in workspace.repos}:
            raise BlockerError(
                code="unknown_repo",
                what=f"no repo '{canopy_repo}' in workspace",
                expected={"available_repos": sorted(r.config.name for r in workspace.repos)},
                details={"alias": alias},
            )
        owner, repo_slug = _resolve_owner_slug(workspace, canopy_repo)
        return [PRTarget(canopy_repo, owner, repo_slug, pr)]

    feature_name = resolve_feature(workspace, alias)

    from ..features.coordinator import FeatureCoordinator
    coord = FeatureCoordinator(workspace)
    status = coord.review_status(feature_name)
    targets: list[PRTarget] = []
    for repo_name, info in status.get("repos", {}).items():
        pr = info.get("pr")
        if not pr:
            continue
        targets.append(PRTarget(
            repo=repo_name,
            owner=info.get("owner", ""),
            repo_slug=info.get("repo_name", ""),
            pr_number=pr["number"],
        ))
    if not targets:
        raise BlockerError(
            code="no_prs_for_feature",
            what=f"feature '{feature_name}' has no open PRs in any repo",
            details={"alias": alias, "feature": feature_name},
            fix_actions=[
                FixAction(action="pr_create", args={"feature": feature_name},
                          safe=False, preview="open PRs for this feature"),
            ],
        )
    return targets


def resolve_branch_targets(
    workspace: Workspace, alias: str, repo: str | None = None,
) -> list[BranchTarget]:
    """Resolve an alias to one or more branch targets.

    Accepts:
      - ``<repo>:<branch>`` (specific branch in specific repo)
      - Feature alias (per-repo branches from feature lane)

    If ``repo`` is provided alongside a feature alias, filters to that repo.
    """
    m = _BRANCH_SPECIFIC.match(alias)
    if m:
        canopy_repo, branch = m.group(1), m.group(2)
        repo_names = {r.config.name for r in workspace.repos}
        if canopy_repo not in repo_names:
            raise BlockerError(
                code="unknown_repo",
                what=f"no repo '{canopy_repo}' in workspace",
                expected={"available_repos": sorted(repo_names)},
                details={"alias": alias},
            )
        if repo and canopy_repo != repo:
            raise BlockerError(
                code="alias_repo_mismatch",
                what=f"alias specifies '{canopy_repo}' but repo='{repo}' was passed",
                details={"alias": alias, "repo": repo},
            )
        return [BranchTarget(canopy_repo, branch)]

    feature_name = resolve_feature(workspace, alias)

    from ..features.coordinator import FeatureCoordinator
    features = FeatureCoordinator(workspace)._load_features()
    feature_data = features.get(feature_name) or {}
    repos = feature_data.get("repos") or [r.config.name for r in workspace.repos]
    if repo:
        if repo not in repos:
            raise BlockerError(
                code="repo_not_in_feature",
                what=f"repo '{repo}' is not part of feature '{feature_name}'",
                expected={"feature_repos": list(repos)},
                details={"alias": alias, "repo": repo, "feature": feature_name},
            )
        repos = [repo]
    return [BranchTarget(r, feature_name) for r in repos]


def _find_canopy_repo_by_slug(workspace: Workspace, owner: str, slug: str) -> str:
    from ..git import repo as git
    target_lc = f"{owner}/{slug}".lower()
    target_lc_no_dotgit = target_lc.removesuffix(".git")
    for state in workspace.repos:
        try:
            url = git.remote_url(state.abs_path).lower().removesuffix(".git")
        except Exception:
            continue
        if target_lc in url or target_lc_no_dotgit in url:
            return state.config.name
    raise BlockerError(
        code="unknown_github_repo",
        what=f"no canopy repo matches github {owner}/{slug}",
        expected={"available_repos": sorted(r.config.name for r in workspace.repos)},
        details={"owner": owner, "slug": slug},
    )


def _resolve_owner_slug(workspace: Workspace, canopy_repo: str) -> tuple[str, str]:
    from ..git import repo as git
    from ..integrations.github import _extract_owner_repo
    state = workspace.get_repo(canopy_repo)
    url = git.remote_url(state.abs_path)
    parsed = _extract_owner_repo(url)
    if not parsed:
        raise BlockerError(
            code="unparseable_remote",
            what=f"can't extract owner/repo from {canopy_repo} remote: {url}",
            details={"canopy_repo": canopy_repo, "remote_url": url},
        )
    return parsed
