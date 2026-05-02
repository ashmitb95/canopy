"""Read primitives — alias-aware fetches against Linear and GitHub.

Each tool accepts the universal alias forms (feature name or Linear ID)
plus its native specific form. See ``actions/aliases.py`` for resolution
rules. All return JSON, never mutate.
"""
from __future__ import annotations

from typing import Any

from ..git import repo as git
from ..integrations import github as gh
from ..providers import (
    IssueNotFoundError,
    ProviderNotConfigured,
    get_issue_provider,
)
from ..workspace.workspace import Workspace
from .aliases import (
    BranchTarget, PRTarget,
    resolve_branch_targets, resolve_linear_id, resolve_pr_targets,
)
from .errors import BlockerError, FixAction


def issue_get(workspace: Workspace, alias: str) -> dict:
    """Fetch an issue and return the canonical ``Issue.to_dict()`` shape.

    Mirrors ``mcp__canopy__issue_get``. Canonical fields: ``id``,
    ``identifier``, ``title``, ``description``, ``state`` (mapped to
    ``todo`` / ``in_progress`` / ``done`` / ``cancelled``), ``url``,
    ``assignee``, ``labels``, ``priority``, ``raw``.

    Use this from new CLI / action code. ``linear_get_issue`` (below)
    is the legacy wrapper that exposes the raw provider state for
    pre-M5 callers — kept until they migrate.
    """
    issue_id = resolve_linear_id(workspace, alias)
    provider = get_issue_provider(workspace)
    try:
        issue = provider.get_issue(issue_id)
    except ProviderNotConfigured as e:
        raise BlockerError(
            code="issue_provider_not_configured",
            what=f"Issue provider '{workspace.config.issue_provider.name}' is not configured",
            details={"alias": alias, "issue_id": issue_id, "error": str(e)},
            fix_actions=[
                FixAction(
                    action="configure_provider",
                    args={"provider": workspace.config.issue_provider.name},
                    safe=True,
                    preview=f"configure {workspace.config.issue_provider.name} per docs/architecture/providers.md §4",
                ),
            ],
        )
    except IssueNotFoundError as e:
        raise BlockerError(
            code="issue_not_found",
            what=f"Issue '{issue_id}' not found",
            details={"alias": alias, "issue_id": issue_id, "error": str(e)},
        )
    out = issue.to_dict()
    out["alias"] = alias   # convenience — original alias the caller passed
    return out


def linear_get_issue(workspace: Workspace, alias: str) -> dict:
    """**Deprecated.** Legacy wrapper that exposes raw provider state.

    Pre-M5 callers used this and asserted on ``state`` carrying the raw
    string ("Todo", "open"). New code should call ``issue_get`` instead,
    which returns the canonical mapped ``Issue.to_dict()`` shape.

    Kept until: deprecated MCP tool ``linear_get_issue`` is retired.

    Despite the historical name, after M5 this resolves through the
    provider registry — the workspace's ``[issue_provider]`` block picks
    Linear / GitHub Issues / a future backend. The output dict shape is
    preserved for backward compatibility (existing callers).

    Accepts:
      - Provider-native ID (e.g. ``"SIN-7"`` for Linear, ``"#142"`` for GH)
      - Feature alias whose lane has a linked issue

    Raises ``BlockerError`` if the provider isn't configured or the
    issue can't be fetched.
    """
    issue_id = resolve_linear_id(workspace, alias)
    provider = get_issue_provider(workspace)
    try:
        issue = provider.get_issue(issue_id)
    except ProviderNotConfigured as e:
        raise BlockerError(
            code="issue_provider_not_configured",
            what=f"Issue provider '{workspace.config.issue_provider.name}' is not configured",
            details={"alias": alias, "issue_id": issue_id, "error": str(e)},
            fix_actions=[
                FixAction(
                    action="configure_provider",
                    args={"provider": workspace.config.issue_provider.name},
                    safe=True,
                    preview=f"configure {workspace.config.issue_provider.name} per docs/architecture/providers.md §4",
                ),
            ],
        )
    except IssueNotFoundError as e:
        raise BlockerError(
            code="issue_not_found",
            what=f"Issue '{issue_id}' not found",
            details={"alias": alias, "issue_id": issue_id, "error": str(e)},
        )

    # Preserve the historical output shape. ``state`` carries the raw
    # provider-native state name (Linear: "In Progress"; GH: "open") via
    # ``Issue.raw`` so existing callers asserting on raw values keep
    # working. Falls back to canonical when raw isn't a recognized shape.
    raw = issue.raw or {}
    raw_state = (
        raw.get("state", {}).get("name")
        if isinstance(raw.get("state"), dict)
        else raw.get("state") or raw.get("status") or issue.state
    )
    return {
        "alias": alias,
        "issue_id": issue_id,
        "title": issue.title,
        "state": raw_state,
        "url": issue.url,
        "description": issue.description or "",
        "raw": raw,
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

    M4 hook: when ``alias`` resolves to a tracked feature, each comment
    seen here is logged into the feature's historian memory (deduped
    per-session by id), and the temporal classifier's ``likely_resolved``
    set is logged once per session.
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

    # M4: mirror into historian when this alias maps to a tracked feature.
    _historian_record_comments_read(workspace, alias, repos)

    return {
        "alias": alias,
        "actionable_count": actionable_total,
        "likely_resolved_count": likely_resolved_total,
        "resolved_thread_count": resolved_total,
        "repos": repos,
    }


def _historian_record_comments_read(
    workspace: Workspace, alias: str, repos: dict[str, dict],
) -> None:
    """Best-effort historian capture for `review_comments` reads (M4).

    Fails silently — the canonical comment data is the GitHub response;
    historian is only a narrative layer. We only write when the alias
    resolves cleanly to a feature in features.json.
    """
    try:
        from .aliases import resolve_feature
        from . import historian

        feature_name = resolve_feature(workspace, alias)
    except Exception:
        return

    for repo_data in repos.values():
        for thread in repo_data.get("actionable_threads", []) or []:
            cid = thread.get("id")
            if cid is None:
                continue
            try:
                historian.record_comment_read(
                    workspace.config.root, feature_name,
                    comment_id=cid,
                    author=thread.get("author", ""),
                    path=thread.get("path", ""),
                    line=thread.get("line", 0),
                    body_excerpt=(thread.get("body") or "").splitlines()[0][:120]
                                  if thread.get("body") else "",
                    url=thread.get("url", ""),
                )
            except Exception:
                continue
        # Classifier-resolved batch (one entry per session per call).
        likely = repo_data.get("likely_resolved_threads", []) or []
        if likely:
            try:
                historian.record_classifier_resolved(
                    workspace.config.root, feature_name, threads=likely,
                )
            except Exception:
                pass
