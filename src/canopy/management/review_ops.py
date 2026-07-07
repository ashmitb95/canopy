"""review_ops — PR-review operations (quarantined management surface).

The three review methods extracted from FeatureCoordinator in the phase-5
prune. They pull GitHub + review_filter; keeping them out of the foundational
coordinator keeps the agent-core decoupled from the management surface.
Callers: the management MCP tools and the `canopy review` / feature-scoped
preflight CLI paths.
"""
from __future__ import annotations

from pathlib import Path

from ..features.coordinator import FeatureCoordinator
from ..git import repo as git
from ..workspace.workspace import Workspace


def review_status(workspace: Workspace, name: str) -> dict:
    """Check if PRs exist for a feature lane across repos.

    For each repo, resolves the remote URL to owner/repo, then queries
    GitHub MCP for an open PR matching the feature branch.

    Returns:
        {
            "feature": str,
            "has_prs": bool,
            "repos": {
                "<repo>": {
                    "branch": str,
                    "owner": str,
                    "repo_name": str,
                    "pr": {number, title, url, state, head_branch} | None,
                    "error": str (optional)
                }
            }
        }

    Raises:
        ValueError: If the feature doesn't exist.
        GitHubNotConfiguredError: If GitHub MCP is not configured.
    """
    from ..integrations.github import (
        is_github_configured,
        find_pull_request,
        _extract_owner_repo,
        GitHubNotConfiguredError,
    )

    coord = FeatureCoordinator(workspace)
    name = coord._resolve_name(name)

    if not is_github_configured(workspace.config.root):
        raise GitHubNotConfiguredError(
            "GitHub MCP not configured.\n"
            "Add a 'github' entry to .canopy/mcps.json:\n"
            "  {\n"
            '    "github": {\n'
            '      "command": "npx",\n'
            '      "args": ["-y", "@modelcontextprotocol/server-github"],\n'
            '      "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_..."}\n'
            "    }\n"
            "  }"
        )

    lane = coord.status(name)
    results: dict[str, dict] = {}
    has_any_pr = False

    for repo_name in lane.repos:
        try:
            state = workspace.get_repo(repo_name)
        except KeyError:
            results[repo_name] = {"error": "repo not found"}
            continue

        remote = git.remote_url(state.abs_path)
        if not remote:
            results[repo_name] = {
                "branch": name,
                "error": "no remote URL configured",
            }
            continue

        parsed = _extract_owner_repo(remote)
        if not parsed:
            results[repo_name] = {
                "branch": name,
                "error": f"could not parse GitHub owner/repo from: {remote}",
            }
            continue

        owner, repo_slug = parsed
        try:
            pr = find_pull_request(
                workspace.config.root, owner, repo_slug, name,
            )
            if pr:
                has_any_pr = True
            results[repo_name] = {
                "branch": name,
                "owner": owner,
                "repo_name": repo_slug,
                "pr": pr,
            }
        except Exception as e:
            results[repo_name] = {
                "branch": name,
                "owner": owner,
                "repo_name": repo_slug,
                "pr": None,
                "error": str(e),
            }

    return {
        "feature": name,
        "has_prs": has_any_pr,
        "repos": results,
    }


def review_comments(workspace: Workspace, name: str) -> dict:
    """Fetch PR review comments classified by temporal staleness.

    Precondition: at least one repo in the lane must have a PR. If
    none do, raises ``PullRequestNotFoundError``.

    Per repo, threads are sorted into:
      - ``actionable_threads``: full comment data; agent reads these
      - ``likely_resolved_threads``: slim summary + addressing commit
      - ``resolved_thread_count``: GitHub-flagged resolved (excluded)

    See ``actions.review_filter.classify_threads`` for the algorithm
    (validated against 4 real PRs in the research doc).

    Returns:
        {
            "feature": str,
            "actionable_count": int,           # across all repos
            "likely_resolved_count": int,
            "resolved_thread_count": int,
            "repos": {
                "<repo>": {
                    "pr_number": int,
                    "pr_url": str,
                    "pr_title": str,
                    "latest_commit_at": str,    # ISO 8601 of branch HEAD
                    "actionable_threads": [...],
                    "likely_resolved_threads": [...],
                    "resolved_thread_count": int,
                }
            }
        }

    Raises:
        PullRequestNotFoundError: If no PR exists for any repo.
        GitHubNotConfiguredError: If GitHub MCP is not configured.
    """
    from ..integrations.github import (
        get_review_comments,
        PullRequestNotFoundError,
        GitHubNotConfiguredError,
    )
    from .review_filter import classify_threads

    coord = FeatureCoordinator(workspace)
    name = coord._resolve_name(name)
    status = review_status(workspace, name)
    if not status["has_prs"]:
        raise PullRequestNotFoundError(
            f"No open PRs found for feature '{name}' in any repo. "
            "Push your branch and create a PR first."
        )

    results: dict[str, dict] = {}
    actionable_total = 0
    likely_resolved_total = 0
    resolved_total = 0

    for repo_name, info in status["repos"].items():
        pr = info.get("pr")
        if not pr:
            continue

        owner = info.get("owner", "")
        repo_slug = info.get("repo_name", "")
        pr_number = pr["number"]

        try:
            comments, resolved_count = get_review_comments(
                workspace.config.root, owner, repo_slug, pr_number,
            )
            repo_state = workspace.get_repo(repo_name)
            branch = info.get("branch") or repo_state.current_branch
            classification = classify_threads(
                comments, repo_state.abs_path, branch,
            )
            # Promote the GitHub-resolved count from upstream filtering.
            classification["resolved_thread_count"] = resolved_count

            actionable_total += len(classification["actionable_threads"])
            likely_resolved_total += len(classification["likely_resolved_threads"])
            resolved_total += resolved_count

            results[repo_name] = {
                "pr_number": pr_number,
                "pr_url": pr.get("url", ""),
                "pr_title": pr.get("title", ""),
                **classification,
            }
        except Exception as e:
            results[repo_name] = {
                "pr_number": pr_number,
                "pr_url": pr.get("url", ""),
                "pr_title": pr.get("title", ""),
                "actionable_threads": [],
                "likely_resolved_threads": [],
                "resolved_thread_count": 0,
                "latest_commit_at": "",
                "error": str(e),
            }

    return {
        "feature": name,
        "actionable_count": actionable_total,
        "likely_resolved_count": likely_resolved_total,
        "resolved_thread_count": resolved_total,
        "repos": results,
    }


def review_prep(workspace: Workspace, name: str, message: str = "") -> dict:
    """Run pre-commit hooks and stage changes for a feature lane.

    This is the "get to commit-ready state" workflow:
    1. Resolve feature → repo paths (worktree or checked-out)
    2. Run pre-commit hooks in each repo
    3. Stage all changes (git add -A)
    4. Report results (does NOT commit — leaves that to the caller)

    If message is provided, it's included in the result for the caller
    to use as a commit message.

    Returns:
        {
            "feature": str,
            "message": str,
            "repos": {
                "<repo>": {
                    "path": str,
                    "precommit": {type, passed, output},
                    "staged": bool,
                    "dirty_count": int,
                    "error": str (optional),
                }
            },
            "all_passed": bool,
        }
    """
    from ..integrations.precommit import run_precommit
    from ..actions.augments import repo_augments

    coord = FeatureCoordinator(workspace)
    name = coord._resolve_name(name)
    paths = coord.resolve_paths(name)
    if not paths:
        raise ValueError(f"No working directories found for feature '{name}'")

    results: dict[str, dict] = {}
    all_passed = True

    for repo_name, path_str in paths.items():
        repo_path = Path(path_str)
        entry: dict = {"path": path_str}

        # Run pre-commit hooks (honoring per-repo augments.preflight_cmd)
        try:
            augments = repo_augments(workspace.config, repo_name)
            pc_result = run_precommit(repo_path, augments=augments)
            entry["precommit"] = pc_result
            if not pc_result["passed"]:
                all_passed = False
        except Exception as e:
            entry["precommit"] = {
                "type": "error",
                "passed": False,
                "output": str(e),
            }
            all_passed = False

        # Stage all changes
        try:
            porcelain = git.status_porcelain(repo_path)
            if porcelain:
                git._run(["add", "-A"], cwd=repo_path)
                entry["staged"] = True
                entry["dirty_count"] = len(porcelain)
            else:
                entry["staged"] = False
                entry["dirty_count"] = 0
        except git.GitError as e:
            entry["staged"] = False
            entry["dirty_count"] = 0
            entry["error"] = str(e)

        results[repo_name] = entry

    # Persist the result so feature_state can distinguish IN_PROGRESS
    # from READY_TO_COMMIT. Records HEAD sha per repo at the time the
    # preflight ran; freshness is decided by comparing those shas
    # against current HEADs.
    try:
        from ..actions.preflight_state import record_result
        head_sha_per_repo: dict[str, str] = {}
        for repo_name in paths.keys():
            try:
                repo_state = workspace.get_repo(repo_name)
                head_sha_per_repo[repo_name] = git.head_sha(repo_state.abs_path)
            except Exception:
                pass
        record_result(
            workspace.config.root, name,
            passed=all_passed,
            head_sha_per_repo=head_sha_per_repo,
            summary=("all checks passed" if all_passed
                      else "one or more checks failed"),
        )
    except Exception:
        # State tracking is auxiliary; don't fail review_prep itself.
        pass

    return {
        "feature": name,
        "message": message,
        "repos": results,
        "all_passed": all_passed,
    }
