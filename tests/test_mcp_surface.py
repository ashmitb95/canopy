from canopy.mcp.server import mcp

KEEP_ACTIVE = {
    "version", "context", "start", "join", "run", "switch", "reclaim",
    "commit", "push", "preflight", "doctor", "drift",
    "stash_save_feature", "stash_pop_feature", "worktree_bootstrap",
}


def _registered():
    return {t.name for t in mcp._tool_manager.list_tools()}


def test_mcp_surface_is_exactly_the_core_15():
    assert _registered() == KEEP_ACTIVE


def test_no_management_tool_is_registered():
    for name in ("triage", "ship", "conflicts", "resolve_thread",
                 "feature_resume", "review_status", "review_comments",
                 "slots", "feature_list", "checkout", "log"):
        assert name not in _registered()
