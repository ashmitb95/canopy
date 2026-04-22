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


@dataclass
class WorkspaceConfig:
    """Parsed workspace configuration."""
    name: str
    repos: list[RepoConfig]
    root: Path              # absolute path to workspace root


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

    return WorkspaceConfig(name=name, repos=repos, root=root)


def validate_config(config: WorkspaceConfig) -> list[str]:
    """Validate a WorkspaceConfig and return a list of warnings.

    Returns an empty list if everything is valid.
    """
    warnings = []

    for repo in config.repos:
        abs_path = (config.root / repo.path).resolve()
        if not abs_path.exists():
            warnings.append(f"Repo '{repo.name}': path does not exist: {abs_path}")
        elif not (abs_path / ".git").exists() and not (abs_path / ".git").is_file():
            warnings.append(f"Repo '{repo.name}': not a git repository: {abs_path}")

    return warnings
