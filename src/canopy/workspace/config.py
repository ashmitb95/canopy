"""
Parse and validate canopy.toml workspace configuration.
"""
from __future__ import annotations

import sys
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigNotFoundError(Exception):
    """No canopy.toml found in the directory tree."""


class ConfigError(Exception):
    """Invalid canopy.toml content."""


@dataclass
class RepoConfig:
    """Configuration for a single repository in the workspace."""
    name: str
    path: str               # relative path from workspace root
    role: str = ""           # optional: backend, frontend, shared, infra
    lang: str = ""           # optional: primary language
    default_branch: str = "main"
    is_worktree: bool = False       # True if this is a linked worktree
    worktree_main: str | None = None  # path to main working tree (if worktree)


@dataclass
class WorkspaceConfig:
    """Parsed workspace configuration."""
    name: str
    repos: list[RepoConfig]
    root: Path              # absolute path to workspace root
    max_worktrees: int = 0  # 0 = unlimited


def load_config(path: Path | None = None) -> WorkspaceConfig:
    """Find and parse canopy.toml.

    If no path is given, walks up from cwd looking for canopy.toml.
    Raises ConfigNotFoundError if none is found.
    Raises ConfigError if the file is malformed.
    """
    if path is not None:
        toml_path = path if path.name == "canopy.toml" else path / "canopy.toml"
    else:
        toml_path = _find_config()

    if not toml_path.exists():
        raise ConfigNotFoundError(f"No canopy.toml found at {toml_path}")

    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Invalid TOML in {toml_path}: {e}") from e

    return _parse_config(data, toml_path.parent.resolve())


def _find_config() -> Path:
    """Walk up from cwd looking for canopy.toml."""
    current = Path.cwd().resolve()
    while True:
        candidate = current / "canopy.toml"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            raise ConfigNotFoundError(
                "No canopy.toml found in current directory or any parent."
            )
        current = parent


def _parse_config(data: dict[str, Any], root: Path) -> WorkspaceConfig:
    """Parse raw TOML dict into WorkspaceConfig."""
    workspace = data.get("workspace", {})
    name = workspace.get("name")
    if not name:
        raise ConfigError("Missing [workspace] name in canopy.toml")

    repos_data = data.get("repos", [])
    if not repos_data:
        raise ConfigError("No [[repos]] entries in canopy.toml")

    repos = []
    seen_names: set[str] = set()
    for i, entry in enumerate(repos_data):
        repo_name = entry.get("name")
        if not repo_name:
            raise ConfigError(f"[[repos]] entry {i} missing 'name'")
        if not entry.get("path"):
            raise ConfigError(f"[[repos]] entry '{repo_name}' missing 'path'")
        if repo_name in seen_names:
            raise ConfigError(f"Duplicate repo name: '{repo_name}'")
        seen_names.add(repo_name)

        repos.append(RepoConfig(
            name=repo_name,
            path=entry["path"],
            role=entry.get("role", ""),
            lang=entry.get("lang", ""),
            default_branch=entry.get("default_branch", "main"),
        ))

    max_worktrees = workspace.get("max_worktrees", 0)

    return WorkspaceConfig(name=name, repos=repos, root=root, max_worktrees=max_worktrees)


# ── Workspace settings (keys under [workspace]) ────────────────────────

# Settings that can be read/written via `canopy config`
WORKSPACE_SETTINGS = {
    "name": str,
    "max_worktrees": int,
}


def get_config_value(root: Path, key: str) -> Any:
    """Read a single workspace setting from canopy.toml."""
    if key not in WORKSPACE_SETTINGS:
        raise ConfigError(
            f"Unknown setting: '{key}'. "
            f"Available: {', '.join(sorted(WORKSPACE_SETTINGS))}"
        )
    toml_path = root / "canopy.toml"
    if not toml_path.exists():
        raise ConfigNotFoundError(f"No canopy.toml at {root}")
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    return data.get("workspace", {}).get(key)


def set_config_value(root: Path, key: str, value: str) -> Any:
    """Write a single workspace setting to canopy.toml.

    Handles type coercion based on WORKSPACE_SETTINGS.
    Returns the coerced value.
    """
    if key not in WORKSPACE_SETTINGS:
        raise ConfigError(
            f"Unknown setting: '{key}'. "
            f"Available: {', '.join(sorted(WORKSPACE_SETTINGS))}"
        )

    expected_type = WORKSPACE_SETTINGS[key]
    try:
        if expected_type == int:
            coerced = int(value)
        else:
            coerced = value
    except (ValueError, TypeError):
        raise ConfigError(f"Invalid value for '{key}': expected {expected_type.__name__}")

    toml_path = root / "canopy.toml"
    if not toml_path.exists():
        raise ConfigNotFoundError(f"No canopy.toml at {root}")

    content = toml_path.read_text()

    # Try to update existing key under [workspace]
    import re
    # Match: key = value (with optional quotes for strings)
    pattern = rf'^({re.escape(key)}\s*=\s*).*$'

    # Find lines within the [workspace] section
    lines = content.split("\n")
    in_workspace = False
    updated = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[workspace]":
            in_workspace = True
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            # Hit a new section — if we haven't updated yet, insert before this
            if in_workspace and not updated:
                # Insert the key before this section
                formatted = _format_toml_value(key, coerced)
                lines.insert(i, formatted)
                updated = True
            in_workspace = False
            continue
        if in_workspace and re.match(pattern, stripped):
            lines[i] = _format_toml_value(key, coerced)
            updated = True
            break

    # If still not updated, append to [workspace] section
    if not updated:
        # Find the [workspace] line and append after it
        for i, line in enumerate(lines):
            if line.strip() == "[workspace]":
                lines.insert(i + 1, _format_toml_value(key, coerced))
                updated = True
                break

    if not updated:
        raise ConfigError("Could not find [workspace] section in canopy.toml")

    toml_path.write_text("\n".join(lines))
    return coerced


def get_all_config(root: Path) -> dict[str, Any]:
    """Read all workspace settings from canopy.toml."""
    toml_path = root / "canopy.toml"
    if not toml_path.exists():
        raise ConfigNotFoundError(f"No canopy.toml at {root}")
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    ws = data.get("workspace", {})
    return {k: ws.get(k) for k in WORKSPACE_SETTINGS}


def _format_toml_value(key: str, value: Any) -> str:
    """Format a key = value line for TOML."""
    if isinstance(value, int):
        return f"{key} = {value}"
    elif isinstance(value, str):
        return f'{key} = "{value}"'
    return f"{key} = {value}"


def validate_config(config: WorkspaceConfig) -> list[str]:
    """Validate a WorkspaceConfig and return a list of warnings.

    Returns an empty list if everything is valid.
    """
    warnings = []

    for repo in config.repos:
        abs_path = (config.root / repo.path).resolve()
        if not abs_path.exists():
            warnings.append(f"Repo '{repo.name}': path does not exist: {abs_path}")
        elif not (abs_path / ".git").exists():
            warnings.append(f"Repo '{repo.name}': not a git repository: {abs_path}")

    return warnings
