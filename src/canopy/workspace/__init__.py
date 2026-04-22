"""Workspace configuration and discovery."""
from .config import WorkspaceConfig, RepoConfig, load_config, validate_config
from .workspace import Workspace, RepoState
from .discovery import discover_repos, generate_toml
