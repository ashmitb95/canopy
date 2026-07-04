"""repo_paths — per-repo path resolution for a feature lane.

Extracted from feature_state.py in the phase-5 prune. A worktree-backed
feature always resolves to its worktree path; otherwise the main-tree path.
This is a pure core helper (no GitHub / review-filter deps) so `commit`,
`push`, and other core primitives can resolve paths without dragging the
management feature_state surface.
"""
from __future__ import annotations

from pathlib import Path

from ..workspace.workspace import Workspace


def resolve_repo_paths(
    workspace: Workspace, feature_name: str, repo_branches: dict[str, str],
) -> tuple[dict[str, Path], bool]:
    """Per-repo path resolution for state derivation.

    Worktree-backed features always resolve to the worktree path, regardless
    of activation status — a worktree IS the feature's home, the active flag
    only governs implicit cwd in canopy_run/IDE openers.

    Returns (paths_by_repo, has_any_worktrees). The flag drives downstream
    UX choices (e.g. drifted-state next-action: switch vs realign).
    """
    from ..features.coordinator import FeatureCoordinator
    coord = FeatureCoordinator(workspace)
    try:
        lane = coord.status(feature_name)
    except Exception:
        lane = None

    paths: dict[str, Path] = {}
    has_worktrees = False
    for repo_name in repo_branches:
        try:
            state = workspace.get_repo(repo_name)
        except KeyError:
            continue
        wt_path: Path | None = None
        if lane is not None:
            wt_str = (lane.repo_states.get(repo_name) or {}).get("worktree_path")
            if wt_str:
                candidate = Path(wt_str).resolve()
                # ``worktree_for_branch`` returns the main repo path when the
                # branch is checked out there, so candidate == state.abs_path
                # means "no linked worktree — feature lives in the main tree."
                if candidate.exists() and candidate != state.abs_path.resolve():
                    wt_path = candidate
                    has_worktrees = True
        paths[repo_name] = wt_path if wt_path is not None else state.abs_path
    return paths, has_worktrees
