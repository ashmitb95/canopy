"""
Canopy MCP Server — expose workspace operations as MCP tools.

Run via stdio:
    canopy-mcp

Register in Claude Code / Cursor / etc as an MCP server with:
    {
        "mcpServers": {
            "canopy": {
                "command": "canopy-mcp",
                "env": { "CANOPY_ROOT": "/path/to/workspace" }
            }
        }
    }

The CANOPY_ROOT env var tells the server where to find canopy.toml.
If not set, it uses the current working directory.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..workspace.config import load_config, ConfigNotFoundError
from ..workspace.workspace import Workspace
from ..workspace.context import detect_context
from ..features.coordinator import FeatureCoordinator
from ..git import repo as git
from ..git import multi


# ── Server setup ─────────────────────────────────────────────────────────

mcp = FastMCP(
    "canopy",
    instructions="Workspace-first development orchestrator — coordinates Git across multiple repos. Use CANOPY_ROOT env var to point at the workspace.",
)


def _get_workspace() -> Workspace:
    """Load workspace from CANOPY_ROOT or cwd."""
    root = os.environ.get("CANOPY_ROOT")
    path = Path(root) if root else None
    try:
        config = load_config(path)
    except ConfigNotFoundError as e:
        raise ValueError(
            f"No canopy.toml found. Set CANOPY_ROOT or run from a canopy workspace. ({e})"
        )
    return Workspace(config)


# ── Workspace tools ──────────────────────────────────────────────────────

@mcp.tool()
def workspace_status() -> dict:
    """Get the full status of the canopy workspace.

    Returns repo names, current branches, dirty state, divergence
    from default branch, and active feature lanes.
    """
    ws = _get_workspace()
    ws.refresh()
    return ws.to_dict()


@mcp.tool()
def workspace_context(cwd: str | None = None) -> dict:
    """Detect canopy context from a directory path.

    Tells you which feature, repo, and branch you're in based on
    the directory. Useful for understanding worktree structure.

    Args:
        cwd: Directory to detect from. Defaults to CANOPY_ROOT.
    """
    path = Path(cwd) if cwd else None
    if path is None:
        root = os.environ.get("CANOPY_ROOT")
        path = Path(root) if root else None
    ctx = detect_context(cwd=path)
    return ctx.to_dict()


# ── Feature lane tools ───────────────────────────────────────────────────

@mcp.tool()
def feature_create(
    name: str,
    repos: list[str] | None = None,
    use_worktrees: bool = False,
) -> dict:
    """Create a new feature lane across repos.

    Creates matching git branches (and optionally worktrees) in all
    or specified repos in the workspace.

    Args:
        name: Feature/branch name (e.g. "auth-flow").
        repos: Subset of repo names. Default: all repos.
        use_worktrees: If true, create linked worktrees so each repo
            gets its own directory under .canopy/worktrees/<name>/.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    lane = coordinator.create(name, repos, use_worktrees=use_worktrees)

    result = lane.to_dict()
    if use_worktrees:
        result["worktree_paths"] = coordinator.resolve_paths(name)
    return result


@mcp.tool()
def feature_list() -> list[dict]:
    """List all active feature lanes with their repo states.

    Shows both explicitly created features and implicit ones
    (branches that exist in 2+ repos).
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return [lane.to_dict() for lane in coordinator.list_active()]


@mcp.tool()
def feature_status(name: str) -> dict:
    """Get detailed status for a feature lane.

    Shows per-repo branch state: ahead/behind default, dirty files,
    changed files, and worktree paths if applicable.

    Args:
        name: Feature lane name.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    lane = coordinator.status(name)
    return lane.to_dict()


@mcp.tool()
def feature_switch(name: str) -> dict:
    """Switch to a feature lane across repos.

    Checks out the feature branch in each participating repo.
    If a branch is already checked out in a worktree, reports the
    worktree path instead of failing.

    Args:
        name: Feature lane name.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    results = coordinator.switch(name)
    return {"feature": name, "results": {k: str(v) for k, v in results.items()}}


@mcp.tool()
def feature_diff(name: str) -> dict:
    """Get aggregate diff for a feature lane across all repos.

    Shows files changed, insertions, deletions per repo, plus
    cross-repo type overlap detection.

    Args:
        name: Feature lane name.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.diff(name)


@mcp.tool()
def feature_merge_readiness(name: str) -> dict:
    """Check if a feature lane is ready to merge.

    Checks: all repos clean, branches up to date with default,
    no type overlaps across repos.

    Args:
        name: Feature lane name.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.merge_readiness(name)


@mcp.tool()
def feature_paths(name: str) -> dict:
    """Get working directory paths for each repo in a feature lane.

    Returns the best path per repo: worktree path if it exists,
    repo path if the branch is checked out there, etc.

    Args:
        name: Feature lane name.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.resolve_paths(name)


# ── Git operations ───────────────────────────────────────────────────────

@mcp.tool()
def checkout(branch: str, repos: list[str] | None = None) -> dict:
    """Checkout a branch across workspace repos.

    Args:
        branch: Branch name to checkout.
        repos: Subset of repo names. Default: all repos.
    """
    ws = _get_workspace()
    results = multi.checkout_all(ws, branch, repos)
    return {"branch": branch, "results": {k: str(v) for k, v in results.items()}}


@mcp.tool()
def commit(message: str, repos: list[str] | None = None) -> dict:
    """Commit staged changes across workspace repos.

    Only commits in repos that have staged changes.

    Args:
        message: Commit message.
        repos: Subset of repo names. Default: all repos.
    """
    ws = _get_workspace()
    results = multi.commit_all(ws, message, repos)
    return {"message": message, "results": results}


@mcp.tool()
def stage(message: str, cwd: str | None = None) -> dict:
    """Context-aware stage + commit from a directory.

    Detects which feature/repos you're in from the directory path,
    stages all changes (git add -A), and commits across all repos
    in that context.

    Args:
        message: Commit message.
        cwd: Directory to detect context from. Defaults to CANOPY_ROOT.
    """
    path = Path(cwd) if cwd else None
    if path is None:
        root = os.environ.get("CANOPY_ROOT")
        path = Path(root) if root else None
    ctx = detect_context(cwd=path)

    if not ctx.repo_paths:
        return {"error": "No repos found in context", "context": ctx.to_dict()}

    results = {}
    for repo_path, repo_name in zip(ctx.repo_paths, ctx.repo_names):
        status = git.status_porcelain(repo_path)
        if not status:
            results[repo_name] = "clean"
            continue
        try:
            git._run(["add", "-A"], cwd=repo_path)
            sha = git.commit(repo_path, message)
            results[repo_name] = sha[:12]
        except git.GitError as e:
            results[repo_name] = f"error: {e}"

    return {
        "message": message,
        "feature": ctx.feature,
        "context_type": ctx.context_type,
        "results": results,
    }


@mcp.tool()
def log(max_count: int = 20, feature: str | None = None) -> list[dict]:
    """Get interleaved commit log across all repos, sorted by date.

    Args:
        max_count: Maximum entries to return.
        feature: If set, show log for this feature branch.
    """
    ws = _get_workspace()
    return multi.log_all(ws, max_count=max_count, feature=feature)


@mcp.tool()
def branch_list() -> dict:
    """List all local branches across workspace repos.

    Returns per-repo branch lists with current branch, sha, and subject.
    """
    ws = _get_workspace()
    return multi.branches_all(ws)


@mcp.tool()
def branch_delete(
    name: str,
    force: bool = False,
    repos: list[str] | None = None,
) -> dict:
    """Delete a branch across workspace repos.

    Args:
        name: Branch name to delete.
        force: Force delete even if not fully merged.
        repos: Subset of repo names. Default: all repos.
    """
    ws = _get_workspace()
    return multi.delete_branch_all(ws, name, force=force, repos=repos)


@mcp.tool()
def branch_rename(
    old_name: str,
    new_name: str,
    repos: list[str] | None = None,
) -> dict:
    """Rename a branch across workspace repos.

    Args:
        old_name: Current branch name.
        new_name: New branch name.
        repos: Subset of repo names. Default: all repos.
    """
    ws = _get_workspace()
    return multi.rename_branch_all(ws, old_name, new_name, repos=repos)


# ── Stash tools ──────────────────────────────────────────────────────────

@mcp.tool()
def stash_save(
    message: str = "",
    repos: list[str] | None = None,
) -> dict:
    """Stash uncommitted changes across workspace repos.

    Args:
        message: Optional stash message.
        repos: Subset of repo names. Default: all repos.
    """
    ws = _get_workspace()
    return multi.stash_save_all(ws, message=message, repos=repos)


@mcp.tool()
def stash_pop(
    index: int = 0,
    repos: list[str] | None = None,
) -> dict:
    """Pop stash across workspace repos.

    Args:
        index: Stash index to pop.
        repos: Subset of repo names. Default: all repos.
    """
    ws = _get_workspace()
    return multi.stash_pop_all(ws, index=index, repos=repos)


@mcp.tool()
def stash_list() -> dict:
    """List stash entries across all workspace repos."""
    ws = _get_workspace()
    return multi.stash_list_all(ws)


@mcp.tool()
def stash_drop(
    index: int = 0,
    repos: list[str] | None = None,
) -> dict:
    """Drop a stash entry across workspace repos.

    Args:
        index: Stash index to drop.
        repos: Subset of repo names. Default: all repos.
    """
    ws = _get_workspace()
    return multi.stash_drop_all(ws, index=index, repos=repos)


# ── Worktree tools ──────────────────────────────────────────────────────

@mcp.tool()
def worktree_info() -> dict:
    """Get worktree information for all repos in the workspace.

    Shows which repos are linked worktrees, their main working tree,
    and all worktrees associated with each repo.
    """
    ws = _get_workspace()
    all_info = {}
    for state in ws.repos:
        if not state.abs_path.exists():
            continue
        worktrees = git.worktree_list(state.abs_path)
        is_wt = git.is_worktree(state.abs_path)
        main_path = git.worktree_main_path(state.abs_path) if is_wt else None
        all_info[state.config.name] = {
            "is_linked_worktree": is_wt,
            "main_working_tree": str(main_path) if main_path else None,
            "worktrees": worktrees,
        }
    return all_info


# ── Sync ─────────────────────────────────────────────────────────────────

@mcp.tool()
def sync(strategy: str = "rebase") -> dict:
    """Pull default branch and rebase/merge feature branches across repos.

    Args:
        strategy: "rebase" or "merge".
    """
    ws = _get_workspace()
    return multi.sync_all(ws, strategy=strategy)


# ── Entry point ──────────────────────────────────────────────────────────

def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
