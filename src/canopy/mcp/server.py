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
    Returns rich context per repo: branch, local path, dirty count,
    ahead/behind, and whether it's a worktree.

    Supports alias resolution: pass a Linear issue ID (e.g. "ENG-412")
    or a unique prefix to resolve to the full feature name.

    Args:
        name: Feature lane name, Linear issue ID, or unique prefix.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.switch(name)


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
def preflight(cwd: str | None = None) -> dict:
    """Context-aware pre-commit quality gate.

    Detects which feature/repos you're in from the directory path,
    stages all changes (git add -A), and runs pre-commit hooks.
    Does NOT commit — reports whether the code is ready to commit.

    Args:
        cwd: Directory to detect context from. Defaults to CANOPY_ROOT.
    """
    from ..integrations.precommit import run_precommit

    path = Path(cwd) if cwd else None
    if path is None:
        root = os.environ.get("CANOPY_ROOT")
        path = Path(root) if root else None
    ctx = detect_context(cwd=path)

    if not ctx.repo_paths:
        return {"error": "No repos found in context", "context": ctx.to_dict()}

    results = {}
    all_passed = True

    for repo_path, repo_name in zip(ctx.repo_paths, ctx.repo_names):
        status = git.status_porcelain(repo_path)
        if not status:
            results[repo_name] = {"status": "clean", "hooks": None}
            continue
        try:
            git._run(["add", "-A"], cwd=repo_path)
        except git.GitError as e:
            results[repo_name] = {"status": "error", "error": str(e), "hooks": None}
            all_passed = False
            continue

        hook_result = run_precommit(repo_path)
        passed = hook_result["passed"]
        if not passed:
            all_passed = False

        dirty_count = len(status.strip().splitlines())
        results[repo_name] = {
            "status": "staged" if passed else "hooks_failed",
            "dirty_count": dirty_count,
            "hooks": hook_result,
        }

    return {
        "feature": ctx.feature,
        "context_type": ctx.context_type,
        "all_passed": all_passed,
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
    """Get live worktree status across the workspace — always fresh.

    Scans .canopy/worktrees/ on disk and enriches each entry with
    live git state (branch, dirty files, ahead/behind). Also shows
    git-level worktree info per main repo.

    Returns:
        features: per-feature dict with per-repo branch, dirty state,
            ahead/behind, dirty files list, and worktree path.
        repos: per-repo git worktree list from the main working tree.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.worktrees_live()


@mcp.tool()
def worktree_create(
    name: str,
    issue: str | None = None,
    repos: list[str] | None = None,
) -> dict:
    """Create a feature with worktrees, optionally linked to a Linear issue.

    This is the primary workflow entry point: create isolated worktree
    directories for each repo, open them in your IDE, and optionally
    link to a Linear issue for tracking.

    Args:
        name: Feature/branch name (e.g. "payment-flow").
        issue: Optional Linear issue ID (e.g. "ENG-123"). If a Linear
            MCP server is configured in .canopy/mcps.json, fetches the
            issue title and URL. The issue ID is stored in feature
            metadata either way.
        repos: Subset of repo names. Default: all repos.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)

    linear_issue = ""
    linear_title = ""
    linear_url = ""

    if issue:
        from ..integrations.linear import (
            is_linear_configured,
            get_issue,
            LinearNotConfiguredError,
            LinearIssueNotFoundError,
        )
        from .client import McpClientError

        if is_linear_configured(ws.config.root):
            try:
                issue_data = get_issue(ws.config.root, issue)
                linear_issue = issue_data.get("identifier", issue)
                linear_title = issue_data.get("title", "")
                linear_url = issue_data.get("url", "")
            except (LinearNotConfiguredError, LinearIssueNotFoundError, McpClientError):
                linear_issue = issue
        else:
            linear_issue = issue

    from ..features.coordinator import WorktreeLimitError
    try:
        lane = coordinator.create(
            name,
            repos=repos,
            use_worktrees=True,
            linear_issue=linear_issue,
            linear_title=linear_title,
            linear_url=linear_url,
        )
    except WorktreeLimitError as e:
        return {
            "error": "worktree_limit_reached",
            "message": str(e),
            "current": e.current,
            "limit": e.limit,
            "stale_candidates": e.stale,
        }

    result = lane.to_dict()
    result["worktree_paths"] = coordinator.resolve_paths(name)
    return result


# ── Feature done ────────────────────────────────────────────────────────

@mcp.tool()
def feature_done(feature: str, force: bool = False) -> dict:
    """Clean up a completed feature: remove worktrees, delete branches, archive.

    Use this when a feature is merged or abandoned. It removes worktree
    directories, deletes local branches, and marks the feature as 'done'
    in features.json. Does not touch remotes or PRs.

    Fails if worktrees have uncommitted changes unless force=True.

    Args:
        feature: Feature lane name.
        force: If True, remove even with dirty worktrees.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.done(feature, force=force)


# ── Config tools ────────────────────────────────────────────────────────

@mcp.tool()
def workspace_config(
    key: str | None = None,
    value: str | None = None,
) -> dict:
    """Read or write workspace settings in canopy.toml.

    With no arguments: returns all settings.
    With key only: returns that setting's value.
    With key and value: sets the value and returns it.

    Available settings: name, max_worktrees.

    Args:
        key: Setting name (e.g. "max_worktrees").
        value: New value to set. Omit to read.
    """
    from ..workspace.config import (
        get_config_value, set_config_value, get_all_config,
        WORKSPACE_SETTINGS,
    )

    root = _get_workspace().config.root

    if key is None:
        return get_all_config(root)

    if value is None:
        v = get_config_value(root, key)
        return {"key": key, "value": v}

    coerced = set_config_value(root, key, value)
    return {"key": key, "value": coerced}


# ── Review tools ────────────────────────────────────────────────────────

@mcp.tool()
def review_status(feature: str) -> dict:
    """Check if pull requests exist for a feature across repos.

    For each repo in the feature lane, resolves the GitHub remote and
    checks for an open PR matching the feature branch. Requires a
    GitHub MCP server configured in .canopy/mcps.json.

    Args:
        feature: Feature lane name (e.g. "auth-flow").

    Returns:
        Per-repo PR status including number, title, URL. The top-level
        "has_prs" field is False if no PRs exist in any repo — the
        review workflow cannot proceed without PRs.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.review_status(feature)


@mcp.tool()
def review_comments(feature: str) -> dict:
    """Fetch unresolved PR review comments for a feature across repos.

    Requires an open PR in at least one repo — fails if no PRs exist.
    Returns comments grouped by repo and file, filtered to unresolved
    comments only (resolved and bot comments are excluded).

    This is the primary tool for an agent to understand what reviewers
    want changed before the PR can be merged.

    Args:
        feature: Feature lane name (e.g. "auth-flow").

    Returns:
        Comments grouped by repo, each with path, line, body, author.
        total_comments gives the aggregate count across all repos.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.review_comments(feature)


@mcp.tool()
def review_prep(
    feature: str,
    message: str = "",
) -> dict:
    """Run pre-commit hooks and stage all changes for a feature.

    This is the "get to commit-ready state" workflow:
    1. Finds working directories for the feature (worktrees or repos)
    2. Runs pre-commit hooks in each repo (detects framework vs git hooks)
    3. Stages all changes (git add -A)
    4. Reports per-repo results

    Does NOT create a commit — it leaves the repos staged and ready.
    Call the `commit` tool afterwards to actually commit.

    Args:
        feature: Feature lane name.
        message: Suggested commit message (included in result for
            convenience, not used for committing).

    Returns:
        Per-repo pre-commit results and staging status.
        all_passed is True only if every repo's hooks passed.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.review_prep(feature, message=message)


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
