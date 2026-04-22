"""
Workspace — the central orchestration object.

Holds the workspace config and provides access to per-repo Git state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import WorkspaceConfig, RepoConfig
from ..git import repo as git


@dataclass
class RepoState:
    """Live Git state for a single repository."""
    config: RepoConfig
    abs_path: Path
    current_branch: str = ""
    head_sha: str = ""
    is_dirty: bool = False
    dirty_count: int = 0
    remote_url: str = ""

    # Populated by enrich()
    ahead_of_default: int = 0
    behind_default: int = 0
    changed_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.config.name,
            "path": str(self.abs_path),
            "role": self.config.role,
            "lang": self.config.lang,
            "current_branch": self.current_branch,
            "head_sha": self.head_sha,
            "is_dirty": self.is_dirty,
            "dirty_count": self.dirty_count,
            "remote_url": self.remote_url,
            "default_branch": self.config.default_branch,
            "ahead_of_default": self.ahead_of_default,
            "behind_default": self.behind_default,
            "changed_files": self.changed_files,
            "changed_file_count": len(self.changed_files),
        }


class Workspace:
    """Central workspace object.

    Reads workspace config, discovers Git state for all repos,
    and provides cross-repo queries.
    """

    def __init__(self, config: WorkspaceConfig):
        self.config = config
        self.repos: list[RepoState] = []
        self._refresh_basic()

    def _refresh_basic(self) -> None:
        """Read basic Git state for all repos."""
        self.repos = []
        for rc in self.config.repos:
            abs_path = (self.config.root / rc.path).resolve()
            state = RepoState(
                config=rc,
                abs_path=abs_path,
            )
            if abs_path.exists():
                try:
                    state.current_branch = git.current_branch(abs_path)
                    state.head_sha = git.short_sha(abs_path)
                    state.is_dirty = git.is_dirty(abs_path)
                    state.dirty_count = git.dirty_file_count(abs_path)
                    state.remote_url = git.remote_url(abs_path)
                except git.GitError:
                    pass  # repo exists but git commands failed
            self.repos.append(state)

    def refresh(self) -> None:
        """Re-read Git state for all repos, including divergence."""
        self._refresh_basic()
        self.enrich()

    def enrich(self) -> None:
        """Enrich repo states with divergence and changed file data."""
        for state in self.repos:
            if not state.abs_path.exists():
                continue
            branch = state.current_branch
            base = state.config.default_branch
            if branch and branch != base and branch != "(detached)":
                try:
                    ahead, behind = git.divergence(state.abs_path, branch, base)
                    state.ahead_of_default = ahead
                    state.behind_default = behind
                    state.changed_files = git.changed_files(
                        state.abs_path, branch, base
                    )
                except git.GitError:
                    pass

    def get_repo(self, name: str) -> RepoState:
        """Get a repo state by name. Raises KeyError if not found."""
        for state in self.repos:
            if state.config.name == name:
                return state
        raise KeyError(f"No repo named '{name}' in workspace")

    def active_features(self) -> list[str]:
        """Find branch names that exist in 2+ repos.

        These are candidate feature lanes — branches that were probably
        created together across repos for coordinated work.
        """
        from collections import Counter
        branch_counts: Counter[str] = Counter()
        default_branches = {rc.default_branch for rc in self.config.repos}

        for state in self.repos:
            branch = state.current_branch
            if branch and branch not in default_branches and branch != "(detached)":
                branch_counts[branch] += 1

        # Also check all local branches in each repo
        for state in self.repos:
            if not state.abs_path.exists():
                continue
            try:
                for branch in git.branches(state.abs_path):
                    if branch not in default_branches:
                        branch_counts[branch] += 1
            except git.GitError:
                pass

        # Branches in 2+ repos are candidate features
        # Deduplicate: we may have counted a branch twice (once from current_branch,
        # once from branches list) — use set-based counting
        branch_repos: dict[str, set[str]] = {}
        for state in self.repos:
            if not state.abs_path.exists():
                continue
            try:
                repo_branches = set(git.branches(state.abs_path))
            except git.GitError:
                repo_branches = set()
            if state.current_branch:
                repo_branches.add(state.current_branch)

            for branch in repo_branches:
                if branch not in default_branches and branch != "(detached)":
                    branch_repos.setdefault(branch, set()).add(state.config.name)

        return sorted(
            branch
            for branch, repos in branch_repos.items()
            if len(repos) >= 2
        )

    def to_dict(self) -> dict:
        """Serialize workspace state to a dict (for --json output)."""
        return {
            "name": self.config.name,
            "root": str(self.config.root),
            "repos": [r.to_dict() for r in self.repos],
            "active_features": self.active_features(),
        }
