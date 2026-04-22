"""
Context detection — figure out where canopy is running from.

When you run canopy from inside a worktree directory, this module
detects which feature lane, which repo(s), and which branch you're
working in. This powers context-aware commands like `canopy stage`.

Context hierarchy (from most to least specific):
    1. Inside a specific repo worktree:
       .canopy/worktrees/auth-flow/api/  →  feature=auth-flow, repo=api
    2. Inside a feature directory (parent of repo worktrees):
       .canopy/worktrees/auth-flow/      →  feature=auth-flow, repos=all
    3. Inside a normal repo in the workspace:
       workspace/api/                     →  repo=api, feature=current branch
    4. At the workspace root:
       workspace/                         →  whole workspace
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..git import repo as git


@dataclass
class CanopyContext:
    """Where canopy is running and what it can see."""

    # Where we detected context from
    cwd: Path

    # Workspace root (where canopy.toml lives), if found
    workspace_root: Optional[Path] = None

    # Feature lane name, if detected
    feature: Optional[str] = None

    # Repo directories to operate on (worktree or regular repo paths)
    repo_paths: list[Path] = field(default_factory=list)

    # Repo names (matching repo_paths)
    repo_names: list[str] = field(default_factory=list)

    # The current branch (if in a single repo/worktree)
    branch: Optional[str] = None

    # How we detected context
    context_type: str = "unknown"
    # "feature_dir"    — inside .canopy/worktrees/<feature>/
    # "repo_worktree"  — inside .canopy/worktrees/<feature>/<repo>/
    # "repo"           — inside a normal workspace repo
    # "workspace_root" — at the workspace root
    # "unknown"        — couldn't detect

    def to_dict(self) -> dict:
        return {
            "cwd": str(self.cwd),
            "workspace_root": str(self.workspace_root) if self.workspace_root else None,
            "feature": self.feature,
            "repo_paths": [str(p) for p in self.repo_paths],
            "repo_names": self.repo_names,
            "branch": self.branch,
            "context_type": self.context_type,
        }


def detect_context(cwd: Path | None = None) -> CanopyContext:
    """Detect canopy context from the current working directory.

    Walks up from cwd looking for clues:
    - .canopy/worktrees/<feature>/<repo>/ structure
    - canopy.toml (workspace root)
    - .git directory (regular repo)
    """
    if cwd is None:
        cwd = Path.cwd().resolve()
    else:
        cwd = cwd.resolve()

    ctx = CanopyContext(cwd=cwd)

    # Strategy 1: Are we inside a .canopy/worktrees/<feature>/ structure?
    _detect_worktree_context(ctx)
    if ctx.context_type != "unknown":
        return ctx

    # Strategy 2: Are we inside a normal repo in a workspace?
    _detect_repo_context(ctx)
    if ctx.context_type != "unknown":
        return ctx

    # Strategy 3: Are we at a workspace root?
    _detect_workspace_root(ctx)

    return ctx


def _detect_worktree_context(ctx: CanopyContext) -> None:
    """Check if cwd is inside .canopy/worktrees/<feature>/[<repo>/]."""
    path = ctx.cwd

    # Walk up looking for a path segment that matches .canopy/worktrees/<feature>
    parts = path.parts
    for i, part in enumerate(parts):
        if part == ".canopy" and i + 2 < len(parts) and parts[i + 1] == "worktrees":
            # Found .canopy/worktrees/ — next part is the feature name
            feature_name = parts[i + 2]
            canopy_dir = Path(*parts[:i])  # workspace root
            feature_dir = Path(*parts[:i + 3])  # .canopy/worktrees/<feature>

            ctx.workspace_root = canopy_dir
            ctx.feature = feature_name

            if i + 3 < len(parts):
                # We're inside a specific repo worktree
                repo_name = parts[i + 3]
                repo_path = Path(*parts[:i + 4])

                ctx.context_type = "repo_worktree"
                ctx.repo_paths = [repo_path]
                ctx.repo_names = [repo_name]
                ctx.branch = _safe_branch(repo_path)
            else:
                # We're at the feature directory level — find all repo worktrees
                ctx.context_type = "feature_dir"
                if feature_dir.exists():
                    for child in sorted(feature_dir.iterdir()):
                        if child.is_dir() and (child / ".git").exists():
                            ctx.repo_paths.append(child)
                            ctx.repo_names.append(child.name)
                if ctx.repo_paths:
                    ctx.branch = _safe_branch(ctx.repo_paths[0])
            return


def _detect_repo_context(ctx: CanopyContext) -> None:
    """Check if cwd is inside a normal repo in a canopy workspace."""
    path = ctx.cwd

    # Walk up looking for .git
    current = path
    while True:
        if (current / ".git").exists():
            # Found a repo — is it inside a canopy workspace?
            parent = current.parent
            ws_root = _find_workspace_root(parent)
            if ws_root:
                ctx.workspace_root = ws_root
                ctx.context_type = "repo"
                ctx.repo_paths = [current]
                ctx.repo_names = [current.name]
                ctx.branch = _safe_branch(current)

                # Try to detect feature from branch name
                if ctx.branch and ctx.branch not in ("main", "master", "(detached)"):
                    ctx.feature = ctx.branch
            return

        parent = current.parent
        if parent == current:
            break
        current = parent


def _detect_workspace_root(ctx: CanopyContext) -> None:
    """Check if cwd is a workspace root (has canopy.toml)."""
    ws_root = _find_workspace_root(ctx.cwd)
    if ws_root and ws_root == ctx.cwd:
        ctx.workspace_root = ws_root
        ctx.context_type = "workspace_root"

        # Find all repos at the workspace level
        try:
            from .config import load_config
            config = load_config(ws_root)
            for rc in config.repos:
                abs_path = (ws_root / rc.path).resolve()
                if abs_path.exists():
                    ctx.repo_paths.append(abs_path)
                    ctx.repo_names.append(rc.name)
        except Exception:
            pass


def _find_workspace_root(start: Path) -> Path | None:
    """Walk up from start looking for canopy.toml."""
    current = start.resolve()
    while True:
        if (current / "canopy.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _safe_branch(repo_path: Path) -> str | None:
    """Get current branch, returning None on error."""
    try:
        return git.current_branch(repo_path)
    except Exception:
        return None
