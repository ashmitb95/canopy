"""Realign feature lane: bring all participating repos to the feature's branch.

The "Switch to Feature" semantics from the dashboard CTA proposal — same
operation whether you're starting fresh on a feature or fixing drift
after a manual ``git checkout`` somewhere. Reads ACTUAL git state per
repo (not heads.json) so the action is self-correcting even when the
post-checkout hook has missed an update.

Dirty trees: by default, refuse to checkout (raises a structured
``BlockerError(code='dirty_tree')`` listing the offending repos). With
``auto_stash=True``, the dirty changes are stashed via P12 with a
feature tag before the checkout, and the stash ref is recorded in the
result so the caller can pop after.

Returns per-repo ``{status, before, after, stash_ref?, reason?}`` with
``status`` ∈ ``{already_aligned, checkout_ok, failed, skipped}``.
"""
from __future__ import annotations

from typing import Any

from ..git import repo as git
from ..workspace.workspace import Workspace
from . import stash as stash_mod
from .aliases import resolve_feature
from .errors import BlockerError, FailedError, FixAction


def realign(
    workspace: Workspace,
    feature: str,
    auto_stash: bool = False,
    repos: list[str] | None = None,
) -> dict[str, Any]:
    """Bring all repos in the feature lane onto the feature's branch.

    Args:
        workspace: loaded workspace.
        feature: feature alias (name or Linear ID).
        auto_stash: if True, stash dirty trees with a feature tag before
            checking out instead of raising ``BlockerError(code='dirty_tree')``.
        repos: subset to operate on (default: ``feature.repos`` from
            features.json, falling back to all workspace repos).

    Raises:
        BlockerError(code='dirty_tree'): one or more target repos are
            dirty and ``auto_stash=False``. ``fix_actions`` includes the
            ``--auto-stash`` form and a manual stash suggestion.
    """
    feature_name = resolve_feature(workspace, feature)
    expected_branch = feature_name  # v1: feature name == branch name
    target_repos = _select_repos(workspace, feature_name, repos)

    results: dict[str, dict] = {}
    dirty_blocked: list[str] = []

    for repo_name in target_repos:
        try:
            state = workspace.get_repo(repo_name)
        except KeyError:
            results[repo_name] = {"status": "failed", "reason": "unknown_repo"}
            continue
        repo_path = state.abs_path

        try:
            before = git.current_branch(repo_path)
        except git.GitError as e:
            results[repo_name] = {
                "status": "failed",
                "reason": f"can't read current branch: {e}",
            }
            continue

        if before == expected_branch:
            results[repo_name] = {
                "status": "already_aligned",
                "before": before, "after": before,
            }
            continue

        if not git.branch_exists(repo_path, expected_branch):
            results[repo_name] = {
                "status": "failed",
                "reason": "branch_not_found",
                "before": before, "after": before,
                "expected_branch": expected_branch,
            }
            continue

        stash_ref: str | None = None
        if git.is_dirty(repo_path):
            if not auto_stash:
                dirty_blocked.append(repo_name)
                results[repo_name] = {
                    "status": "skipped",
                    "reason": "dirty_tree",
                    "before": before, "after": before,
                }
                continue
            try:
                stash_mod.save_for_feature(
                    workspace, feature_name, "auto: pre-realign",
                    repos=[repo_name],
                )
                # New stashes always push to stash@{0}.
                stash_ref = "stash@{0}"
            except BlockerError as e:
                results[repo_name] = {
                    "status": "failed",
                    "reason": f"auto_stash_failed: {e.what}",
                    "before": before, "after": before,
                }
                continue

        try:
            git.checkout(repo_path, expected_branch)
        except git.GitError as e:
            results[repo_name] = {
                "status": "failed",
                "reason": str(e),
                "before": before, "after": _safe_current_branch(repo_path, before),
            }
            continue

        after = _safe_current_branch(repo_path, before)
        if after == expected_branch:
            entry: dict[str, Any] = {
                "status": "checkout_ok",
                "before": before, "after": after,
            }
            if stash_ref is not None:
                entry["stash_ref"] = stash_ref
            results[repo_name] = entry
        else:
            results[repo_name] = {
                "status": "failed",
                "reason": "post_state_mismatch",
                "before": before, "after": after,
                "expected": expected_branch,
            }

    if dirty_blocked:
        raise BlockerError(
            code="dirty_tree",
            what=(
                f"{len(dirty_blocked)} repo(s) have uncommitted changes "
                f"and would be lost by checkout"
            ),
            expected={"feature": feature_name, "branch": expected_branch},
            actual={"dirty_repos": list(dirty_blocked)},
            fix_actions=[
                FixAction(
                    action="realign",
                    args={"feature": feature_name, "auto_stash": True},
                    safe=False,
                    preview=(
                        "auto-stash dirty repos with feature tag, then checkout"
                    ),
                ),
                FixAction(
                    action="stash save",
                    args={"feature": feature_name},
                    safe=True,
                    preview="manually stash dirty repos with feature tag first",
                ),
            ],
            details={"completed": {k: v for k, v in results.items()
                                    if v.get("status") in ("checkout_ok", "already_aligned")}},
        )

    aligned = all(
        r.get("status") in ("checkout_ok", "already_aligned")
        for r in results.values()
    )
    return {
        "feature": feature_name,
        "aligned": aligned,
        "repos": results,
    }


def _safe_current_branch(repo_path, fallback: str) -> str:
    try:
        return git.current_branch(repo_path)
    except git.GitError:
        return fallback


def _select_repos(
    workspace: Workspace, feature_name: str, requested: list[str] | None,
) -> list[str]:
    all_names = {r.config.name for r in workspace.repos}

    if requested is not None:
        unknown = [r for r in requested if r not in all_names]
        if unknown:
            raise BlockerError(
                code="unknown_repo",
                what=f"unknown repos: {', '.join(unknown)}",
                expected={"available_repos": sorted(all_names)},
                details={"requested": list(requested)},
            )
        return list(requested)

    from ..features.coordinator import FeatureCoordinator
    features = FeatureCoordinator(workspace)._load_features()
    feature_data = features.get(feature_name) or {}
    declared = feature_data.get("repos") or sorted(all_names)
    return [r for r in declared if r in all_names]
