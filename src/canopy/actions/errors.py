"""Structured, actionable errors for canopy actions.

The design contract: every action error carries enough machine-readable
context that the consumer (a human reading CLI output, or an agent reading
MCP JSON) can act on it without parsing prose. Same shape across surfaces.

A BlockerError is a precondition failure: the action refused to start.
A FailedError is a mid-flight failure: the action started but couldn't
complete. Both serialize identically; consumers tell them apart by ``status``.

Error contract::

    {
      "status":      "blocked" | "failed",
      "code":        "drift_detected" | "preflight_failed" | ...,
      "what":        "human-readable summary",
      "expected":    {...},          # action-specific
      "actual":      {...},          # action-specific
      "fix_actions": [FixAction...], # ordered, most-recommended first
      "details":     {...},          # extra context
    }

CLI renders this via ``canopy.cli.render.render_blocker``. MCP returns the
dict from ``to_dict`` directly to the agent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FixAction:
    """A suggested next step the user or agent can take to unblock the action.

    ``safe=True`` means an agent can run this without further user
    confirmation (e.g., a clean realign). ``safe=False`` means the fix
    might lose work or affect remote state, and a human should approve
    first (e.g., ``--force`` deletes, force-push).
    """
    action: str                       # canopy action name, e.g., "realign"
    args: dict[str, Any] = field(default_factory=dict)
    safe: bool = True
    preview: str | None = None        # one-line description of what'd happen

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "args": dict(self.args),
            "safe": self.safe,
            "preview": self.preview,
        }


class ActionError(Exception):
    """Base class for canopy action errors.

    Subclasses set ``STATUS`` (``"blocked"`` or ``"failed"``) and provide
    a ``code`` plus the structured fields. Raise; the calling layer catches
    and either re-raises (Python consumers), serializes (MCP), or renders
    (CLI).
    """
    STATUS: str = "failed"

    def __init__(
        self,
        code: str,
        what: str,
        *,
        expected: Any = None,
        actual: Any = None,
        fix_actions: list[FixAction] | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(f"{self.STATUS}: {code}: {what}")
        self.code = code
        self.what = what
        self.expected = expected
        self.actual = actual
        self.fix_actions: list[FixAction] = list(fix_actions or [])
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "status": self.STATUS,
            "code": self.code,
            "what": self.what,
            "fix_actions": [f.to_dict() for f in self.fix_actions],
        }
        if self.expected is not None:
            out["expected"] = self.expected
        if self.actual is not None:
            out["actual"] = self.actual
        if self.details:
            out["details"] = self.details
        return out


class BlockerError(ActionError):
    """Action refused to start because a precondition failed.

    Raised before any side effects. The action's state hasn't changed.
    Callers should rely on ``fix_actions`` to recover.
    """
    STATUS = "blocked"


class FailedError(ActionError):
    """Action started but couldn't complete cleanly.

    May have partial side effects (some repos updated, others not). The
    ``details`` field SHOULD include per-repo status so the caller can
    reason about what's left to do.
    """
    STATUS = "failed"
