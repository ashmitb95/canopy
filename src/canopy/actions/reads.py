"""Read primitives — alias-aware fetches against Linear and GitHub.

Each tool accepts the universal alias forms (feature name or Linear ID)
plus its native specific form. See ``actions/aliases.py`` for resolution
rules. All return JSON, never mutate.
"""
from __future__ import annotations

from typing import Any

from ..git import repo as git
from ..integrations import github as gh, linear as ln
from ..workspace.workspace import Workspace
from .aliases import (
    BranchTarget, PRTarget,
    resolve_branch_targets, resolve_linear_id, resolve_pr_targets,
)
from .errors import BlockerError, FixAction


def linear_get_issue(workspace: Workspace, alias: str) -> dict:
    """Fetch a Linear issue.

    Accepts:
      - Linear ID directly (e.g. ``ENG-412``)
      - Feature alias whose lane has a linked ``linear_issue``

    Raises ``BlockerError`` if the Linear MCP is not configured or the
    issue can't be fetched. Linear-side exceptions are wrapped so callers
    only have to handle ``ActionError``.
    """
    issue_id = resolve_linear_id(workspace, alias)
    try:
        issue = ln.get_issue(workspace.config.root, issue_id)
    except ln.LinearNotConfiguredError as e:
        raise BlockerError(
            code="linear_not_configured",
            what="Linear MCP is not configured",
            details={"alias": alias, "issue_id": issue_id, "error": str(e)},
            fix_actions=[
                FixAction(
                    action="configure_mcp", args={"server": "linear"},
                    safe=True,
                    preview="add a 'linear' entry to .canopy/mcps.json",
                ),
            ],
        )
    except ln.LinearIssueNotFoundError as e:
        raise BlockerError(
            code="linear_issue_not_found",
            what=f"Linear issue '{issue_id}' not found",
            details={"alias": alias, "issue_id": issue_id, "error": str(e)},
        )
    return {
        "alias": alias,
        "issue_id": issue_id,
        "title": issue.get("title", ""),
        "state": issue.get("state", ""),
        "url": issue.get("url", ""),
        "description": issue.get("description", ""),
        "raw": issue.get("raw"),
    }


def github_get_pr(workspace: Workspace, alias: str) -> dict:
    """Fetch PR data per repo for an alias.

    Accepts:
      - Feature alias → all PRs in the lane (multi-repo)
      - ``<repo>#<pr_number>`` → specific PR
      - GitHub PR URL → specific PR
    """
    targets = resolve_pr_targets(workspace, alias)
    repos: dict[str, dict] = {}
    for t in targets:
        pr = gh.get_pull_request_by_number(
            workspace.config.root, t.owner, t.repo_slug, t.pr_number,
        )
        if pr is None:
            repos[t.repo] = {
                "pr_number": t.pr_number,
                "owner": t.owner,
                "repo_slug": t.repo_slug,
                "found": False,
            }
        else:
            repos[t.repo] = {
                "pr_number": t.pr_number,
                "owner": t.owner,
                "repo_slug": t.repo_slug,
                "found": True,
                **pr,
            }
    return {"alias": alias, "repos": repos}


def github_get_branch(
    workspace: Workspace, alias: str, repo: str | None = None,
) -> dict:
    """Fetch branch info per repo for an alias.

    Accepts:
      - Feature alias → per-repo branches from the feature lane
      - ``<repo>:<branch>`` → specific branch in specific repo

    Returned per repo: ``{branch, exists_locally, head_sha, ahead, behind,
    has_upstream, pr_number?}``.
    """
    targets = resolve_branch_targets(workspace, alias, repo=repo)
    repos: dict[str, dict] = {}
    for t in targets:
        state = workspace.get_repo(t.repo)
        info: dict[str, Any] = {
            "branch": t.branch,
            "exists_locally": git.branch_exists(state.abs_path, t.branch),
        }
        if info["exists_locally"]:
            info["head_sha"] = git.sha_of(state.abs_path, t.branch)
            remote_ref = f"origin/{t.branch}"
            info["has_upstream"] = bool(git.sha_of(state.abs_path, remote_ref))
            if info["has_upstream"]:
                try:
                    ahead, behind = git.divergence(state.abs_path, t.branch, remote_ref)
                except Exception:
                    ahead, behind = 0, 0
                info["ahead"] = ahead
                info["behind"] = behind
            else:
                info["ahead"] = 0
                info["behind"] = 0
        repos[t.repo] = info
    return {"alias": alias, "repos": repos}


def github_get_pr_comments(workspace: Workspace, alias: str) -> dict:
    """Fetch temporally classified PR review comments per repo for an alias.

    Same shape as Wave 1's ``review_comments`` (per-repo
    ``actionable_threads`` / ``likely_resolved_threads`` /
    ``resolved_thread_count`` / ``latest_commit_at``), but accepts the
    full alias surface — feature alias, ``<repo>#<n>``, or PR URL.
    """
    from .review_filter import classify_threads

    targets = resolve_pr_targets(workspace, alias)
    repos: dict[str, dict] = {}
    actionable_total = 0
    likely_resolved_total = 0
    resolved_total = 0

    for t in targets:
        comments, resolved_count = gh.get_review_comments(
            workspace.config.root, t.owner, t.repo_slug, t.pr_number,
        )
        state = workspace.get_repo(t.repo)
        # Need the PR's head branch to anchor the temporal classifier.
        pr = gh.get_pull_request_by_number(
            workspace.config.root, t.owner, t.repo_slug, t.pr_number,
        )
        branch = (pr or {}).get("head_branch") or state.current_branch
        classification = classify_threads(comments, state.abs_path, branch)
        classification["resolved_thread_count"] = resolved_count

        actionable_total += len(classification["actionable_threads"])
        likely_resolved_total += len(classification["likely_resolved_threads"])
        resolved_total += resolved_count

        repos[t.repo] = {
            "pr_number": t.pr_number,
            "pr_url": (pr or {}).get("url", ""),
            "pr_title": (pr or {}).get("title", ""),
            **classification,
        }

    return {
        "alias": alias,
        "actionable_count": actionable_total,
        "likely_resolved_count": likely_resolved_total,
        "resolved_thread_count": resolved_total,
        "repos": repos,
    }
