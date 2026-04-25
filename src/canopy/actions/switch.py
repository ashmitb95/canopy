"""switch — activate a feature as the user's current context.

Three cases handled:

  1. Feature has worktrees → mark them active, return success
  2. Feature is main-tree only → call realign internally, mark active
  3. Feature has no worktrees AND no main branch →
     BlockerError unless ``create_worktrees=True`` (then create + case 1)

Distinct from ``realign``: realign FIXES drift in main repos. switch
DECLARES context (and incidentally fixes drift for case 2 features by
calling realign). Both write per-repo paths into ``.canopy/state/active_feature.json``;
later commands without an explicit ``--feature`` consult that state.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..git import repo as git
from ..workspace.workspace import Workspace
from . import active_feature as af
from .aliases import resolve_feature, repos_for_feature
from .errors import BlockerError, FixAction
from .realign import realign


def switch(
    workspace: Workspace,
    feature: str,
    *,
    create_worktrees: bool = False,
    auto_stash: bool = False,
) -> dict[str, Any]:
    """Activate ``feature`` as the workspace's current context.

    Args:
        feature: feature alias (resolved via the alias layer).
        create_worktrees: if no worktrees exist AND the main branch is
            missing, create worktrees on the fly. Without this flag,
            that case raises ``BlockerError(code='no_active_state')``.
        auto_stash: passed through to ``realign`` for case 2 (main-tree
            mode) when a repo has uncommitted changes.

    Returns ``{feature, mode, per_repo_paths, previous_feature, realign?,
    worktrees_created?}``.
    """
    # Resolve the alias. For --create-worktrees, accept fresh names
    # that don't yet exist anywhere — they become new feature lanes.
    try:
        feature_name = resolve_feature(workspace, feature)
        repo_branches = repos_for_feature(workspace, feature_name)
    except BlockerError as e:
        if create_worktrees and e.code in ("unknown_alias", "ambiguous_alias"):
            feature_name = feature
            repo_branches = {r.config.name: feature_name for r in workspace.repos}
        else:
            raise

    if not repo_branches:
        raise BlockerError(
            code="unknown_feature",
            what=f"no resolvable repos for feature '{feature_name}'",
            details={"feature": feature_name},
        )

    worktree_paths = _existing_worktree_paths(workspace, feature_name, repo_branches)
    main_paths = _main_repo_paths(workspace, feature_name, repo_branches)

    realign_result: dict | None = None
    worktrees_created = False
    per_repo_paths: dict[str, str] = {}

    if worktree_paths:
        # Case 1: at least one worktree exists. Activate worktrees we have
        # + main paths for repos that don't have a worktree.
        per_repo_paths = {**main_paths, **worktree_paths}
        mode = "worktree" if len(worktree_paths) == len(repo_branches) else "mixed"

    elif _all_main_branches_exist(workspace, repo_branches):
        # Case 2: main-tree only. Realign + activate main paths.
        realign_result = realign(workspace, feature_name, auto_stash=auto_stash)
        per_repo_paths = main_paths
        mode = "main_tree"

    elif create_worktrees:
        # Case 3a: missing branches; user opted into worktree creation.
        from ..features.coordinator import FeatureCoordinator
        coord = FeatureCoordinator(workspace)
        try:
            coord.create(
                feature_name,
                repos=list(repo_branches.keys()),
                use_worktrees=True,
            )
        except Exception as e:
            raise BlockerError(
                code="worktree_create_failed",
                what=f"could not create worktrees for '{feature_name}'",
                details={"feature": feature_name, "error": str(e)},
            )
        worktrees_created = True
        # Re-check now that they exist.
        worktree_paths = _existing_worktree_paths(workspace, feature_name, repo_branches)
        per_repo_paths = {**main_paths, **worktree_paths}
        mode = "worktree"

    else:
        # Case 3b: missing branches, no flag. Block.
        missing = [r for r, b in repo_branches.items()
                    if not _branch_exists_in_repo(workspace, r, b)]
        raise BlockerError(
            code="no_active_state",
            what=(
                f"feature '{feature_name}' has no worktrees and the branch "
                f"is missing in {len(missing)} repo(s)"
            ),
            expected={"branches_per_repo": dict(repo_branches)},
            actual={"missing_branch_in_repos": missing},
            fix_actions=[
                FixAction(
                    action="switch",
                    args={"feature": feature_name, "create_worktrees": True},
                    safe=False,
                    preview=f"create worktrees for {feature_name} in {', '.join(missing)} and activate",
                ),
                FixAction(
                    action="feature create",
                    args={"name": feature_name},
                    safe=True,
                    preview=f"create branches in main repos for '{feature_name}' first",
                ),
            ],
        )

    entry = af.write_active(workspace, feature_name, per_repo_paths)

    out: dict[str, Any] = {
        "feature": feature_name,
        "mode": mode,
        "per_repo_paths": dict(per_repo_paths),
        "previous_feature": entry.previous_feature,
        "activated_at": entry.activated_at,
    }
    if realign_result is not None:
        out["realign"] = realign_result
    if worktrees_created:
        out["worktrees_created"] = True
    return out


def _existing_worktree_paths(
    workspace: Workspace,
    feature_name: str,
    repo_branches: dict[str, str],
) -> dict[str, str]:
    """Return ``{repo: abs_path}`` for repos that have a worktree on disk
    at ``.canopy/worktrees/<feature>/<repo>/``."""
    base = workspace.config.root / ".canopy" / "worktrees" / feature_name
    out: dict[str, str] = {}
    for repo_name in repo_branches:
        candidate = base / repo_name
        if candidate.exists() and (candidate / ".git").exists():
            out[repo_name] = str(candidate.resolve())
    return out


def _main_repo_paths(
    workspace: Workspace,
    feature_name: str,
    repo_branches: dict[str, str],
) -> dict[str, str]:
    """Return ``{repo: abs_path}`` for the main working tree of each repo."""
    out: dict[str, str] = {}
    for repo_name in repo_branches:
        try:
            state = workspace.get_repo(repo_name)
            out[repo_name] = str(state.abs_path.resolve())
        except KeyError:
            continue
    return out


def _branch_exists_in_repo(
    workspace: Workspace, repo_name: str, branch: str,
) -> bool:
    try:
        state = workspace.get_repo(repo_name)
    except KeyError:
        return False
    try:
        return git.branch_exists(state.abs_path, branch)
    except Exception:
        return False


def _all_main_branches_exist(
    workspace: Workspace, repo_branches: dict[str, str],
) -> bool:
    return all(
        _branch_exists_in_repo(workspace, repo, branch)
        for repo, branch in repo_branches.items()
    )
