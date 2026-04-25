"""
Cross-repo Git operations.

Calls git.repo functions across multiple repos in a workspace.
"""
from __future__ import annotations

import os
from pathlib import Path

from ..workspace.workspace import Workspace, RepoState
from . import repo as git


def workspace_status(workspace: Workspace) -> list[RepoState]:
    """Refresh and return enriched state for all repos."""
    workspace.refresh()
    return workspace.repos


def create_branch_all(
    workspace: Workspace,
    branch: str,
    repos: list[str] | None = None,
) -> dict[str, bool | str]:
    """Create a branch in all (or specified) repos.

    Returns:
        {repo_name: True} on success, {repo_name: error_message} on failure.
    """
    results: dict[str, bool | str] = {}
    targets = _filter_repos(workspace, repos)

    for state in targets:
        try:
            if git.branch_exists(state.abs_path, branch):
                results[state.config.name] = True  # already exists
            else:
                git.create_branch(state.abs_path, branch)
                results[state.config.name] = True
        except git.GitError as e:
            results[state.config.name] = str(e)

    return results


def checkout_all(
    workspace: Workspace,
    branch: str,
    repos: list[str] | None = None,
) -> dict[str, bool | str]:
    """Checkout a branch in all (or specified) repos.

    Returns:
        {repo_name: True} on success, {repo_name: error_message} on failure.
    """
    results: dict[str, bool | str] = {}
    targets = _filter_repos(workspace, repos)

    for state in targets:
        try:
            if not git.branch_exists(state.abs_path, branch):
                results[state.config.name] = f"branch '{branch}' does not exist"
                continue
            git.checkout(state.abs_path, branch)
            results[state.config.name] = True
        except git.GitError as e:
            results[state.config.name] = str(e)

    return results


def cross_repo_diff(workspace: Workspace, feature: str) -> dict:
    """Aggregate diff across all repos for a feature branch vs default.

    Returns:
        {
            repo_name: {
                files_changed, insertions, deletions,
                changed_files, has_branch
            }
        }
    """
    result = {}

    for state in workspace.repos:
        base = state.config.default_branch
        repo_name = state.config.name

        if not git.branch_exists(state.abs_path, feature):
            result[repo_name] = {
                "has_branch": False,
                "files_changed": 0,
                "insertions": 0,
                "deletions": 0,
                "changed_files": [],
            }
            continue

        try:
            stat = git.diff_stat(state.abs_path, base, feature)
            files = git.changed_files(state.abs_path, feature, base)
            result[repo_name] = {
                "has_branch": True,
                "files_changed": stat["files_changed"],
                "insertions": stat["insertions"],
                "deletions": stat["deletions"],
                "changed_files": files,
            }
        except git.GitError as e:
            result[repo_name] = {
                "has_branch": True,
                "error": str(e),
                "files_changed": 0,
                "insertions": 0,
                "deletions": 0,
                "changed_files": [],
            }

    return result


def find_type_overlaps(workspace: Workspace, feature: str) -> list[dict]:
    """Find files with similar names changed across multiple repos.

    Looks for potential shared type/interface conflicts where, e.g.,
    api/src/models.py and ui/src/types.ts both change user-related types.

    Returns:
        [{file_pattern, repos: [repo_names], files: [{repo, path}]}]
    """
    # Collect changed file basenames per repo
    file_map: dict[str, list[dict]] = {}

    for state in workspace.repos:
        base = state.config.default_branch
        if not git.branch_exists(state.abs_path, feature):
            continue
        try:
            files = git.changed_files(state.abs_path, feature, base)
        except git.GitError:
            continue

        for f in files:
            basename = os.path.splitext(os.path.basename(f))[0].lower()
            # Normalize common type-related names
            file_map.setdefault(basename, []).append({
                "repo": state.config.name,
                "path": f,
            })

    # Filter to basenames that appear in 2+ repos
    overlaps = []
    for basename, entries in file_map.items():
        repos = {e["repo"] for e in entries}
        if len(repos) >= 2:
            overlaps.append({
                "file_pattern": basename,
                "repos": sorted(repos),
                "files": entries,
            })

    return overlaps


def sync_all(
    workspace: Workspace,
    strategy: str = "rebase",
) -> dict[str, str]:
    """Pull default branch and rebase/merge feature branches.

    Returns:
        {repo_name: "ok" | error_message}
    """
    results: dict[str, str] = {}

    for state in workspace.repos:
        try:
            base = state.config.default_branch
            current = git.current_branch(state.abs_path)

            # First, update the default branch
            git.checkout(state.abs_path, base)
            git.pull_rebase(state.abs_path)

            # If we were on a feature branch, rebase it
            if current != base and current != "(detached)":
                git.checkout(state.abs_path, current)
                if strategy == "rebase":
                    git._run(["rebase", base], cwd=state.abs_path)
                else:
                    git._run(["merge", base], cwd=state.abs_path)

            results[state.config.name] = "ok"
        except git.GitError as e:
            results[state.config.name] = str(e)
            # Try to recover: abort rebase if in progress
            try:
                git._run_ok(["rebase", "--abort"], cwd=state.abs_path)
            except Exception:
                pass

    return results


def stash_save_all(
    workspace: Workspace,
    message: str = "",
    repos: list[str] | None = None,
    include_untracked: bool = False,
) -> dict[str, str]:
    """Stash uncommitted changes across repos.

    Returns:
        {repo_name: "stashed" | "clean" | error_message}
    """
    results: dict[str, str] = {}
    targets = _filter_repos(workspace, repos)

    for state in targets:
        try:
            stashed = git.stash_save(
                state.abs_path, message, include_untracked=include_untracked,
            )
            results[state.config.name] = "stashed" if stashed else "clean"
        except git.GitError as e:
            results[state.config.name] = str(e)

    return results


def stash_pop_all(
    workspace: Workspace,
    index: int = 0,
    repos: list[str] | None = None,
) -> dict[str, str]:
    """Pop stash across repos.

    Returns:
        {repo_name: "ok" | "no stash" | error_message}
    """
    results: dict[str, str] = {}
    targets = _filter_repos(workspace, repos)

    for state in targets:
        stashes = git.stash_list(state.abs_path)
        if not stashes:
            results[state.config.name] = "no stash"
            continue
        try:
            git.stash_pop(state.abs_path, index)
            results[state.config.name] = "ok"
        except git.GitError as e:
            results[state.config.name] = str(e)

    return results


def stash_list_all(workspace: Workspace) -> dict[str, list[dict]]:
    """List stashes across all repos.

    Returns:
        {repo_name: [{index, ref, message}, ...]}
    """
    results: dict[str, list[dict]] = {}

    for state in workspace.repos:
        stashes = git.stash_list(state.abs_path)
        if stashes:
            results[state.config.name] = stashes

    return results


def stash_drop_all(
    workspace: Workspace,
    index: int = 0,
    repos: list[str] | None = None,
) -> dict[str, str]:
    """Drop stash entry across repos.

    Returns:
        {repo_name: "ok" | "no stash" | error_message}
    """
    results: dict[str, str] = {}
    targets = _filter_repos(workspace, repos)

    for state in targets:
        stashes = git.stash_list(state.abs_path)
        if not stashes:
            results[state.config.name] = "no stash"
            continue
        try:
            git.stash_drop(state.abs_path, index)
            results[state.config.name] = "ok"
        except git.GitError as e:
            results[state.config.name] = str(e)

    return results


def commit_all(
    workspace: Workspace,
    message: str,
    repos: list[str] | None = None,
) -> dict[str, str]:
    """Commit staged changes across repos with the same message.

    Returns:
        {repo_name: new_sha | "nothing to commit" | error_message}
    """
    results: dict[str, str] = {}
    targets = _filter_repos(workspace, repos)

    for state in targets:
        status = git.status_porcelain(state.abs_path)
        staged = [e for e in status if e["index_status"]]
        if not staged:
            results[state.config.name] = "nothing to commit"
            continue
        try:
            sha = git.commit(state.abs_path, message)
            results[state.config.name] = sha[:12]
        except git.GitError as e:
            results[state.config.name] = str(e)

    return results


def log_all(
    workspace: Workspace,
    max_count: int = 20,
    feature: str | None = None,
) -> list[dict]:
    """Interleaved log across repos, sorted by date.

    Returns:
        List of {repo, sha, short_sha, author, date, subject}
    """
    all_entries = []

    for state in workspace.repos:
        ref = feature if feature and git.branch_exists(state.abs_path, feature) else "HEAD"
        entries = git.log_structured(state.abs_path, ref=ref, max_count=max_count)
        for entry in entries:
            entry["repo"] = state.config.name
            all_entries.append(entry)

    # Sort by date descending
    all_entries.sort(key=lambda e: e["date"], reverse=True)
    return all_entries[:max_count]


def delete_branch_all(
    workspace: Workspace,
    branch: str,
    force: bool = False,
    repos: list[str] | None = None,
) -> dict[str, str]:
    """Delete a branch across repos.

    Returns:
        {repo_name: "ok" | "not found" | error_message}
    """
    results: dict[str, str] = {}
    targets = _filter_repos(workspace, repos)

    for state in targets:
        if not git.branch_exists(state.abs_path, branch):
            results[state.config.name] = "not found"
            continue
        # Don't delete the branch we're currently on
        if git.current_branch(state.abs_path) == branch:
            results[state.config.name] = "currently checked out"
            continue
        try:
            git.delete_branch(state.abs_path, branch, force=force)
            results[state.config.name] = "ok"
        except git.GitError as e:
            results[state.config.name] = str(e)

    return results


def rename_branch_all(
    workspace: Workspace,
    old_name: str,
    new_name: str,
    repos: list[str] | None = None,
) -> dict[str, str]:
    """Rename a branch across repos.

    Returns:
        {repo_name: "ok" | "not found" | error_message}
    """
    results: dict[str, str] = {}
    targets = _filter_repos(workspace, repos)

    for state in targets:
        if not git.branch_exists(state.abs_path, old_name):
            results[state.config.name] = "not found"
            continue
        try:
            git.rename_branch(state.abs_path, old_name, new_name)
            results[state.config.name] = "ok"
        except git.GitError as e:
            results[state.config.name] = str(e)

    return results


def branches_all(workspace: Workspace) -> dict[str, list[dict]]:
    """List all branches across repos.

    Returns:
        {repo_name: [{name, is_current, sha, subject}, ...]}
    """
    results: dict[str, list[dict]] = {}

    for state in workspace.repos:
        entries = git.all_branches(state.abs_path)
        results[state.config.name] = entries

    return results


def _filter_repos(
    workspace: Workspace,
    repo_names: list[str] | None,
) -> list[RepoState]:
    """Filter repos by name, or return all if names is None."""
    if repo_names is None:
        return workspace.repos
    name_set = set(repo_names)
    return [s for s in workspace.repos if s.config.name in name_set]
