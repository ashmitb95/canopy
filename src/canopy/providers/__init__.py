"""Issue-provider injection (M5).

Workspaces opt into a provider via the ``[issue_provider]`` block in
``canopy.toml``. The action layer obtains the configured provider via
:func:`get_issue_provider` — it never imports a provider module directly.

See ``docs/architecture/providers.md`` for the design.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .types import Issue, IssueProvider, IssueProviderError, IssueNotFoundError, ProviderNotConfigured

if TYPE_CHECKING:
    from ..workspace.workspace import Workspace

__all__ = [
    "Issue",
    "IssueProvider",
    "IssueProviderError",
    "IssueNotFoundError",
    "ProviderNotConfigured",
    "get_issue_provider",
    "register_provider",
    "available_providers",
]


# Lazy-imported registry. Backends are imported on first use to avoid
# pulling in MCP / gh CLI machinery for every action.
_REGISTRY: dict[str, str] = {
    "linear": "canopy.providers.linear.LinearProvider",
    "github_issues": "canopy.providers.github_issues.GitHubIssuesProvider",
}

# Per-workspace cache. Keyed on the workspace root path so multi-workspace
# MCP sessions don't share instances.
_INSTANCES: dict[Path, IssueProvider] = {}


def register_provider(name: str, dotted_path: str) -> None:
    """Register a third-party provider class. Out of band from canopy.toml.

    Reserved for future entry-point discovery; v1 only ships bundled
    providers but exposing this avoids a refactor when entry points land.
    """
    _REGISTRY[name] = dotted_path
    # Drop any cached instance for that name.
    for path, instance in list(_INSTANCES.items()):
        if type(instance).__name__ == dotted_path.rsplit(".", 1)[-1]:
            _INSTANCES.pop(path, None)


def available_providers() -> list[str]:
    """Sorted list of registered provider names."""
    return sorted(_REGISTRY.keys())


def get_issue_provider(workspace: "Workspace") -> IssueProvider:
    """Return the configured issue provider for the workspace.

    Cached per-workspace; constructed lazily on first access.

    Raises:
        ProviderNotConfigured: when ``[issue_provider]`` references an
            unknown name. Carries the list of available providers so the
            agent can suggest the right one.
    """
    root = workspace.config.root
    if root in _INSTANCES:
        return _INSTANCES[root]

    config = workspace.config.issue_provider
    name = config.name
    dotted = _REGISTRY.get(name)
    if dotted is None:
        raise ProviderNotConfigured(
            f"Unknown issue provider '{name}'. "
            f"Available: {', '.join(available_providers())}",
        )

    cls = _import(dotted)
    # Backends accept their config dict as a positional argument plus
    # ``workspace_root`` as a kwarg. Backends that don't need the root
    # (e.g. a hypothetical purely-credential-driven provider) can ignore
    # it via **kwargs.
    instance = cls(config.options, workspace_root=root)
    _INSTANCES[root] = instance
    return instance


def _import(dotted_path: str):
    """Resolve a 'module.Class' string to the class object."""
    module_path, _, attr = dotted_path.rpartition(".")
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, attr)


def _clear_cache() -> None:
    """Clear the per-workspace instance cache. Test-only."""
    _INSTANCES.clear()
