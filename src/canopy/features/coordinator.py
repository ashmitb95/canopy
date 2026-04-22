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
from ..git.multi import create_branch_all, checkout_all, cross_repo_diff, find_type_overlaps


@dataclass
class FeatureLane:
    """Metadata and live state for a feature lane."""
    name: str
    repos: list[str]                     # participating repo names
    created_at: str = ""                 # ISO timestamp
    status: str = "active"              # active | merged | abandoned

    # Populated at query time (not persisted)
    repo_states: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "repos": self.repos,
            "created_at": self.created_at,
            "status": self.status,
            "repo_states": self.repo_states,
        }


class FeatureCoordinator:
    """Manages feature lane lifecycle across a workspace."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self._store_path = workspace.config.root / ".canopy" / "features.json"

    def create(self, name: str, repos: list[str] | None = None) -> FeatureLane:
        """Create a new feature lane.

        Creates matching branches in all (or specified) repos and
        records the feature in .canopy/features.json.
        """
        target_repos = repos or [r.config.name for r in self.workspace.repos]

        # Validate repos exist
        known = {r.config.name for r in self.workspace.repos}
        unknown = set(target_repos) - known
        if unknown:
            raise ValueError(f"Unknown repos: {', '.join(sorted(unknown))}")

        # Create branches
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
        )

        features = self._load_features()
        features[name] = {
            "repos": lane.repos,
            "created_at": lane.created_at,
            "status": lane.status,
        }
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

    def switch(self, name: str) -> dict[str, bool | str]:
        """Switch to a feature lane (checkout its branch in all repos)."""
        features = self._load_features()
        if name in features:
            repos = features[name]["repos"]
        else:
            # Try implicit: find repos that have this branch
            repos = []
            for state in self.workspace.repos:
                if git.branch_exists(state.abs_path, name):
                    repos.append(state.config.name)

        if not repos:
            raise ValueError(f"Feature '{name}' not found in any repo")

        return checkout_all(self.workspace, name, repos)

    def status(self, name: str) -> FeatureLane:
        """Get detailed status for a feature lane."""
        features = self._load_features()
        if name in features:
            data = features[name]
            lane = FeatureLane(
                name=name,
                repos=data["repos"],
                created_at=data.get("created_at", ""),
                status=data.get("status", "active"),
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

    def diff(self, name: str) -> dict:
        """Get aggregate diff for a feature lane across repos."""
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

    def merge_readiness(self, name: str) -> dict:
        """Check if a feature lane is ready to merge.

        Checks:
        - All repos are clean (no uncommitted changes)
        - All branches are up to date with default
        - No type overlaps detected
        """
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

                lane.repo_states[repo_name] = {
                    "has_branch": True,
                    "ahead": ahead,
                    "behind": behind,
                    "dirty": dirty,
                    "changed_files": files,
                    "changed_file_count": len(files),
                    "default_branch": base,
                }
            except git.GitError as e:
                lane.repo_states[repo_name] = {
                    "has_branch": True,
                    "error": str(e),
                }

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
