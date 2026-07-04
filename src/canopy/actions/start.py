"""canopy start <alias> — begin new work (lazy).

Resolves the alias (Linear best-effort), creates the feature record with
ZERO repos by default (lazy growth; repos join later via `canopy join`),
marks it the intended focus, and returns fresh context. Idempotent: an
existing feature resumes.
"""
from __future__ import annotations

from typing import Any

from ..workspace.workspace import Workspace


def start(workspace: Workspace, alias: str,
          repos: list[str] | None = None) -> dict[str, Any]:
    from . import active as active_mod
    from .registry import context as registry_context
    from ..features.coordinator import FeatureCoordinator

    coord = FeatureCoordinator(workspace)
    features = coord._load_features()

    name = alias
    linear_issue = linear_title = linear_url = ""
    degraded = False
    if "-" in alias and alias.split("-")[-1].isdigit():
        try:
            from ..integrations import linear
            issue = linear.get_issue(workspace.config.root, alias)
            linear_issue = alias
            linear_title = issue.get("title", "")
            linear_url = issue.get("url", "")
        except Exception:
            degraded = True

    status = "resumed" if name in features else "created"
    if status == "created":
        coord.create(name, repos=repos if repos is not None else [],
                     linear_issue=linear_issue, linear_title=linear_title,
                     linear_url=linear_url)

    active_mod.set_active(workspace, name)
    return {"feature": name, "status": status, "degraded": degraded,
            "context": registry_context(workspace)}
