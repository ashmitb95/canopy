"""Agent-facing surface: tools that exist primarily to make agent tool
calls mistake-proof (path resolution, ad-hoc command exec, etc.)."""
from .runner import run_in_repo

__all__ = ["run_in_repo"]
