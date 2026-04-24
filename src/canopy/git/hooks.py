"""Install, uninstall, and read canopy git hooks.

Canopy installs a post-checkout hook in every managed repo and worktree so
it has real-time ground truth of HEAD per repo without polling. The hook
writes to .canopy/state/heads.json under the workspace root.
"""
from __future__ import annotations

import json
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

_HOOK_NAME = "post-checkout"
_CHAINED_NAME = "post-checkout.canopy-chained"
_MARKER = "__CANOPY_HOOK_MARKER__"
_TEMPLATE_PATH = Path(__file__).parent / "templates" / "post-checkout.py"


@dataclass
class InstallResult:
    repo: str
    path: str
    action: str  # "installed", "reinstalled", "chained_existing"


def install_hook(repo_path: Path, repo_name: str, workspace_root: Path) -> InstallResult:
    """Install the canopy post-checkout hook in a repo or linked worktree.

    If a user hook already exists, it's moved to ``post-checkout.canopy-chained``
    and invoked after the canopy hook runs. If a previous canopy hook is
    present, it's replaced.
    """
    hooks_dir = resolve_hooks_dir(repo_path)
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / _HOOK_NAME

    template = _TEMPLATE_PATH.read_text()
    rendered = template.replace(
        '"__CANOPY_REPO__"', json.dumps(repo_name),
    ).replace(
        '"__CANOPY_WORKSPACE_ROOT__"', json.dumps(str(workspace_root.resolve())),
    )

    action = "installed"
    if hook_path.exists():
        existing = hook_path.read_text()
        if _MARKER in existing:
            action = "reinstalled"
        else:
            chained = hooks_dir / _CHAINED_NAME
            if chained.exists():
                chained.unlink()
            shutil.move(str(hook_path), str(chained))
            _make_executable(chained)
            action = "chained_existing"

    hook_path.write_text(rendered)
    _make_executable(hook_path)

    return InstallResult(repo=repo_name, path=str(hook_path), action=action)


@dataclass
class UninstallResult:
    repo: str
    action: str  # "uninstalled", "uninstalled_and_restored", "skipped", "not_installed"
    reason: str | None = None


def uninstall_hook(repo_path: Path, repo_name: str) -> UninstallResult:
    """Remove the canopy hook; restore any chained user hook."""
    hooks_dir = resolve_hooks_dir(repo_path)
    hook_path = hooks_dir / _HOOK_NAME
    chained = hooks_dir / _CHAINED_NAME

    if not hook_path.exists():
        return UninstallResult(repo=repo_name, action="not_installed")

    if _MARKER not in hook_path.read_text():
        return UninstallResult(
            repo=repo_name, action="skipped",
            reason="hook exists but is not a canopy hook",
        )

    hook_path.unlink()
    if chained.exists():
        shutil.move(str(chained), str(hook_path))
        _make_executable(hook_path)
        return UninstallResult(repo=repo_name, action="uninstalled_and_restored")
    return UninstallResult(repo=repo_name, action="uninstalled")


def hook_status(repo_path: Path) -> dict:
    """Inspect current hook state for a repo."""
    hooks_dir = resolve_hooks_dir(repo_path)
    hook_path = hooks_dir / _HOOK_NAME
    chained = hooks_dir / _CHAINED_NAME

    if not hook_path.exists():
        return {"installed": False, "hook_path": str(hook_path)}

    content = hook_path.read_text()
    return {
        "installed": _MARKER in content,
        "foreign_hook": _MARKER not in content,
        "chained_present": chained.exists(),
        "hook_path": str(hook_path),
    }


def read_heads_state(workspace_root: Path) -> dict:
    """Return ``{repo_name: {branch, sha, prev_sha, ts}}`` from the state file."""
    path = workspace_root / ".canopy" / "state" / "heads.json"
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def resolve_hooks_dir(repo_path: Path) -> Path:
    """Resolve the ``hooks`` dir git actually uses for this repo / worktree.

    Resolution order:
      1. ``core.hooksPath`` if set in the repo's config (e.g., Husky uses
         ``.husky/_``). Relative paths resolve against the repo root.
         Without this we'd install a hook git would never run.
      2. For a linked worktree, follow ``.git`` (file) → worktree gitdir →
         ``commondir`` → main ``.git/hooks``. Hooks are shared across all
         worktrees of a repo by default.
      3. Otherwise ``<repo>/.git/hooks``.
    """
    custom = _get_core_hooks_path(repo_path)
    if custom is not None:
        return custom

    git_path = repo_path / ".git"
    if git_path.is_file():
        contents = git_path.read_text().strip()
        if contents.startswith("gitdir:"):
            worktree_gitdir = Path(contents.split(":", 1)[1].strip())
            if not worktree_gitdir.is_absolute():
                worktree_gitdir = (repo_path / worktree_gitdir).resolve()
            commondir_file = worktree_gitdir / "commondir"
            if commondir_file.is_file():
                common = Path(commondir_file.read_text().strip())
                if not common.is_absolute():
                    common = (worktree_gitdir / common).resolve()
                return common / "hooks"
            return worktree_gitdir / "hooks"
    return git_path / "hooks"


def _get_core_hooks_path(repo_path: Path) -> Path | None:
    """Read ``core.hooksPath`` from the repo's config. Returns None if unset."""
    result = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=repo_path, capture_output=True, text=True, check=False,
    )
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        return None
    p = Path(value)
    if not p.is_absolute():
        p = (repo_path / p).resolve()
    return p


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
