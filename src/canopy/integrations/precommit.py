"""
Pre-commit hook detection and execution.

Detects whether a repo uses the pre-commit framework (.pre-commit-config.yaml),
bare git hooks (.git/hooks/pre-commit), or neither. Runs whichever is present
and returns structured results.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class PrecommitError(Exception):
    """A pre-commit hook failed."""
    def __init__(self, message: str, output: str = "", returncode: int = 1):
        super().__init__(message)
        self.output = output
        self.returncode = returncode


def detect_precommit(repo_path: Path) -> str:
    """Detect which pre-commit system a repo uses.

    Returns:
        "framework" — .pre-commit-config.yaml exists (pre-commit framework)
        "git_hook" — .git/hooks/pre-commit exists and is executable
        "none" — no pre-commit hooks detected
    """
    # Check for pre-commit framework
    if (repo_path / ".pre-commit-config.yaml").exists():
        return "framework"

    # Check for bare git hook
    # Handle both normal repos (.git is directory) and worktrees (.git is file)
    git_path = repo_path / ".git"
    if git_path.is_dir():
        hook = git_path / "hooks" / "pre-commit"
        if hook.exists() and _is_executable(hook):
            return "git_hook"
    elif git_path.is_file():
        # Worktree — .git is a file pointing to the main repo's .git dir
        # Hooks live in the main repo's hooks dir, but git resolves this
        # automatically when we run `git hook run`
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, cwd=repo_path,
        )
        if result.returncode == 0:
            common_dir = (repo_path / result.stdout.strip()).resolve()
            hook = common_dir / "hooks" / "pre-commit"
            if hook.exists() and _is_executable(hook):
                return "git_hook"

    return "none"


def _is_executable(path: Path) -> bool:
    """Check if a file is executable."""
    import os
    return os.access(path, os.X_OK)


def run_precommit(repo_path: Path, augments: dict | None = None) -> dict:
    """Run pre-commit hooks for a repo.

    If ``augments`` contains ``preflight_cmd``, runs that command instead
    of the auto-detected hook system. Otherwise detects the hook system
    (pre-commit framework / git hook / none) and runs it.

    Returns a result dict with:
        type: "custom" | "framework" | "git_hook" | "none"
        passed: bool
        output: str (combined stdout + stderr)
        applied_augment: bool (True iff preflight_cmd from augments ran)

    Does not raise on hook failure — the caller decides what to do.
    """
    custom_cmd = (augments or {}).get("preflight_cmd")
    if custom_cmd:
        return _run_custom_preflight(repo_path, str(custom_cmd))

    hook_type = detect_precommit(repo_path)

    if hook_type == "none":
        return {
            "type": "none",
            "passed": True,
            "output": "No pre-commit hooks detected.",
            "applied_augment": False,
        }

    if hook_type == "framework":
        result = _run_framework(repo_path)
    else:
        result = _run_git_hook(repo_path)
    result["applied_augment"] = False
    return result


def _run_custom_preflight(repo_path: Path, command: str) -> dict:
    """Run a user-configured preflight command via the shell.

    Honors the augment's ``preflight_cmd`` literal — supports pipes /
    chaining (e.g. ``ruff check . && pyright``) by passing through ``sh -c``.
    """
    result = subprocess.run(
        ["sh", "-c", command],
        capture_output=True,
        text=True,
        cwd=repo_path,
        timeout=120,
    )
    output = result.stdout
    if result.stderr:
        output += "\n" + result.stderr
    return {
        "type": "custom",
        "passed": result.returncode == 0,
        "output": output.strip(),
        "applied_augment": True,
        "command": command,
    }


def _run_framework(repo_path: Path) -> dict:
    """Run `pre-commit run --all-files`."""
    result = subprocess.run(
        ["pre-commit", "run", "--all-files"],
        capture_output=True,
        text=True,
        cwd=repo_path,
        timeout=120,
    )

    output = result.stdout
    if result.stderr:
        output += "\n" + result.stderr

    return {
        "type": "framework",
        "passed": result.returncode == 0,
        "output": output.strip(),
    }


def _run_git_hook(repo_path: Path) -> dict:
    """Run git hook via `git hook run pre-commit`."""
    # Try `git hook run` first (Git 2.36+), fall back to direct execution
    result = subprocess.run(
        ["git", "hook", "run", "pre-commit"],
        capture_output=True,
        text=True,
        cwd=repo_path,
        timeout=120,
    )

    # Check if `git hook run` isn't available (older Git versions)
    stderr_lower = result.stderr.lower()
    needs_fallback = (
        result.returncode != 0
        and ("not a git command" in stderr_lower
             or "not found" in stderr_lower
             or "unknown command" in stderr_lower)
    )

    if needs_fallback:
        # Direct execution fallback
        hook_path = _resolve_hook_path(repo_path)
        if hook_path and hook_path.exists():
            result = subprocess.run(
                [str(hook_path)],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=120,
            )
        else:
            return {
                "type": "git_hook",
                "passed": True,
                "output": "Git hook not found at resolved path.",
            }

    output = result.stdout
    if result.stderr:
        output += "\n" + result.stderr

    return {
        "type": "git_hook",
        "passed": result.returncode == 0,
        "output": output.strip(),
    }


def _resolve_hook_path(repo_path: Path) -> Path | None:
    """Resolve the pre-commit hook path, handling worktrees."""
    git_path = repo_path / ".git"
    if git_path.is_dir():
        return git_path / "hooks" / "pre-commit"

    # Worktree
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        capture_output=True, text=True, cwd=repo_path,
    )
    if result.returncode == 0:
        common_dir = (repo_path / result.stdout.strip()).resolve()
        return common_dir / "hooks" / "pre-commit"

    return None


def run_precommit_all(repo_paths: dict[str, Path]) -> dict[str, dict]:
    """Run pre-commit hooks across multiple repos.

    Args:
        repo_paths: {repo_name: repo_path}

    Returns:
        {repo_name: {type, passed, output}}
    """
    results = {}
    for name, path in repo_paths.items():
        try:
            results[name] = run_precommit(path)
        except subprocess.TimeoutExpired:
            results[name] = {
                "type": detect_precommit(path),
                "passed": False,
                "output": "Pre-commit hook timed out (120s).",
            }
        except Exception as e:
            results[name] = {
                "type": "error",
                "passed": False,
                "output": f"Error running pre-commit: {e}",
            }
    return results
