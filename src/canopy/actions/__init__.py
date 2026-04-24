"""Actions: completion-driven recipes that compose tools.

Every action accepts semantic context (feature, repo) and runs preconditions
→ steps → completion verification. Failures are returned as structured
BlockerError instances that consumers (CLI, MCP, extension) render or react
to in a uniform way.
"""
from .errors import (
    ActionError,
    BlockerError,
    FailedError,
    FixAction,
)

__all__ = ["ActionError", "BlockerError", "FailedError", "FixAction"]
