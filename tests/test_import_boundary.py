"""Agent-core must never import the management surface.

Static source scan (catches lazy/function-local imports too). This is the
phase-5 decoupling gate. When a management module still physically lives
under canopy/actions/ (before Pass 2 moves it), it is NOT in canopy.management
yet, so referencing it by its actions path would slip past a naive check —
that is why AGENT_CORE is an explicit allowlist of the modules that must stay
clean, and MANAGEMENT_NAMES is the set of module basenames that must not
appear in them regardless of path.
"""
import importlib
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "canopy"

AGENT_CORE = [
    "actions/registry.py", "actions/switch.py", "actions/switch_preflight.py",
    "actions/commit.py", "actions/push.py", "actions/slots.py",
    "actions/slot_policy.py", "actions/slot_bootstrap.py", "actions/reclaim.py",
    "actions/bootstrap.py", "actions/aliases.py", "actions/drift.py",
    "actions/stash.py", "actions/pr_map.py", "actions/repo_paths.py",
    "actions/ide_workspace.py", "actions/preflight_state.py",
    "actions/start.py", "actions/join.py", "actions/doctor.py",
    "features/coordinator.py", "agent/runner.py",
]

# Management module basenames that agent-core must not reference.
MANAGEMENT_NAMES = [
    "review_filter", "review_ops", "draft_replies", "thread_actions",
    "thread_resolutions", "bot_status", "bot_resolutions", "historian",
    "resume", "last_visit", "ship", "conflicts", "slot_details", "reads",
    "feature_state",
    # triage is split: pr_map is core; the triage *tiers* module is management.
    "triage",
]


def _refs(text: str, name: str) -> bool:
    patterns = [
        r"canopy\.management",
        r"from \.\.?management",
        rf"import\s+{re.escape(name)}\b",
        rf"from\s+[.\w]*\b{re.escape(name)}\s+import",
    ]
    return any(re.search(p, text) for p in patterns)


def test_agent_core_never_imports_management():
    violations = []
    for rel in AGENT_CORE:
        p = SRC / rel
        if not p.exists():
            continue
        text = p.read_text()
        for name in MANAGEMENT_NAMES:
            if _refs(text, name):
                violations.append(f"{rel} references management module '{name}'")
    assert not violations, "\n".join(violations)
