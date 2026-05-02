"""
Feature lane lifecycle management.

A feature lane is a coordination primitive that spans multiple repos.
It maps to real Git branches — one per participating repo — with
metadata tracked in .canopy/features.json.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from ..workspace.workspace import Workspace
from ..git import repo as git
from ..git.multi import create_branch_all, cross_repo_diff, find_type_overlaps
from ..providers import get_issue_provider

# Default directory for worktrees, relative to workspace root
_WORKTREE_DIR = ".canopy/worktrees"


class WorktreeLimitError(Exception):
    """Worktree limit would be exceeded."""
    def __init__(self, message: str, current: int = 0, limit: int = 0, stale: list[dict] | None = None):
        super().__init__(message)
        self.current = current
        self.limit = limit
        self.stale = stale or []


@dataclass
class FeatureLane:
    """Metadata and live state for a feature lane."""
    name: str
    repos: list[str]                     # participating repo names
    created_at: str = ""                 # ISO timestamp
    status: str = "active"              # active | merged | abandoned

    # Optional integration links
    linear_issue: str = ""              # e.g. "ENG-123"
    linear_title: str = ""              # e.g. "Add payment processing"
    linear_url: str = ""                # e.g. "https://linear.app/..."

    # Optional per-repo branch override. When unset, ``branch_for(repo)``
    # returns the feature name (the historical default). When set,
    # consumers should always go through ``branch_for`` to get the right
    # branch name per repo. Used for cases like docsum's
    # ``doc-3010-UI-fixes`` (api) vs ``DOC-3010-UI-fixes-2`` (ui) where
    # the same feature has different branch names per repo.
    branches: dict[str, str] = field(default_factory=dict)

    # Populated at query time (not persisted)
    repo_states: dict[str, dict] = field(default_factory=dict)

    def branch_for(self, repo: str) -> str:
        """Return the expected branch name for ``repo`` in this lane.

        Falls back to the feature name if no per-repo override exists.
        """
        return self.branches.get(repo) or self.name

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "repos": self.repos,
            "created_at": self.created_at,
            "status": self.status,
            "repo_states": self.repo_states,
        }
        if self.linear_issue:
            d["linear_issue"] = self.linear_issue
            d["linear_title"] = self.linear_title
            d["linear_url"] = self.linear_url
        if self.branches:
            d["branches"] = dict(self.branches)
        return d


class FeatureCoordinator:
    """Manages feature lane lifecycle across a workspace."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self._store_path = workspace.config.root / ".canopy" / "features.json"

    def _resolve_name(self, name: str) -> str:
        """Resolve a short alias to a full feature name.

        Supports:
        - Exact match (returned as-is)
        - Linear issue prefix (e.g. "ENG-412" → "ENG-412-add-oauth2-login")
        - Unique prefix match (e.g. "ENG-412" matches if only one feature starts with it)

        Raises ValueError if the alias is ambiguous (matches multiple features).
        Returns the original name if no match is found (allows implicit features).
        """
        features = self._load_features()

        # Exact match — fast path
        if name in features:
            return name

        # Prefix match: check if name is a prefix of exactly one feature
        matches = [f for f in features if f.startswith(name)]

        # Also check linear_issue field for issue-ID-only lookups
        if not matches:
            matches = [
                f for f, data in features.items()
                if data.get("linear_issue", "").upper() == name.upper()
            ]

        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            raise ValueError(
                f"Ambiguous alias '{name}' matches: {', '.join(sorted(matches))}"
            )

        # No match in features.json — return as-is for implicit feature detection
        return name

    def create(
        self,
        name: str,
        repos: list[str] | None = None,
        use_worktrees: bool = False,
        worktree_base: Path | None = None,
        linear_issue: str = "",
        linear_title: str = "",
        linear_url: str = "",
    ) -> FeatureLane:
        """Create a new feature lane.

        Creates matching branches in all (or specified) repos and
        records the feature in .canopy/features.json.

        Args:
            name: Feature/branch name.
            repos: Subset of repos (default: all).
            use_worktrees: If True, create linked worktrees instead of
                just branches. Each repo gets a worktree at
                <worktree_base>/<feature>/<repo_name>.
            worktree_base: Base directory for worktrees. Defaults to
                <workspace_root>/.canopy/worktrees.
        """
        target_repos = repos or [r.config.name for r in self.workspace.repos]

        # Validate repos exist
        known = {r.config.name for r in self.workspace.repos}
        unknown = set(target_repos) - known
        if unknown:
            raise ValueError(f"Unknown repos: {', '.join(sorted(unknown))}")

        worktree_paths: dict[str, str] = {}

        if use_worktrees:
            # Check worktree limit
            limit = self.workspace.config.max_worktrees
            if limit > 0:
                current_count = self._count_active_worktrees()
                if current_count >= limit:
                    stale = self._find_stale_worktrees()
                    raise WorktreeLimitError(
                        f"Worktree limit reached ({current_count}/{limit}). "
                        f"Clean up with `canopy done <feature>` or raise the "
                        f"limit with `canopy config max_worktrees {limit + 1}`.",
                        current=current_count,
                        limit=limit,
                        stale=stale,
                    )

            base = worktree_base or (self.workspace.config.root / _WORKTREE_DIR)
            feature_dir = base / name
            feature_dir.mkdir(parents=True, exist_ok=True)

            results: dict[str, bool | str] = {}
            for repo_name in target_repos:
                state = self.workspace.get_repo(repo_name)
                wt_dest = feature_dir / repo_name
                try:
                    git.worktree_add(
                        state.abs_path, wt_dest, name, create_branch=True,
                    )
                    results[repo_name] = True
                    worktree_paths[repo_name] = str(wt_dest)
                except git.GitError as e:
                    results[repo_name] = str(e)

            failed = {r: msg for r, msg in results.items() if msg is not True}
            if len(failed) == len(target_repos):
                raise RuntimeError(
                    f"Failed to create worktrees in all repos: {failed}"
                )
        else:
            # Just create branches
            results = create_branch_all(self.workspace, name, target_repos)
            failed = {r: msg for r, msg in results.items() if msg is not True}
            if len(failed) == len(target_repos):
                raise RuntimeError(
                    f"Failed to create branch in all repos: {failed}"
                )

        # Record the feature
        lane = FeatureLane(
            name=name,
            repos=target_repos,
            created_at=datetime.now(timezone.utc).isoformat(),
            status="active",
            linear_issue=linear_issue,
            linear_title=linear_title,
            linear_url=linear_url,
        )

        features = self._load_features()
        feature_data: dict = {
            "repos": lane.repos,
            "created_at": lane.created_at,
            "status": lane.status,
        }
        if worktree_paths:
            feature_data["worktree_paths"] = worktree_paths
            feature_data["use_worktrees"] = True
        if linear_issue:
            feature_data["linear_issue"] = linear_issue
            feature_data["linear_title"] = linear_title
            feature_data["linear_url"] = linear_url
        features[name] = feature_data
        self._save_features(features)

        return lane

    def list_active(self) -> list[FeatureLane]:
        """List all active feature lanes with live state."""
        features = self._load_features()
        lanes = []

        for name, data in features.items():
            if data.get("status", "active") != "active":
                continue
            lane = FeatureLane(
                name=name,
                repos=data["repos"],
                created_at=data.get("created_at", ""),
                status=data.get("status", "active"),
                linear_issue=data.get("linear_issue", ""),
                linear_title=data.get("linear_title", ""),
                linear_url=data.get("linear_url", ""),
                branches=dict(data.get("branches") or {}),
            )
            self._enrich_lane(lane)
            lanes.append(lane)

        # Also detect implicit features (branches in 2+ repos not in features.json)
        explicit_names = set(features.keys())
        for branch_name in self.workspace.active_features():
            if branch_name not in explicit_names:
                # Find which repos have this branch
                repos_with = []
                for state in self.workspace.repos:
                    try:
                        if git.branch_exists(state.abs_path, branch_name):
                            repos_with.append(state.config.name)
                    except Exception:
                        pass
                if len(repos_with) >= 2:
                    lane = FeatureLane(
                        name=branch_name,
                        repos=repos_with,
                        status="active",
                    )
                    self._enrich_lane(lane)
                    lanes.append(lane)

        return lanes

    def status(self, name: str) -> FeatureLane:
        """Get detailed status for a feature lane."""
        name = self._resolve_name(name)
        features = self._load_features()
        if name in features:
            data = features[name]
            lane = FeatureLane(
                name=name,
                repos=data["repos"],
                created_at=data.get("created_at", ""),
                status=data.get("status", "active"),
                linear_issue=data.get("linear_issue", ""),
                linear_title=data.get("linear_title", ""),
                linear_url=data.get("linear_url", ""),
            )
        else:
            # Implicit feature
            repos = []
            for state in self.workspace.repos:
                if git.branch_exists(state.abs_path, name):
                    repos.append(state.config.name)
            if not repos:
                raise ValueError(f"Feature '{name}' not found")
            lane = FeatureLane(name=name, repos=repos, status="active")

        self._enrich_lane(lane)
        return lane

    def link_linear_issue(self, feature: str, issue: str) -> FeatureLane:
        """Attach a Linear issue to an existing feature lane.

        Fetches issue data via the Linear MCP server and writes linear_issue,
        linear_title, linear_url onto the lane's record in features.json.
        Overwrites any previously linked issue.

        Args:
            feature: Feature lane name or alias.
            issue: Linear issue identifier (e.g. "ENG-412").

        Returns:
            The updated FeatureLane (with enriched repo_states).

        Raises:
            ValueError: Feature not found in features.json.
            ProviderNotConfigured: Issue provider isn't set up.
            IssueNotFoundError: Issue can't be resolved.
        """
        # M5: route through the provider registry. Method name kept as
        # link_linear_issue for backward compat (callers + the MCP tool
        # name); the linked issue can be from any configured provider.
        name = self._resolve_name(feature)
        features = self._load_features()
        if name not in features:
            raise ValueError(
                f"Feature '{name}' not found in features.json — "
                f"link_linear_issue only works on explicitly created lanes."
            )

        provider = get_issue_provider(self.workspace)
        issue_data = provider.get_issue(issue)
        features[name]["linear_issue"] = issue_data.identifier or issue
        features[name]["linear_title"] = issue_data.title or ""
        features[name]["linear_url"] = issue_data.url or ""
        self._save_features(features)

        return self.status(name)

    def diff(self, name: str) -> dict:
        """Get aggregate diff for a feature lane across repos."""
        name = self._resolve_name(name)
        diff_data = cross_repo_diff(self.workspace, name)
        overlaps = find_type_overlaps(self.workspace, name)

        # Summary
        total_files = sum(d["files_changed"] for d in diff_data.values())
        total_ins = sum(d["insertions"] for d in diff_data.values())
        total_del = sum(d["deletions"] for d in diff_data.values())
        participating = sum(1 for d in diff_data.values() if d.get("has_branch"))

        return {
            "feature": name,
            "repos": diff_data,
            "summary": {
                "participating_repos": participating,
                "total_repos": len(diff_data),
                "total_files_changed": total_files,
                "total_insertions": total_ins,
                "total_deletions": total_del,
            },
            "type_overlaps": overlaps,
        }

    def feature_changes(self, name: str) -> dict:
        """Get per-file change status (M/A/D/?) for each repo in a feature.

        Includes uncommitted changes — uses the worktree path when one
        exists so the listing matches what the user is editing.

        Returns:
            {
                "feature": str,
                "repos": {
                    "<repo>": {
                        "has_branch": bool,
                        "path": str,            # repo or worktree path used
                        "default_branch": str,
                        "changes": [{path, status}, ...],
                        "error": str | None,
                    }
                }
            }
        """
        name = self._resolve_name(name)
        lane = self.status(name)
        result: dict[str, dict] = {}

        for repo_name in lane.repos:
            repo_state = lane.repo_states.get(repo_name, {})
            try:
                state = self.workspace.get_repo(repo_name)
            except KeyError:
                result[repo_name] = {"error": "repo not found"}
                continue

            base = repo_state.get("default_branch") or state.config.default_branch
            wt_path = repo_state.get("worktree_path")
            scan_path = Path(wt_path) if wt_path else state.abs_path

            if not repo_state.get("has_branch"):
                result[repo_name] = {
                    "has_branch": False,
                    "path": str(scan_path),
                    "default_branch": base,
                    "changes": [],
                }
                continue

            try:
                changes = git.changed_files_with_status(scan_path, name, base)
                result[repo_name] = {
                    "has_branch": True,
                    "path": str(scan_path),
                    "default_branch": base,
                    "changes": changes,
                }
            except git.GitError as e:
                result[repo_name] = {
                    "has_branch": True,
                    "path": str(scan_path),
                    "default_branch": base,
                    "changes": [],
                    "error": str(e),
                }

        return {"feature": name, "repos": result}

    def merge_readiness(self, name: str) -> dict:
        """Check if a feature lane is ready to merge.

        Checks:
        - All repos are clean (no uncommitted changes)
        - All branches are up to date with default
        - No type overlaps detected
        """
        name = self._resolve_name(name)
        lane = self.status(name)
        issues = []

        for repo_name, state in lane.repo_states.items():
            if state.get("dirty"):
                issues.append(f"{repo_name}: has uncommitted changes")
            if state.get("behind", 0) > 0:
                issues.append(
                    f"{repo_name}: {state['behind']} commits behind "
                    f"{state.get('default_branch', 'default')}"
                )

        overlaps = find_type_overlaps(self.workspace, name)
        if overlaps:
            for o in overlaps:
                issues.append(
                    f"Type overlap: '{o['file_pattern']}' modified in "
                    f"{', '.join(o['repos'])}"
                )

        return {
            "feature": name,
            "ready": len(issues) == 0,
            "issues": issues,
        }

    def resolve_paths(self, name: str) -> dict[str, str]:
        """Get the working directory path for each repo in a feature lane.

        For each repo, returns the best path to work in:
        - If the branch is checked out in a worktree → that worktree path
        - If the branch is the current branch in the repo → the repo path
        - Otherwise → the repo path (caller may need to checkout first)

        This is used by IDE launchers to know which directories to open.
        """
        name = self._resolve_name(name)
        lane = self.status(name)
        paths: dict[str, str] = {}

        for repo_name in lane.repos:
            try:
                state = self.workspace.get_repo(repo_name)
            except KeyError:
                continue

            repo_state = lane.repo_states.get(repo_name, {})

            # Priority 1: worktree path
            if repo_state.get("worktree_path"):
                paths[repo_name] = repo_state["worktree_path"]
            # Priority 2: repo is on this branch
            elif state.current_branch == name:
                paths[repo_name] = str(state.abs_path)
            # Priority 3: branch exists but not checked out — use repo path
            elif repo_state.get("has_branch"):
                paths[repo_name] = str(state.abs_path)

        return paths

    def _enrich_lane(self, lane: FeatureLane) -> None:
        """Populate repo_states with live Git data."""
        for repo_name in lane.repos:
            try:
                state = self.workspace.get_repo(repo_name)
            except KeyError:
                lane.repo_states[repo_name] = {"error": "repo not found"}
                continue

            base = state.config.default_branch
            has_branch = git.branch_exists(state.abs_path, lane.name)

            if not has_branch:
                lane.repo_states[repo_name] = {
                    "has_branch": False,
                    "ahead": 0,
                    "behind": 0,
                    "dirty": False,
                    "changed_files": [],
                }
                continue

            try:
                ahead, behind = git.divergence(
                    state.abs_path, lane.name, base
                )
                files = git.changed_files(state.abs_path, lane.name, base)
                dirty = state.is_dirty if state.current_branch == lane.name else False

                repo_state: dict = {
                    "has_branch": True,
                    "ahead": ahead,
                    "behind": behind,
                    "dirty": dirty,
                    "changed_files": files,
                    "changed_file_count": len(files),
                    "default_branch": base,
                }

                # Check if branch is checked out in a worktree
                wt_path = git.worktree_for_branch(state.abs_path, lane.name)
                if wt_path:
                    repo_state["worktree_path"] = wt_path

                lane.repo_states[repo_name] = repo_state
            except git.GitError as e:
                lane.repo_states[repo_name] = {
                    "has_branch": True,
                    "error": str(e),
                }

    def worktrees_live(self) -> dict:
        """Live scan of all worktrees across the workspace.

        Scans .canopy/worktrees/ on disk and enriches each entry with
        live git state (branch, dirty files, ahead/behind). Also includes
        git-level worktree info per main repo. Never cached — always
        reflects the filesystem as it is right now.

        Returns:
            {
                "features": {
                    "<feature>": {
                        "repos": {
                            "<repo>": {
                                "path": str,
                                "branch": str,
                                "dirty": bool,
                                "dirty_count": int,
                                "dirty_files": [...],
                                "ahead": int,
                                "behind": int,
                                "default_branch": str,
                            }
                        }
                    }
                },
                "repos": {
                    "<repo>": {
                        "main_path": str,
                        "worktrees": [{"path": str, "branch": str, "sha": str}]
                    }
                }
            }
        """
        root = self.workspace.config.root
        wt_base = root / _WORKTREE_DIR

        # ── Part 1: scan .canopy/worktrees/ ──────────────────────────
        features: dict = {}
        if wt_base.is_dir():
            for feat_dir in sorted(wt_base.iterdir()):
                if not feat_dir.is_dir():
                    continue
                feat_name = feat_dir.name
                repos_info: dict = {}
                for repo_dir in sorted(feat_dir.iterdir()):
                    if not repo_dir.is_dir():
                        continue
                    repo_name = repo_dir.name
                    entry: dict = {"path": str(repo_dir)}
                    try:
                        entry["branch"] = git.current_branch(repo_dir)
                        porcelain = git.status_porcelain(repo_dir)
                        entry["dirty"] = len(porcelain) > 0
                        entry["dirty_count"] = len(porcelain)
                        entry["dirty_files"] = [
                            f.get("path", "") for f in porcelain
                        ]
                        # Divergence from default branch
                        # Find the matching repo config for default_branch
                        default_branch = "main"
                        try:
                            state = self.workspace.get_repo(repo_name)
                            default_branch = state.config.default_branch
                        except KeyError:
                            pass
                        entry["default_branch"] = default_branch
                        try:
                            ahead, behind = git.divergence(
                                repo_dir, entry["branch"], default_branch,
                            )
                            entry["ahead"] = ahead
                            entry["behind"] = behind
                        except git.GitError:
                            entry["ahead"] = 0
                            entry["behind"] = 0
                    except git.GitError as e:
                        entry["error"] = str(e)
                    repos_info[repo_name] = entry
                if repos_info:
                    features[feat_name] = {"repos": repos_info}

        # ── Part 2: git-level worktree info per main repo ────────────
        repos_wt: dict = {}
        for state in self.workspace.repos:
            if not state.abs_path.exists():
                continue
            worktrees = git.worktree_list(state.abs_path)
            repos_wt[state.config.name] = {
                "main_path": str(state.abs_path),
                "worktrees": worktrees,
            }

        return {
            "features": features,
            "repos": repos_wt,
        }

    def done(self, name: str, force: bool = False) -> dict:
        """Clean up a feature lane: remove worktrees, delete branches, archive.

        Steps:
        1. Check if worktrees are dirty (fail unless --force)
        2. Remove worktree directories
        3. Delete local branches
        4. Mark feature as 'done' in features.json

        Args:
            name: Feature lane name (or alias/Linear ID).
            force: If True, remove even with dirty worktrees.

        Returns:
            {
                "feature": str,
                "worktrees_removed": {repo: path},
                "branches_deleted": {repo: "ok" | error},
                "archived": bool,
            }
        """
        name = self._resolve_name(name)
        features = self._load_features()
        feature_data = features.get(name, {})
        repos = feature_data.get("repos", [])

        # If not in features.json, try to find it as an implicit feature
        if not repos:
            for state in self.workspace.repos:
                if git.branch_exists(state.abs_path, name):
                    repos.append(state.config.name)
            if not repos:
                raise ValueError(f"Feature '{name}' not found")

        worktrees_removed: dict[str, str] = {}
        branches_deleted: dict[str, str] = {}

        # ── Step 1+2: Remove worktrees ──
        wt_base = self.workspace.config.root / _WORKTREE_DIR / name
        if wt_base.is_dir():
            for repo_dir in sorted(wt_base.iterdir()):
                if not repo_dir.is_dir():
                    continue
                repo_name = repo_dir.name

                # Check dirty state
                if not force:
                    try:
                        porcelain = git.status_porcelain(repo_dir)
                        if porcelain:
                            raise ValueError(
                                f"Worktree '{name}/{repo_name}' has uncommitted changes. "
                                f"Use --force to remove anyway."
                            )
                    except git.GitError:
                        pass

                # Find the main repo to remove worktree from
                try:
                    state = self.workspace.get_repo(repo_name)
                    git.worktree_remove(state.abs_path, repo_dir, force=force)
                    worktrees_removed[repo_name] = str(repo_dir)
                except (KeyError, git.GitError) as e:
                    # If git worktree remove fails, try to clean up manually
                    import shutil
                    try:
                        shutil.rmtree(repo_dir)
                        worktrees_removed[repo_name] = str(repo_dir)
                    except OSError:
                        worktrees_removed[repo_name] = f"error: {e}"

            # Remove the feature directory if empty
            try:
                wt_base.rmdir()
            except OSError:
                pass

        # ── Step 3: Delete local branches ──
        for repo_name in repos:
            try:
                state = self.workspace.get_repo(repo_name)
            except KeyError:
                branches_deleted[repo_name] = "repo not found"
                continue

            if not git.branch_exists(state.abs_path, name):
                branches_deleted[repo_name] = "no branch"
                continue

            # Don't delete if it's the current branch
            current = git.current_branch(state.abs_path)
            if current == name:
                # Switch to default branch first
                try:
                    git.checkout(state.abs_path, state.config.default_branch)
                except git.GitError as e:
                    branches_deleted[repo_name] = f"could not switch away: {e}"
                    continue

            try:
                git.delete_branch(state.abs_path, name, force=force)
                branches_deleted[repo_name] = "ok"
            except git.GitError as e:
                branches_deleted[repo_name] = str(e)

        # ── Step 4: Archive in features.json ──
        archived = False
        if name in features:
            features[name]["status"] = "done"
            # Remove worktree paths since they no longer exist
            features[name].pop("worktree_paths", None)
            features[name].pop("use_worktrees", None)
            self._save_features(features)
            archived = True

        # ── Step 5: Clear active-feature state if this feature is active ──
        active_cleared = False
        try:
            from ..actions.active_feature import clear_active
            active_cleared = clear_active(self.workspace, only_if_feature=name)
        except Exception:
            pass

        return {
            "feature": name,
            "worktrees_removed": worktrees_removed,
            "branches_deleted": branches_deleted,
            "archived": archived,
            "active_cleared": active_cleared,
        }

    def review_status(self, name: str) -> dict:
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

        name = self._resolve_name(name)

        if not is_github_configured(self.workspace.config.root):
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

        lane = self.status(name)
        results: dict[str, dict] = {}
        has_any_pr = False

        for repo_name in lane.repos:
            try:
                state = self.workspace.get_repo(repo_name)
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
                    self.workspace.config.root, owner, repo_slug, name,
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

    def review_comments(self, name: str) -> dict:
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
        from ..actions.review_filter import classify_threads

        name = self._resolve_name(name)
        status = self.review_status(name)
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
                    self.workspace.config.root, owner, repo_slug, pr_number,
                )
                repo_state = self.workspace.get_repo(repo_name)
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

    def review_prep(self, name: str, message: str = "") -> dict:
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

        name = self._resolve_name(name)
        paths = self.resolve_paths(name)
        if not paths:
            raise ValueError(f"No working directories found for feature '{name}'")

        results: dict[str, dict] = {}
        all_passed = True

        for repo_name, path_str in paths.items():
            repo_path = Path(path_str)
            entry: dict = {"path": path_str}

            # Run pre-commit hooks
            try:
                pc_result = run_precommit(repo_path)
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
                    repo_state = self.workspace.get_repo(repo_name)
                    head_sha_per_repo[repo_name] = git.head_sha(repo_state.abs_path)
                except Exception:
                    pass
            record_result(
                self.workspace.config.root, name,
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

    def _count_active_worktrees(self) -> int:
        """Count active worktree feature directories on disk."""
        wt_base = self.workspace.config.root / _WORKTREE_DIR
        if not wt_base.is_dir():
            return 0
        return sum(1 for d in wt_base.iterdir() if d.is_dir())

    def _find_stale_worktrees(self) -> list[dict]:
        """Find worktrees that are candidates for cleanup.

        A worktree is 'stale' if:
        - Its feature is marked as done/merged/abandoned in features.json
        - All its repos are clean (no dirty files)
        - Its branches have been merged into default

        Returns a list of {name, reason} dicts, most stale first.
        """
        wt_base = self.workspace.config.root / _WORKTREE_DIR
        if not wt_base.is_dir():
            return []

        features = self._load_features()
        stale = []

        for feat_dir in sorted(wt_base.iterdir()):
            if not feat_dir.is_dir():
                continue
            feat_name = feat_dir.name
            meta = features.get(feat_name, {})

            # Check if archived
            status = meta.get("status", "active")
            if status in ("done", "merged", "abandoned"):
                stale.append({"name": feat_name, "reason": f"status: {status}"})
                continue

            # Check if all repos are clean and merged
            all_clean = True
            all_merged = True
            for repo_dir in feat_dir.iterdir():
                if not repo_dir.is_dir():
                    continue
                try:
                    porcelain = git.status_porcelain(repo_dir)
                    if porcelain:
                        all_clean = False
                except git.GitError:
                    pass

                try:
                    repo_name = repo_dir.name
                    state = self.workspace.get_repo(repo_name)
                    ahead, _ = git.divergence(
                        repo_dir, feat_name, state.config.default_branch,
                    )
                    if ahead > 0:
                        all_merged = False
                except (KeyError, git.GitError):
                    pass

            if all_clean and all_merged:
                stale.append({"name": feat_name, "reason": "clean and merged"})
            elif all_clean:
                stale.append({"name": feat_name, "reason": "clean (not yet merged)"})

        return stale

    def _load_features(self) -> dict:
        """Load features.json, returning empty dict if not found."""
        if not self._store_path.exists():
            return {}
        try:
            return json.loads(self._store_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_features(self, features: dict) -> None:
        """Save features.json."""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._store_path.write_text(json.dumps(features, indent=2))
