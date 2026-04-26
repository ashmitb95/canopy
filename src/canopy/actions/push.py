"""push — feature-scoped multi-repo push.

Pushes the feature's branch in each in-scope repo to ``origin``. Like
``commit``, defaults to the canonical feature when no ``--feature`` is
given. ``--dry-run`` enumerates what would happen without firing pushes.

Pre-flight (raises ``BlockerError`` before any push fires):
  - ``no_canonical_feature`` — no active feature and no explicit one.
  - ``empty_feature`` — feature has no associated repos.
  - ``no_upstream`` — at least one in-scope repo lacks a configured
    upstream and ``set_upstream`` was not passed. The fix-action
    carries the same call arguments + ``set_upstream=True`` so the
    agent can retry mechanically.

Per-repo recipe::

    1. read upstream + unpushed_count for the feature branch
    2. branch ahead of upstream → `git push` → ok / rejected / failed
    3. branch up-to-date → status: "up_to_date"
    4. branch lacks upstream + set_upstream → push --set-upstream
    5. rejected (non-fast-forward) without force_with_lease → status:
       "rejected" + reason; do NOT auto-force.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..git import repo as git
from ..workspace.workspace import Workspace
from . import active_feature as af
from .aliases import repos_for_feature, resolve_feature
from .errors import BlockerError, FixAction
from .feature_state import resolve_repo_paths


def _resolve_feature_name(
    workspace: Workspace, feature: str | None,
) -> str:
    if feature:
        return resolve_feature(workspace, feature)
    active = af.read_active(workspace)
    if active is None:
        raise BlockerError(
            code="no_canonical_feature",
            what="no active feature; pass --feature or run `canopy switch <name>` first",
            fix_actions=[
                FixAction(action="switch", args={}, safe=False,
                          preview="canopy switch <feature> sets the canonical slot"),
            ],
        )
    return active.feature


def _check_upstream(
    repo_paths: dict[str, Path],
    repo_branches: dict[str, str],
    set_upstream: bool,
    feature_name: str,
) -> None:
    """Raise no_upstream BlockerError if any repo lacks upstream + set_upstream not given."""
    if set_upstream:
        return
    missing: dict[str, str] = {}
    for repo_name, branch in repo_branches.items():
        path = repo_paths.get(repo_name)
        if path is None:
            continue
        if not git.has_upstream(path, branch):
            missing[repo_name] = branch
    if not missing:
        return
    raise BlockerError(
        code="no_upstream",
        what=(
            f"{len(missing)} repo(s) have no upstream for the feature branch — "
            "rerun with --set-upstream to publish"
        ),
        details={"per_repo": missing},
        fix_actions=[
            FixAction(
                action="push",
                args={"feature": feature_name, "set_upstream": True},
                safe=False,
                preview="canopy push --set-upstream publishes the branches",
            ),
        ],
    )


def _push_one(
    repo_path: Path,
    branch: str,
    *,
    set_upstream: bool,
    force_with_lease: bool,
    dry_run: bool,
) -> dict[str, Any]:
    """Push one repo. Returns a per-repo result dict."""
    has_up = git.has_upstream(repo_path, branch)

    # Up-to-date short-circuit only meaningful when upstream exists.
    if has_up and not set_upstream:
        unpushed = git.unpushed_count(repo_path, branch)
        if unpushed == 0:
            ref = git.upstream_ref(repo_path, branch)
            return {
                "status": "up_to_date",
                "ref": ref,
                "pushed_count": 0,
            }

    if dry_run:
        # dry-run still calls git push --dry-run; trust the primitive.
        return git.push(
            repo_path,
            branch=branch,
            set_upstream=set_upstream and not has_up,
            force_with_lease=force_with_lease,
            dry_run=True,
        )

    return git.push(
        repo_path,
        branch=branch,
        set_upstream=set_upstream and not has_up,
        force_with_lease=force_with_lease,
    )


def push(
    workspace: Workspace,
    *,
    feature: str | None = None,
    repos: list[str] | None = None,
    set_upstream: bool = False,
    force_with_lease: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Push the feature branch across every repo in the lane.

    Args:
        workspace: the workspace.
        feature: feature alias. If None, falls back to the canonical
            feature in ``active_feature.json``.
        repos: optional filter — only push these repos within the
            feature scope.
        set_upstream: pass ``--set-upstream`` for repos that lack an
            upstream; without this, missing-upstream raises a
            ``BlockerError(code='no_upstream')`` pre-flight.
        force_with_lease: pass ``--force-with-lease`` so non-fast-forward
            pushes succeed when the local upstream cache matches the
            remote (preserves "did anyone push behind my back?" check).
        dry_run: enumerate what would happen without firing pushes.

    Returns ``{feature, results: {<repo>: {...}}}``. Per-repo dict shape::

        {status, pushed_count?, ref?, set_upstream?, reason?, dry_run?}

    where ``status`` is one of
    ``ok | up_to_date | rejected | failed``.
    """
    feature_name = _resolve_feature_name(workspace, feature)
    repo_branches = repos_for_feature(workspace, feature_name)
    if not repo_branches:
        raise BlockerError(
            code="empty_feature",
            what=f"feature '{feature_name}' has no associated repos",
        )

    if repos:
        repo_branches = {
            r: b for r, b in repo_branches.items() if r in set(repos)
        }
        if not repo_branches:
            raise BlockerError(
                code="repos_filter_empty",
                what=f"none of {sorted(repos)} are in feature '{feature_name}'",
            )

    repo_paths, _has_wt = resolve_repo_paths(workspace, feature_name, repo_branches)

    _check_upstream(repo_paths, repo_branches, set_upstream, feature_name)

    results: dict[str, dict[str, Any]] = {}
    for repo_name, branch in repo_branches.items():
        path = repo_paths.get(repo_name)
        if path is None:
            results[repo_name] = {"status": "failed", "reason": "repo path unresolved"}
            continue
        results[repo_name] = _push_one(
            path,
            branch,
            set_upstream=set_upstream,
            force_with_lease=force_with_lease,
            dry_run=dry_run,
        )

    return {"feature": feature_name, "results": results}
