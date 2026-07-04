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
from ..actions import slots as slots_mod

# Default directory for worktrees, relative to workspace root. In Wave 3.0
# this contains generic numbered slot dirs (worktree-1, worktree-2, ...)
# whose feature occupancy is tracked in .canopy/state/slots.json.
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
    # branch name per repo. Used for cases like ``auth-flow`` (api) vs
    # ``auth-flow-v2`` (ui) where the same feature has different branch
    # names per repo.
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
        target_repos = ([r.config.name for r in self.workspace.repos]
                        if repos is None else repos)

        # Validate repos exist
        known = {r.config.name for r in self.workspace.repos}
        unknown = set(target_repos) - known
        if unknown:
            raise ValueError(f"Unknown repos: {', '.join(sorted(unknown))}")

        worktree_paths: dict[str, str] = {}
        allocated_slot: str | None = None

        if use_worktrees:
            # Wave 3.0: allocate a slot from .canopy/state/slots.json.
            # The config's ``slots`` field is the warm-slot cap (canonical
            # is separate). If all slots are full, raise WorktreeLimitError
            # so the CLI / MCP can surface a fix action.
            limit = self.workspace.config.slots
            slot_state = slots_mod.read_state(self.workspace) or slots_mod.SlotState(
                slot_count=limit,
            )
            # Honor the canopy.toml cap even if state was persisted with a
            # different slot_count earlier.
            slot_state.slot_count = limit

            allocated_slot = slots_mod.allocate_slot(slot_state)
            if allocated_slot is None:
                stale = self._find_stale_worktrees()
                current = len(slot_state.slots)
                raise WorktreeLimitError(
                    f"Worktree limit reached ({current}/{limit}). "
                    f"Clean up with `canopy done <feature>` or raise the "
                    f"limit with `canopy config slots {limit + 1}`.",
                    current=current,
                    limit=limit,
                    stale=stale,
                )

            base = worktree_base or (self.workspace.config.root / _WORKTREE_DIR)
            feature_dir = base / allocated_slot
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
            if target_repos and len(failed) == len(target_repos):
                raise RuntimeError(
                    f"Failed to create worktrees in all repos: {failed}"
                )

            # Persist the slot occupancy + last_touched on success.
            now = slots_mod.now_iso()
            slot_state.slots[allocated_slot] = slots_mod.SlotEntry(
                feature=name, occupied_at=now,
            )
            slot_state.last_touched[name] = now
            slots_mod.write_state(self.workspace, slot_state)
        else:
            # Just create branches
            results = create_branch_all(self.workspace, name, target_repos)
            failed = {r: msg for r, msg in results.items() if msg is not True}
            if target_repos and len(failed) == len(target_repos):
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
        if allocated_slot:
            feature_data["slot_id"] = allocated_slot
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
                branches=dict(data.get("branches") or {}),
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
                # Per-repo branch override: scan the lane's actual branch
                # for this repo, not the bare feature name.
                branch = lane.branch_for(repo_name)
                changes = git.changed_files_with_status(scan_path, branch, base)
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
        - If the feature occupies a warm slot → the slot's repo subdir
          (``.canopy/worktrees/worktree-N/<repo>``)
        - If the branch is checked out in a worktree (legacy/ad-hoc) →
          that worktree path
        - If the branch is the current branch in the repo → the repo path
        - Otherwise → the repo path (caller may need to checkout first)

        This is used by IDE launchers to know which directories to open.
        """
        name = self._resolve_name(name)
        lane = self.status(name)
        paths: dict[str, str] = {}

        # Wave 3.0: prefer the slot path when the feature is warm. This is
        # the authoritative source for warm features.
        slot_id = slots_mod.slot_for_feature(self.workspace, name)

        for repo_name in lane.repos:
            try:
                state = self.workspace.get_repo(repo_name)
            except KeyError:
                continue

            repo_state = lane.repo_states.get(repo_name, {})

            # Priority 1: slot path (Wave 3.0 canonical-slot model)
            if slot_id is not None:
                slot_path = slots_mod.slot_worktree_path(
                    self.workspace, slot_id, repo_name,
                )
                if slot_path.exists():
                    paths[repo_name] = str(slot_path)
                    continue
            # Priority 2: worktree path discovered by git (fallback)
            if repo_state.get("worktree_path"):
                paths[repo_name] = repo_state["worktree_path"]
            # Priority 3: repo is on this branch
            elif state.current_branch == name:
                paths[repo_name] = str(state.abs_path)
            # Priority 4: branch exists but not checked out — use repo path
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
            # Honor per-repo branch overrides — the branch may differ from
            # the feature name (FeatureLane.branches map). Using lane.name
            # here would mis-report mismatched-naming features as having no
            # branch / no changes.
            branch = lane.branch_for(repo_name)
            has_branch = git.branch_exists(state.abs_path, branch)

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
                    state.abs_path, branch, base
                )
                files = git.changed_files(state.abs_path, branch, base)
                dirty = state.is_dirty if state.current_branch == branch else False

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
                wt_path = git.worktree_for_branch(state.abs_path, branch)
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

        Wave 3.0: returns slot-keyed view of warm features. Iterates the
        ``slots`` map from ``.canopy/state/slots.json`` (not feature-named
        directories) and enriches each slot's repo subdirs with live git
        state. Also includes git-level worktree info per main repo.

        Returns:
            {
                "slots": {
                    "worktree-1": {
                        "feature": "<feature>",
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
        # ── Part 1: walk the slots map from slots.json ────────────────
        slots: dict = {}
        slot_state = slots_mod.read_state(self.workspace)
        if slot_state is not None:
            for slot_id, entry in sorted(slot_state.slots.items()):
                feat_name = entry.feature
                slot_dir = (
                    self.workspace.config.root / _WORKTREE_DIR / slot_id
                )
                if not slot_dir.is_dir():
                    continue
                repos_info: dict = {}
                for repo_dir in sorted(slot_dir.iterdir()):
                    if not repo_dir.is_dir():
                        continue
                    repo_name = repo_dir.name
                    repo_entry: dict = {"path": str(repo_dir)}
                    try:
                        repo_entry["branch"] = git.current_branch(repo_dir)
                        porcelain = git.status_porcelain(repo_dir)
                        repo_entry["dirty"] = len(porcelain) > 0
                        repo_entry["dirty_count"] = len(porcelain)
                        repo_entry["dirty_files"] = [
                            f.get("path", "") for f in porcelain
                        ]
                        default_branch = "main"
                        try:
                            state = self.workspace.get_repo(repo_name)
                            default_branch = state.config.default_branch
                        except KeyError:
                            pass
                        repo_entry["default_branch"] = default_branch
                        try:
                            ahead, behind = git.divergence(
                                repo_dir, repo_entry["branch"], default_branch,
                            )
                            repo_entry["ahead"] = ahead
                            repo_entry["behind"] = behind
                        except git.GitError:
                            repo_entry["ahead"] = 0
                            repo_entry["behind"] = 0
                    except git.GitError as e:
                        repo_entry["error"] = str(e)
                    repos_info[repo_name] = repo_entry
                slots[slot_id] = {"feature": feat_name, "repos": repos_info}

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
            "slots": slots,
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

        # ── Step 1+2: Remove worktrees from the feature's slot ──
        # Wave 3.0: look up the slot in .canopy/state/slots.json. The
        # worktree dir is .canopy/worktrees/<slot_id>/, not /<feature>/.
        slot_id = slots_mod.slot_for_feature(self.workspace, name)
        wt_base: Path | None = None
        if slot_id is not None:
            wt_base = (
                self.workspace.config.root / _WORKTREE_DIR / slot_id
            )
        if wt_base is not None and wt_base.is_dir():
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
                                f"Worktree '{slot_id}/{repo_name}' has uncommitted changes. "
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

            # Remove the slot directory if empty
            try:
                wt_base.rmdir()
            except OSError:
                pass

        # ── Step 2b: Drop the slot entry from slots.json ──
        if slot_id is not None:
            slot_state = slots_mod.read_state(self.workspace)
            if slot_state is not None:
                slot_state.slots.pop(slot_id, None)
                # If canonical pointed at this feature (wind-down), clear it.
                if (
                    slot_state.canonical is not None
                    and slot_state.canonical.feature == name
                ):
                    slot_state.canonical = None
                slot_state.last_touched.pop(name, None)
                slots_mod.write_state(self.workspace, slot_state)

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
            features[name].pop("slot_id", None)
            self._save_features(features)
            archived = True

        # ── Step 5: Drop canonical pointer if this feature is canonical ──
        active_cleared = False
        try:
            state = slots_mod.read_state(self.workspace)
            if state and state.canonical and state.canonical.feature == name:
                state.canonical = None
                slots_mod.write_state(self.workspace, state)
                active_cleared = True
        except Exception:
            pass

        return {
            "feature": name,
            "worktrees_removed": worktrees_removed,
            "branches_deleted": branches_deleted,
            "archived": archived,
            "active_cleared": active_cleared,
        }

    def _count_active_worktrees(self) -> int:
        """Count occupied slots from slots.json."""
        state = slots_mod.read_state(self.workspace)
        if state is None:
            return 0
        return len(state.slots)

    def _find_stale_worktrees(self) -> list[dict]:
        """Find slot-occupied features that are candidates for cleanup.

        Wave 3.0: iterates the ``slots`` map in slots.json (not
        feature-named directories). A slot is 'stale' if its feature is:
        - Marked as done/merged/abandoned in features.json, OR
        - All its repos are clean (no dirty files) and the branch has
          been merged into default.

        Returns a list of {name, slot_id, reason} dicts, most stale first.
        """
        slot_state = slots_mod.read_state(self.workspace)
        if slot_state is None or not slot_state.slots:
            return []

        features = self._load_features()
        stale = []

        for slot_id, entry in sorted(slot_state.slots.items()):
            feat_name = entry.feature
            meta = features.get(feat_name, {})
            slot_dir = (
                self.workspace.config.root / _WORKTREE_DIR / slot_id
            )

            # Check if archived
            status = meta.get("status", "active")
            if status in ("done", "merged", "abandoned"):
                stale.append({
                    "name": feat_name, "slot_id": slot_id,
                    "reason": f"status: {status}",
                })
                continue

            if not slot_dir.is_dir():
                continue

            # Check if all repos are clean and merged
            all_clean = True
            all_merged = True
            for repo_dir in slot_dir.iterdir():
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
                    # Per-repo branch override (else the feature name).
                    branch = (meta.get("branches") or {}).get(repo_name, feat_name)
                    ahead, _ = git.divergence(
                        repo_dir, branch, state.config.default_branch,
                    )
                    if ahead > 0:
                        all_merged = False
                except (KeyError, git.GitError):
                    pass

            if all_clean and all_merged:
                stale.append({
                    "name": feat_name, "slot_id": slot_id,
                    "reason": "clean and merged",
                })
            elif all_clean:
                stale.append({
                    "name": feat_name, "slot_id": slot_id,
                    "reason": "clean (not yet merged)",
                })

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
