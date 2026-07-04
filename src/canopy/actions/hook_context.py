"""SessionStart brief — one compact block injected into a new session.

Evidence: 111 midway branch switches in 35 days, 87 after 10+ edits. The
mismatch must be visible BEFORE the agent reads a single file. Keep this
under ~10 lines: it lands in every session's context budget.
"""
from __future__ import annotations

import re

from ..workspace.workspace import Workspace

_SLOT_NUM = re.compile(r"worktree-(\d+)$")


def _slot_sort_key(sid: str) -> tuple[int, int, str]:
    """Sort worktree-N slots numerically; other ids fall back to name order."""
    m = _SLOT_NUM.match(sid)
    return (0, int(m.group(1)), "") if m else (1, 0, sid)


def context_brief(workspace: Workspace) -> str:
    from . import slots as slots_mod
    from . import active as active_mod
    from .advisories import compute_advisories

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
        for sid in sorted(state.slots, key=_slot_sort_key):
            lines.append(f"  slot {sid} → {state.slots[sid].feature}")
    active_feat = (state.canonical.feature if state and state.canonical
                   else active_mod.get_active(workspace))
    for adv in compute_advisories(workspace, active_feat):
        lines.append(f"  ⚠ {adv['message']}")
    lines.append(
        "  Before any work: confirm the branch above matches this chat's "
        "ticket. If not, run `canopy switch <feature>` FIRST."
    )
    return "\n".join(lines)
