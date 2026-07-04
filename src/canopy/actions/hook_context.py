"""SessionStart brief — one compact block injected into a new session.

Evidence: 111 midway branch switches in 35 days, 87 after 10+ edits. The
mismatch must be visible BEFORE the agent reads a single file. Keep this
under ~10 lines: it lands in every session's context budget.
"""
from __future__ import annotations

from ..workspace.workspace import Workspace


def context_brief(workspace: Workspace) -> str:
    from . import slots as slots_mod

    state = slots_mod.read_state(workspace)
    canonical = state.canonical.feature if state and state.canonical else None
    lines = [
        f"canopy: workspace '{workspace.config.name}' — "
        f"canonical feature: {canonical or '(none)'}",
    ]
    for rs in sorted(workspace.repos, key=lambda r: r.config.name):
        name = rs.config.name
        if not rs.abs_path.exists():
            lines.append(f"  {name} → (missing on disk)")
            continue
        dirty = f"{rs.dirty_count} dirty" if rs.is_dirty else "clean"
        lines.append(f"  {name} → {rs.current_branch} ({dirty})")
    if state and state.slots:
        for sid, entry in sorted(state.slots.items()):
            lines.append(f"  slot {sid} → {entry.feature}")
    lines.append(
        "  Before any work: confirm the branch above matches this chat's "
        "ticket. If not, run `canopy switch <feature>` FIRST."
    )
    return "\n".join(lines)
