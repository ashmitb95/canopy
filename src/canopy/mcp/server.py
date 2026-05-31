"""
Canopy MCP Server — expose workspace operations as MCP tools.

Run via stdio:
    canopy-mcp

Register in Claude Code / Cursor / etc as an MCP server with:
    {
        "mcpServers": {
            "canopy": {
                "command": "canopy-mcp",
                "env": { "CANOPY_ROOT": "/path/to/workspace" }
            }
        }
    }

The CANOPY_ROOT env var tells the server where to find canopy.toml.
If not set, it uses the current working directory.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..workspace.config import load_config, ConfigNotFoundError
from ..workspace.workspace import Workspace
from ..workspace.context import detect_context
from ..features.coordinator import FeatureCoordinator
from ..git import repo as git
from ..git import multi


# ── Server setup ─────────────────────────────────────────────────────────

mcp = FastMCP(
    "canopy",
    instructions="Workspace-first development orchestrator — coordinates Git across multiple repos. Use CANOPY_ROOT env var to point at the workspace.",
)


def _get_workspace() -> Workspace:
    """Load workspace from CANOPY_ROOT or cwd."""
    root = os.environ.get("CANOPY_ROOT")
    path = Path(root) if root else None
    try:
        config = load_config(path)
    except ConfigNotFoundError as e:
        raise ValueError(
            f"No canopy.toml found. Set CANOPY_ROOT or run from a canopy workspace. ({e})"
        )
    return Workspace(config)


# ── Meta tools ───────────────────────────────────────────────────────────

# Bump when canopy.toml schema changes in a way the extension/agent must know
# about. Independent of the package version.
_SCHEMA_VERSION = "1"


@mcp.tool()
def version() -> dict:
    """Report canopy versions for the doctor handshake.

    Returns:
        ``{cli_version, mcp_version, schema_version}``. ``cli_version`` is
        the ``canopy`` CLI as resolved from PATH (best-effort; empty string
        if not installed). ``mcp_version`` is the running MCP server's
        package version. ``schema_version`` covers the canopy.toml shape.
        The extension calls this once at startup to compare against its
        bundled expectation; the doctor uses it to detect drift between
        CLI and MCP installations.
    """
    import shutil
    import subprocess
    from .. import __version__

    cli_version = ""
    cli_path = shutil.which("canopy")
    if cli_path:
        try:
            out = subprocess.run(
                [cli_path, "--version"],
                capture_output=True, text=True, check=False, timeout=5,
            )
            if out.returncode == 0:
                # "canopy 0.1.0" → "0.1.0"
                parts = out.stdout.strip().split()
                cli_version = parts[-1] if parts else ""
        except (OSError, subprocess.TimeoutExpired):
            pass

    return {
        "cli_version": cli_version,
        "mcp_version": __version__,
        "schema_version": _SCHEMA_VERSION,
    }


# ── Workspace tools ──────────────────────────────────────────────────────

@mcp.tool()
def workspace_status() -> dict:
    """Get the full status of the canopy workspace.

    Returns repo names, current branches, dirty state, divergence
    from default branch, and active feature lanes. Slot occupancy
    (which feature is in each numbered worktree slot) is tracked
    separately — call ``worktree_info`` for the slot-keyed view.
    """
    ws = _get_workspace()
    ws.refresh()
    return ws.to_dict()


@mcp.tool()
def workspace_context(cwd: str | None = None) -> dict:
    """Detect canopy context from a directory path.

    Tells you which feature, repo, and branch you're in based on
    the directory. Useful for understanding worktree structure.

    Args:
        cwd: Directory to detect from. Defaults to CANOPY_ROOT.
    """
    path = Path(cwd) if cwd else None
    if path is None:
        root = os.environ.get("CANOPY_ROOT")
        path = Path(root) if root else None
    ctx = detect_context(cwd=path)
    return ctx.to_dict()


@mcp.tool()
def run(repo: str, command: str, feature: str | None = None,
        timeout_seconds: int = 60) -> dict:
    """Run a shell command in a canopy-managed repo, with directory resolution.

    Eliminates "cd to wrong path" agent mistakes. Pass the repo name and
    canopy resolves the working directory: if ``feature`` is set and a
    worktree exists for ``(feature, repo)``, runs in the worktree;
    otherwise runs in the repo's main path.

    Returns ``{exit_code, stdout, stderr, cwd, duration_ms}``. Confirm
    ``cwd`` matches your expectation in any post-call reasoning.

    Args:
        repo: name of the repo as configured in canopy.toml.
        command: shell command to run (e.g. ``"git status"``).
        feature: optional feature name; selects worktree path if applicable.
        timeout_seconds: kills the process after this many seconds (default 60).
    """
    from ..agent.runner import run_in_repo

    ws = _get_workspace()
    return run_in_repo(ws, repo=repo, command=command, feature=feature,
                       timeout_seconds=timeout_seconds)


@mcp.tool()
def feature_state(feature: str) -> dict:
    """Compute feature state + suggested next actions (dashboard backend).

    Returns one of: drifted, needs_work, in_progress, ready_to_commit,
    ready_to_push, awaiting_review, approved, no_prs.

    Composes drift detection (live git, not heads.json), dirty/clean
    state, ahead/behind, temporal-filtered review comments, and recorded
    preflight result into a single state + ordered next_actions list.
    Same logic the dashboard CTAs and the agent both consume.
    """
    from ..actions.feature_state import feature_state as _impl
    ws = _get_workspace()
    return _impl(ws, feature)


@mcp.tool()
def triage(author: str = "@me", repos: list[str] | None = None) -> dict:
    """Prioritized list of features needing user attention.

    Enumerates open PRs across all configured repos, groups by feature
    lane (explicit from features.json or implicit by shared branch),
    classifies each via the temporal review-comment filter, and orders
    by priority:

      changes_requested > review_required_with_bot_comments
                       > review_required > approved

    The agent's morning daily-loop entry point. `author='@me'` filters
    to the authenticated user's PRs (gh CLI shorthand).
    """
    from ..actions.triage import triage as _impl
    ws = _get_workspace()
    return _impl(ws, author=author, repos=repos)


@mcp.tool()
def switch(feature: str | None = None, release_current: bool = False,
           no_evict: bool = False, evict: str | None = None,
           evict_to: str | None = None, to_slot: str | None = None) -> dict:
    """Promote a feature to the canonical slot (Wave 3.0 canonical-slot model).

    Worktrees live in numbered slots (``.canopy/worktrees/worktree-N/``),
    not feature-named dirs. Slot identity is stable; feature occupancy is
    transient. If the target feature is already warm in a slot, switch uses
    a fast 5-op path (stash → checkout → pop in each repo). If the target is
    cold, the outgoing feature's slot is reused (or the lowest free slot is
    allocated for it).

    Two modes for what happens to the previously-canonical feature X:

      - **Active rotation (default)**: X evacuates to a warm worktree
        slot (stash → worktree-add → pop). Use when X still needs your
        attention soon — switching back is instant.
      - **Wind-down (release_current=True)**: X goes straight to cold
        (just the branch + a feature-tagged stash if there were dirty
        changes). Use when X is parked / finished and Y is the new
        focus.

    When active-rotation would exceed the warm-slot cap (default 2),
    canopy raises a structured BlockerError(code='worktree_cap_reached')
    with fix_actions: switch in wind-down mode, evict a specific LRU
    warm to cold (with auto-stash), or raise the cap. Use no_evict=True
    to refuse auto-eviction (raises the same blocker for the user to
    decide); use evict='<feature>' to override the LRU pick with a
    specific feature.

    See docs/concepts.md §4 for the full canonical-slot model.

    After this, calls without an explicit `feature` argument
    (canopy_run, feature_state, IDE openers) default to this feature.

    Returns {feature, mode, per_repo_paths, previously_canonical?,
    eviction?, branches_created?, migration?, per_repo, activated_at}
    on success, or a structured ``BlockerError``-shaped dict
    ``{status: "blocked", code, what, fix_actions, ...}`` when a
    precondition refuses the action (e.g. ``worktree_cap_reached``).
    Dashboards inspect ``status`` to render a modal with the fix actions.
    """
    from ..actions.switch import switch as _impl
    from ..actions.errors import ActionError
    ws = _get_workspace()
    try:
        return _impl(
            ws, feature,
            release_current=release_current,
            no_evict=no_evict,
            evict=evict,
            evict_to=evict_to,
            to_slot=to_slot,
        )
    except ActionError as e:
        # Surface BlockerError / FailedError as a structured response so
        # the dashboard can render the cap-reached modal (or any future
        # blocker) without parsing string repr. Same convention used by
        # linear_my_issues + ``feature_state`` warnings.
        return e.to_dict()


@mcp.tool()
def slot_load(
    feature: str, slot_id: str | None = None,
    replace: bool = False, bootstrap: bool = False,
) -> dict:
    """Warm a cold feature into a slot WITHOUT changing canonical.

    Use `switch` to actually make a feature the active workspace; use
    `slot_load` to pre-warm a slot for fast future switching, or to load
    a feature for inspection (e.g. before review) without disturbing the
    canonical.

    slot_id defaults to the lowest free slot. Raises worktree_cap_reached
    when all slots are full. With replace=True, evicts the slot's
    current occupant to cold first.
    """
    from ..actions.slot_load import slot_load as _impl
    return _impl(_get_workspace(), feature,
                 slot_id=slot_id, replace=replace, bootstrap=bootstrap)


@mcp.tool()
def slot_clear(slot_id: str) -> dict:
    """Evict the occupant of a slot to cold (with feature-tagged stash if dirty)."""
    from ..actions.slot_load import slot_clear as _impl
    return _impl(_get_workspace(), slot_id)


@mcp.tool()
def slot_swap(slot_a: str, slot_b: str) -> dict:
    """Exchange the occupants of two slots. Requires identical repo scope on both features."""
    from ..actions.slot_load import slot_swap as _impl
    return _impl(_get_workspace(), slot_a, slot_b)


@mcp.tool()
def commit(message: str = "", feature: str | None = None,
           repos: list[str] | None = None, paths: list[str] | None = None,
           no_hooks: bool = False, amend: bool = False,
           address: str | None = None,
           resolve_thread: bool | None = None) -> dict:
    """Commit across every repo in a feature lane with a single message (Wave 2.3).

    Defaults to the canonical feature when ``feature`` is omitted (reads
    ``.canopy/state/slots.json``). ``--paths`` filters staging
    to those files; otherwise stages all tracked changes (``git add -u``).

    Pre-flight: every in-scope repo must be on the feature's expected
    branch. Mismatches raise ``BlockerError(code='wrong_branch')`` with
    a per-repo expected/actual map; no commits fire.

    ``address`` (M3): a bot review comment id (numeric or GitHub URL).
    When set, the message is auto-suffixed with the comment title + URL
    and a resolution is recorded in ``.canopy/state/bot_resolutions.json``
    against the matching repo's commit SHA. Non-bot comments raise
    ``BlockerError(code='not_a_bot_comment')``.

    ``resolve_thread`` (T4): when ``address`` is set, controls whether the
    corresponding GitHub review thread is resolved after a successful commit.
    ``True`` forces resolve; ``False`` forces skip; ``None`` (default) defers
    to the workspace augment ``auto_resolve_threads_on_address``.

    Per-repo result statuses:
      - ``ok``           — committed; carries ``sha``, ``files_changed``.
      - ``nothing``      — no changes staged.
      - ``hooks_failed`` — pre-commit / commit-msg hook rejected; carries
                            tail of ``hook_output``. Other repos continue.
      - ``failed``       — git error (gpg, locked index, etc.).

    Returns ``{feature, results: {<repo>: {...}}, addressed?}`` on success,
    or a structured ``BlockerError``-shaped dict on pre-flight rejection.
    """
    from ..actions.commit import commit as _impl
    from ..actions.errors import ActionError
    ws = _get_workspace()
    try:
        return _impl(
            ws, message,
            feature=feature, repos=repos, paths=paths,
            no_hooks=no_hooks, amend=amend, address=address,
            resolve_thread=resolve_thread,
        )
    except ActionError as e:
        return e.to_dict()


@mcp.tool()
def bot_comments_status(feature: str | None = None) -> dict:
    """Per-feature rollup of bot review comments (M3).

    Returns ``{feature, repos: {<repo>: {pr_number, total, resolved,
    unresolved, threads}}, all_resolved, any_bot_comments}``. Bot threads
    are read live from open PRs; resolutions come from the persistent
    ``.canopy/state/bot_resolutions.json`` log written by
    ``commit --address``.
    """
    from ..actions.bot_status import bot_comments_status as _impl
    from ..actions.errors import ActionError
    ws = _get_workspace()
    try:
        return _impl(ws, feature=feature)
    except ActionError as e:
        return e.to_dict()


# ── Historian (M4) ──────────────────────────────────────────────────────


def _historian_feature(feature: str | None) -> tuple:
    """Resolve (workspace_root, feature_name) for a historian call.

    Falls back to the canonical feature when ``feature`` is omitted.
    """
    from ..actions import slots as slots_mod
    from ..actions.aliases import resolve_feature
    from ..actions.errors import BlockerError
    ws = _get_workspace()
    if feature:
        return ws.config.root, resolve_feature(ws, feature)
    state = slots_mod.read_state(ws)
    if state is None or state.canonical is None:
        raise BlockerError(
            code="no_canonical_feature",
            what="no active feature; pass `feature` or run `canopy switch <name>` first",
        )
    return ws.config.root, state.canonical.feature


@mcp.tool()
def historian_decide(feature: str | None = None,
                     decisions: list[dict] | None = None) -> dict:
    """Record one or more agent decisions in the feature's memory file (M4).

    ``decisions`` is a list of ``{"title": str, "rationale": str}`` dicts.
    Decisions are deduped per-session by title — calling the tool twice
    with the same title within a session is a no-op (the hybrid Stop-hook
    backup mechanism relies on this).
    """
    from ..actions import historian
    from ..actions.errors import ActionError
    try:
        root, name = _historian_feature(feature)
    except ActionError as e:
        return e.to_dict()
    out = []
    for d in (decisions or []):
        out.append(historian.record_decision(
            root, name, title=d.get("title", ""), rationale=d.get("rationale", ""),
        ))
    return {"feature": name, "results": out}


@mcp.tool()
def historian_pause(feature: str | None = None, reason: str = "") -> dict:
    """Record a pause / blocker for the feature (M4)."""
    from ..actions import historian
    from ..actions.errors import ActionError
    try:
        root, name = _historian_feature(feature)
    except ActionError as e:
        return e.to_dict()
    return {"feature": name, **historian.record_pause(root, name, reason=reason)}


@mcp.tool()
def historian_defer_comment(feature: str | None = None,
                            comment_id: str = "", reason: str = "") -> dict:
    """Mark a review comment as intentionally deferred (M4)."""
    from ..actions import historian
    from ..actions.errors import ActionError
    try:
        root, name = _historian_feature(feature)
    except ActionError as e:
        return e.to_dict()
    return {"feature": name, **historian.record_comment_deferred(
        root, name, comment_id=comment_id, reason=reason,
    )}


@mcp.tool()
def feature_memory(feature: str | None = None) -> dict:
    """Read the rendered feature memory as markdown (M4).

    Returns ``{feature, memory: <markdown or "">}`` — empty string when
    no memory has been recorded yet.
    """
    from ..actions import historian
    from ..actions.errors import ActionError
    try:
        root, name = _historian_feature(feature)
    except ActionError as e:
        return e.to_dict()
    return {"feature": name, "memory": historian.format_for_agent(root, name)}


@mcp.tool()
def historian_compact(feature: str | None = None,
                      keep_sessions: int = 5) -> dict:
    """Trim the Sessions section to the most-recent ``keep_sessions`` (M4).

    v1 is mechanical — it drops session entries beyond the cutoff while
    preserving the Resolutions log + PR context entries. A future LLM
    pass can replace this with summarized recaps; the storage shape is
    forward-compatible.
    """
    from ..actions import historian
    from ..actions.errors import ActionError
    try:
        root, name = _historian_feature(feature)
    except ActionError as e:
        return e.to_dict()
    return {"feature": name, **historian.compact(
        root, name, keep_sessions=keep_sessions,
    )}


@mcp.tool()
def push(feature: str | None = None, repos: list[str] | None = None,
         set_upstream: bool = False, force_with_lease: bool = False,
         dry_run: bool = False) -> dict:
    """Push the feature branch in every in-scope repo (Wave 2.3).

    Defaults to the canonical feature. Pre-flight raises
    ``BlockerError(code='no_upstream')`` if any in-scope repo lacks an
    upstream and ``set_upstream`` was not passed; the fix-action carries
    the same call args plus ``set_upstream=True`` so the agent retries
    mechanically.

    Per-repo result statuses:
      - ``ok``         — pushed; carries ``pushed_count``, ``ref``.
      - ``up_to_date`` — branch is already at upstream; nothing to push.
      - ``rejected``   — non-fast-forward without ``force_with_lease``.
      - ``failed``     — git error (network, auth, etc.).

    Returns ``{feature, results: {<repo>: {...}}}`` on success, or a
    structured ``BlockerError``-shaped dict on pre-flight rejection.
    """
    from ..actions.errors import ActionError
    from ..actions.push import push as _impl
    ws = _get_workspace()
    try:
        return _impl(
            ws,
            feature=feature, repos=repos,
            set_upstream=set_upstream,
            force_with_lease=force_with_lease,
            dry_run=dry_run,
        )
    except ActionError as e:
        return e.to_dict()


@mcp.tool()
def stash_save_feature(feature: str, message: str = "",
                        repos: list[str] | None = None) -> dict:
    """Stash dirty changes (incl. untracked) with a feature tag.

    Stash message becomes '[canopy <feature> @ <iso_ts>] <message>',
    parseable by stash_list_grouped / stash_pop_feature.
    """
    from ..actions.stash import save_for_feature
    ws = _get_workspace()
    return save_for_feature(ws, feature, message, repos=repos)


@mcp.tool()
def stash_list_grouped(feature: str | None = None) -> dict:
    """List stashes across repos, grouped by feature tag.

    Returns {by_feature: {<f>: [...]}, untagged: [...]}. Optional
    `feature` filter scopes to a single feature (untagged excluded).
    """
    from ..actions.stash import list_grouped
    ws = _get_workspace()
    return list_grouped(ws, feature=feature)


@mcp.tool()
def stash_pop_feature(feature: str, repos: list[str] | None = None) -> dict:
    """Pop the most recent feature-tagged stash per repo."""
    from ..actions.stash import pop_feature
    ws = _get_workspace()
    return pop_feature(ws, feature, repos=repos)


@mcp.tool()
def linear_get_issue(alias: str) -> dict:
    """Deprecated. Use ``issue_get`` instead.

    Provider-agnostic alias surviving from the pre-M5 era. Forwards to
    the configured issue provider via ``actions.reads.linear_get_issue``;
    same return shape (``{alias, issue_id, title, state, url, description, raw}``).
    Will be removed in a future release.

    Accepts:
      - Provider-native issue ID (Linear ``"SIN-7"``, GH ``"#142"``)
      - Feature alias whose lane has a linked issue
    """
    from ..actions.reads import linear_get_issue as _impl
    ws = _get_workspace()
    return _impl(ws, alias)


@mcp.tool()
def github_get_pr(alias: str) -> dict:
    """Fetch PR data per repo for an alias.

    Accepts:
      - Feature alias (e.g. 'TEAM-101') -> all PRs in the lane
      - <repo>#<pr_number> (e.g. 'api#142') -> specific PR
      - GitHub PR URL -> specific PR
    """
    from ..actions.reads import github_get_pr as _impl
    ws = _get_workspace()
    return _impl(ws, alias)


@mcp.tool()
def github_get_branch(alias: str, repo: str | None = None) -> dict:
    """Fetch branch info (HEAD sha, ahead/behind, upstream) per repo.

    Accepts:
      - Feature alias -> per-repo branches from the feature lane
      - <repo>:<branch> -> specific branch in specific repo

    Pass `repo` to filter feature-alias results to one repo.
    """
    from ..actions.reads import github_get_branch as _impl
    ws = _get_workspace()
    return _impl(ws, alias, repo=repo)


@mcp.tool()
def github_get_pr_comments(alias: str) -> dict:
    """Fetch temporally classified PR review comments per repo.

    Same shape as `review_comments` (per-repo actionable_threads /
    likely_resolved_threads / resolved_thread_count / latest_commit_at)
    but accepts the full alias surface — feature alias, <repo>#<n>, or PR URL.

    Bot threads are kept; the temporal classifier handles staleness regardless
    of author.
    """
    from ..actions.reads import github_get_pr_comments as _impl
    ws = _get_workspace()
    return _impl(ws, alias)


@mcp.tool()
def doctor(
    fix: bool = False,
    fix_categories: list[str] | None = None,
    feature: str | None = None,
    clean_vsix: bool = False,
) -> dict:
    """Diagnose workspace + install integrity; optionally repair.

    Returns ``{issues, summary, fixed, skipped, ...}``. ``issues`` is a list
    of typed records ``{code, severity, what, expected?, actual?, repo?,
    feature?, fix_action?, auto_fixable, details?}``. ``summary`` rolls up
    counts by severity. ``fixed`` and ``skipped`` are populated when
    ``fix=True`` (they are empty otherwise).

    Diagnostic codes (16 categories):
      State-integrity: heads_stale, active_feature_orphan,
        active_feature_path_missing, worktree_orphan, worktree_missing,
        hook_missing, hook_chained_unsafe, preflight_stale,
        features_unknown_repo, branches_missing.
      Install-staleness: cli_stale, mcp_stale, mcp_missing_in_workspace,
        skill_missing, skill_stale, vsix_duplicates.

    Use this as the recovery entry point when any other canopy operation
    returns an unexpected error — most "something is off" cases trace to
    one of the categories above.

    Args:
        fix: repair every auto-fixable issue.
        fix_categories: limit ``fix`` to a subset of categories
            (heads, active_feature, worktrees, hooks, preflight, features,
            branches, cli, mcp, skill, vsix). Implies ``fix=True``.
        feature: scope feature-bearing checks to one feature.
        clean_vsix: required to repair ``vsix_duplicates`` (destructive).
    """
    from ..actions.doctor import doctor as _doctor

    ws = _get_workspace()
    return _doctor(
        ws,
        fix=fix,
        fix_categories=fix_categories,
        feature=feature,
        clean_vsix=clean_vsix,
    )


@mcp.tool()
def pr_checks(alias: str) -> dict:
    """Fetch CI check runs for a PR alias (M10).

    ``alias`` is the universal-resolved form: feature alias,
    ``<repo>#<n>``, or PR URL. Returns the rolled-up status plus the raw
    per-check list — useful when the rolled-up ``ci_status`` on
    ``feature_state.repos[*].pr`` isn't enough.
    """
    from ..actions.aliases import resolve_pr_targets
    from ..integrations import github as gh

    ws = _get_workspace()
    targets = resolve_pr_targets(ws, alias)
    out = []
    for t in targets:
        rollup, raw = gh.get_pr_checks(
            ws.config.root, t.owner, t.repo_slug, t.pr_number,
        )
        out.append({
            "repo": t.repo,
            "pr_number": t.pr_number,
            "ci_status": rollup,
            "checks": raw,
        })
    return {"alias": alias, "results": out}


@mcp.tool()
def worktree_bootstrap(
    feature: str,
    force: bool = False,
    steps: list[str] | None = None,
) -> dict:
    """Bootstrap a feature's worktrees — env-files, deps, IDE workspace (M6).

    Three optional steps, off by default unless the matching config is
    set in canopy.toml: env-file copy from main checkout into the
    worktree, dep install via per-repo ``install_cmd``, and a
    ``.canopy/workspaces/<feature>.code-workspace`` file when
    ``[workspace] ide = "vscode"`` is set.

    Args:
        feature: feature alias.
        force: overwrite existing destination env files.
        steps: subset of {"env", "deps", "ide"} to run; default = all three.
    """
    from ..actions.bootstrap import bootstrap_feature

    ws = _get_workspace()
    return bootstrap_feature(ws, feature, force=force, steps=steps)


@mcp.tool()
def ship(
    feature: str | None = None,
    repos: list[str] | None = None,
    draft: bool = False,
    reviewers: list[str] | None = None,
    dry_run: bool = False,
    base: str | None = None,
) -> dict:
    """Open or update one PR per repo in the canonical feature (M8 / Wave 2.4).

    Per-repo recipe: ensure-pushed → ensure-PR-exists. Cross-repo body
    refresh runs second so each PR description links to its siblings.

    Args:
        feature: feature alias. Defaults to the canonical slot.
        repos: optional repo filter within the feature scope.
        draft: open PRs as drafts (initial open only).
        reviewers: GitHub handles to request review from.
        dry_run: enumerate without firing pushes/opens.
        base: override base branch for every repo.
    """
    from ..actions.ship import ship as ship_impl

    ws = _get_workspace()
    return ship_impl(
        ws, feature=feature, repos=repos, draft=draft,
        reviewers=reviewers, dry_run=dry_run, base=base,
    )


@mcp.tool()
def draft_replies(alias: str, include_likely_resolved: bool = False) -> dict:
    """Auto-draft "Done in <sha>" replies for addressed PR comments (M9).

    For each unresolved comment, walk the file's git history since the
    comment was anchored. If anything changed, the comment is
    "addressed" — return a template-based draft the user reviews and
    posts (or edits + posts). No LLM in v1.

    Args:
        alias: feature name, ``<repo>#<n>``, or PR URL.
        include_likely_resolved: also draft for the temporal classifier's
            ``likely_resolved`` set (weaker signal — surfaced as
            ``confidence: low``).
    """
    from ..actions.draft_replies import draft_replies as draft_impl

    ws = _get_workspace()
    return draft_impl(ws, alias, include_likely_resolved=include_likely_resolved)


@mcp.tool()
def conflicts(
    feature: str | None = None,
    other: str | None = None,
    include_cold: bool = False,
    line_level: bool = False,
) -> dict:
    """Cross-feature file-overlap detection (M12).

    Pairwise intersect each active feature's changed-file set per repo
    and surface pairs that touch the same files. ``high`` severity
    means same file (or, when ``line_level=True``, overlapping line
    ranges) — the rebase will conflict; rebase one onto the other
    before opening a PR.

    Args:
        feature: scope to "what overlaps with this feature." Returns
            only pairs where ``feature`` is one side.
        other: further scope to "specifically <feature> vs <other>."
            Requires ``feature``.
        include_cold: also consider cold features (no worktree). Default
            keeps the focus on actively rotating features.
        line_level: opt into the per-file line-range comparison. Slower
            because it re-runs ``git diff --unified=0`` per repo, but
            lets ``medium`` accurately mean "same file, disjoint lines."
    """
    from ..actions.conflicts import find_conflicts

    ws = _get_workspace()
    return find_conflicts(
        ws, feature=feature, other=other,
        include_cold=include_cold, line_level=line_level,
    )


@mcp.tool()
def reply_to_thread(
    thread_id: str,
    body: str,
    feature: str | None = None,
    resolve_after: bool = False,
) -> dict:
    """Post a reply to a GH review thread; optionally resolve after.

    Args:
        thread_id: The GitHub review thread node ID (must start with
            ``PRRT_``).
        body: The reply text to post.
        feature: Feature to attribute the reply to. Defaults to the
            canonical feature if not supplied.
        resolve_after: If True, resolve the thread after posting the reply
            and record the resolution in the canopy log.
    """
    from ..actions.thread_actions import reply_to_thread as _impl
    from ..actions.errors import ActionError

    ws = _get_workspace()
    try:
        feat = _historian_feature(feature)[1]
    except ActionError as e:
        return e.to_dict()
    try:
        return _impl(ws, thread_id, body, feature=feat, resolve_after=resolve_after)
    except ActionError as e:
        return e.to_dict()


@mcp.tool()
def resolve_thread(thread_id: str, feature: str | None = None) -> dict:
    """Resolve a GitHub PR review thread and record the resolution locally.

    Calls the GitHub GraphQL ``resolveReviewThread`` mutation and appends
    an entry to ``.canopy/state/thread_resolutions.json`` so the resume
    brief can distinguish threads closed by canopy from those resolved
    directly on GitHub.

    Args:
        thread_id: The GitHub review thread node ID (must start with
            ``PRRT_``).
        feature: Feature to attribute the resolution to. Defaults to the
            canonical feature if not supplied.
    """
    from ..actions.thread_actions import resolve_thread as _impl
    from ..actions.errors import ActionError

    ws = _get_workspace()
    try:
        feat = _historian_feature(feature)[1]
    except ActionError as e:
        return e.to_dict()
    try:
        return _impl(ws, thread_id, feature=feat)
    except ActionError as e:
        return e.to_dict()


@mcp.tool()
def feature_resume(alias: str) -> dict:
    """Fresh "what changed since last visit" brief.

    Refreshes GitHub + Linear on every call. Returns:
      - since_last_visit: commits, new threads, resolved threads (GH + canopy),
        ci status delta (v1: empty), draft_replies_pending, historian_excerpt
      - current_state: feature_state, ci_summary_per_repo, bot_unresolved_total,
        draft_replies_summary, branch_position_per_repo, linear link
      - first_visit, last_visit, window_hours
      - switch_performed, switch_summary
      - intent_hints (prioritized next actions)

    The agent should call this on first activity in a feature per session
    (or after returning from another feature). Switch already embeds a
    counts-only summary; this is the full payload.

    Args:
        alias: Feature name, Linear ID, PR URL, or slot ID.
    """
    from ..actions.resume import feature_resume as _impl
    from ..actions.errors import ActionError

    ws = _get_workspace()
    try:
        return _impl(ws, alias)
    except ActionError as e:
        return e.to_dict()


@mcp.tool()
def drift(feature: str | None = None) -> dict:
    """Compare recorded HEAD state vs feature lane expectations.

    Returns a structured report of which feature lanes are aligned (all
    repos on the expected branch) vs drifted (one or more repos on a
    different branch, or repos with no recorded HEAD state yet).

    Use this as the precondition check before any multi-repo write op
    (commit, push, ship). If any feature shows drift, the agent should
    surface it and offer to run ``switch`` to re-align the canonical slot.

    Args:
        feature: limit the report to one feature lane. If None, all
            active feature lanes are reported.
    """
    from ..actions.drift import detect_drift

    ws = _get_workspace()
    ws.refresh()
    return detect_drift(ws, feature_name=feature).to_dict()


# ── Feature lane tools ───────────────────────────────────────────────────

@mcp.tool()
def feature_create(
    name: str,
    repos: list[str] | None = None,
    use_worktrees: bool = False,
) -> dict:
    """Create a new feature lane across repos.

    Creates matching git branches (and optionally worktrees) in all
    or specified repos in the workspace.

    Args:
        name: Feature/branch name (e.g. "auth-flow").
        repos: Subset of repo names. Default: all repos.
        use_worktrees: If true, create linked worktrees so each repo
            gets its own directory under .canopy/worktrees/<name>/.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    lane = coordinator.create(name, repos, use_worktrees=use_worktrees)

    result = lane.to_dict()
    if use_worktrees:
        result["worktree_paths"] = coordinator.resolve_paths(name)
    return result


@mcp.tool()
def feature_list() -> list[dict]:
    """List all active feature lanes with their repo states.

    Shows both explicitly created features and implicit ones
    (branches that exist in 2+ repos).
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return [lane.to_dict() for lane in coordinator.list_active()]


@mcp.tool()
def feature_status(name: str) -> dict:
    """Get detailed status for a feature lane.

    Shows per-repo branch state: ahead/behind default, dirty files,
    changed files, and worktree paths if applicable.

    Args:
        name: Feature lane name.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    lane = coordinator.status(name)
    return lane.to_dict()


@mcp.tool()
def feature_diff(name: str) -> dict:
    """Get aggregate diff for a feature lane across all repos.

    Shows files changed, insertions, deletions per repo, plus
    cross-repo type overlap detection.

    Args:
        name: Feature lane name.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.diff(name)


@mcp.tool()
def feature_changes(name: str) -> dict:
    """Per-file change status (M/A/D/?) for each repo in a feature.

    Includes uncommitted changes — uses the worktree path when one exists
    so the listing matches what the user is actively editing.

    Args:
        name: Feature lane name.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.feature_changes(name)


@mcp.tool()
def feature_merge_readiness(name: str) -> dict:
    """Check if a feature lane is ready to merge.

    Checks: all repos clean, branches up to date with default,
    no type overlaps across repos.

    Args:
        name: Feature lane name.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.merge_readiness(name)


@mcp.tool()
def feature_paths(name: str) -> dict:
    """Get working directory paths for each repo in a feature lane.

    Returns the best path per repo: worktree path if it exists,
    repo path if the branch is checked out there, etc.

    Args:
        name: Feature lane name.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.resolve_paths(name)


# ── Git operations ───────────────────────────────────────────────────────

@mcp.tool()
def checkout(branch: str, repos: list[str] | None = None) -> dict:
    """Checkout a branch across workspace repos.

    Args:
        branch: Branch name to checkout.
        repos: Subset of repo names. Default: all repos.
    """
    ws = _get_workspace()
    results = multi.checkout_all(ws, branch, repos)
    return {"branch": branch, "results": {k: str(v) for k, v in results.items()}}



@mcp.tool()
def preflight(cwd: str | None = None) -> dict:
    """Context-aware pre-commit quality gate.

    Detects which feature/repos you're in from the directory path,
    stages all changes (git add -A), and runs pre-commit hooks.
    Does NOT commit — reports whether the code is ready to commit.

    Args:
        cwd: Directory to detect context from. Defaults to CANOPY_ROOT.
    """
    from ..integrations.precommit import run_precommit
    from ..actions.augments import repo_augments
    from ..workspace.config import load_config, ConfigNotFoundError, ConfigError

    path = Path(cwd) if cwd else None
    if path is None:
        root = os.environ.get("CANOPY_ROOT")
        path = Path(root) if root else None
    ctx = detect_context(cwd=path)

    if not ctx.repo_paths:
        return {"error": "No repos found in context", "context": ctx.to_dict()}

    workspace_config = None
    if ctx.workspace_root:
        try:
            workspace_config = load_config(ctx.workspace_root)
        except (ConfigNotFoundError, ConfigError):
            workspace_config = None

    results = {}
    all_passed = True

    for repo_path, repo_name in zip(ctx.repo_paths, ctx.repo_names):
        status = git.status_porcelain(repo_path)
        if not status:
            results[repo_name] = {"status": "clean", "hooks": None}
            continue
        try:
            git._run(["add", "-A"], cwd=repo_path)
        except git.GitError as e:
            results[repo_name] = {"status": "error", "error": str(e), "hooks": None}
            all_passed = False
            continue

        augments = (
            repo_augments(workspace_config, repo_name) if workspace_config else None
        )
        hook_result = run_precommit(repo_path, augments=augments)
        passed = hook_result["passed"]
        if not passed:
            all_passed = False

        dirty_count = len(status.strip().splitlines())
        results[repo_name] = {
            "status": "staged" if passed else "hooks_failed",
            "dirty_count": dirty_count,
            "hooks": hook_result,
        }

    return {
        "feature": ctx.feature,
        "context_type": ctx.context_type,
        "all_passed": all_passed,
        "results": results,
    }


@mcp.tool()
def log(max_count: int = 20, feature: str | None = None) -> list[dict]:
    """Get interleaved commit log across all repos, sorted by date.

    Args:
        max_count: Maximum entries to return.
        feature: If set, show log for this feature branch.
    """
    ws = _get_workspace()
    return multi.log_all(ws, max_count=max_count, feature=feature)


@mcp.tool()
def branch_list() -> dict:
    """List all local branches across workspace repos.

    Returns per-repo branch lists with current branch, sha, and subject.
    """
    ws = _get_workspace()
    return multi.branches_all(ws)


@mcp.tool()
def branch_delete(
    name: str,
    force: bool = False,
    repos: list[str] | None = None,
) -> dict:
    """Delete a branch across workspace repos.

    Args:
        name: Branch name to delete.
        force: Force delete even if not fully merged.
        repos: Subset of repo names. Default: all repos.
    """
    ws = _get_workspace()
    return multi.delete_branch_all(ws, name, force=force, repos=repos)


@mcp.tool()
def branch_rename(
    old_name: str,
    new_name: str,
    repos: list[str] | None = None,
) -> dict:
    """Rename a branch across workspace repos.

    Args:
        old_name: Current branch name.
        new_name: New branch name.
        repos: Subset of repo names. Default: all repos.
    """
    ws = _get_workspace()
    return multi.rename_branch_all(ws, old_name, new_name, repos=repos)


# ── Stash tools ──────────────────────────────────────────────────────────

@mcp.tool()
def stash_save(
    message: str = "",
    repos: list[str] | None = None,
) -> dict:
    """Stash uncommitted changes across workspace repos.

    Args:
        message: Optional stash message.
        repos: Subset of repo names. Default: all repos.
    """
    ws = _get_workspace()
    return multi.stash_save_all(ws, message=message, repos=repos)


@mcp.tool()
def stash_pop(
    index: int = 0,
    repos: list[str] | None = None,
) -> dict:
    """Pop stash across workspace repos.

    Args:
        index: Stash index to pop.
        repos: Subset of repo names. Default: all repos.
    """
    ws = _get_workspace()
    return multi.stash_pop_all(ws, index=index, repos=repos)


@mcp.tool()
def stash_list() -> dict:
    """List stash entries across all workspace repos."""
    ws = _get_workspace()
    return multi.stash_list_all(ws)


@mcp.tool()
def stash_drop(
    index: int = 0,
    repos: list[str] | None = None,
) -> dict:
    """Drop a stash entry across workspace repos.

    Args:
        index: Stash index to drop.
        repos: Subset of repo names. Default: all repos.
    """
    ws = _get_workspace()
    return multi.stash_drop_all(ws, index=index, repos=repos)


# ── Worktree tools ──────────────────────────────────────────────────────

@mcp.tool()
def worktree_info() -> dict:
    """Get live worktree status across the workspace — always fresh.

    Wave 3.0: worktrees live in numbered slots (``.canopy/worktrees/
    worktree-N/<repo>/``), not feature-named directories. Slot identity
    is stable across switches; feature occupancy is transient. Reads
    slot state from ``.canopy/state/slots.json`` and enriches each
    slot's repo subdirs with live git state (branch, dirty files,
    ahead/behind).

    Returns:
        slots: slot-keyed map ``{worktree-N: {feature, repos}}`` where
            each repo entry has branch, dirty, dirty_count, dirty_files,
            ahead, behind, default_branch, and path.
        repos: per-repo git worktree list from the main working tree.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.worktrees_live()


@mcp.tool()
def worktree_create(
    name: str,
    issue: str | None = None,
    repos: list[str] | None = None,
) -> dict:
    """Create a feature with worktrees, optionally linked to a Linear issue.

    Wave 3.0: worktrees live in numbered slots (``.canopy/worktrees/
    worktree-N/<repo>/``), not feature-named directories. The allocated
    slot ID (e.g. ``worktree-1``) is returned as ``slot_id`` so callers
    can reference the slot directly.

    This is the primary workflow entry point: create isolated worktree
    directories for each repo, open them in your IDE, and optionally
    link to a Linear issue for tracking.

    Args:
        name: Feature/branch name (e.g. "payment-flow").
        issue: Optional Linear issue ID (e.g. "ENG-123"). If a Linear
            MCP server is configured in .canopy/mcps.json, fetches the
            issue title and URL. The issue ID is stored in feature
            metadata either way.
        repos: Subset of repo names. Default: all repos.

    Returns:
        Lane dict with ``slot_id`` (the allocated worktree-N slot) and
        ``worktree_paths`` (per-repo absolute paths inside that slot).
        When ``issue`` was passed, also includes
        ``linear_lookup: {status, reason?}`` so the agent sees whether
        the Linear fetch succeeded:

          - ``ok`` — title/url populated.
          - ``not_configured`` — no linear entry in mcps.json; lane has
            just the issue ID.
          - ``failed`` — Linear MCP responded but the fetch errored or
            returned an empty title/url (often a tool-arg schema
            mismatch); ``reason`` carries the detail.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)

    linear_issue = ""
    linear_title = ""
    linear_url = ""
    linear_lookup: dict = {"status": "skipped"}

    if issue:
        from ..integrations.linear import (
            is_linear_configured,
            get_issue,
            LinearNotConfiguredError,
            LinearIssueNotFoundError,
        )
        from .client import McpClientError

        if is_linear_configured(ws.config.root):
            try:
                issue_data = get_issue(ws.config.root, issue)
                linear_issue = issue_data.get("identifier", issue)
                linear_title = issue_data.get("title", "")
                linear_url = issue_data.get("url", "")
                if linear_title or linear_url:
                    linear_lookup = {"status": "ok"}
                else:
                    # get_issue returned but with no title/url — treat as
                    # a lookup failure so the agent sees the lane was
                    # created with just the bare issue ID.
                    linear_lookup = {
                        "status": "failed",
                        "reason": (
                            "Linear MCP responded but returned no title or URL"
                            " (likely a tool-arg schema mismatch)"
                        ),
                    }
                    linear_issue = issue
                    linear_title = ""
                    linear_url = ""
            except LinearIssueNotFoundError as e:
                linear_lookup = {"status": "failed", "reason": f"issue not found: {e}"}
                linear_issue = issue
            except (LinearNotConfiguredError, McpClientError) as e:
                linear_lookup = {"status": "failed", "reason": str(e)}
                linear_issue = issue
        else:
            linear_lookup = {"status": "not_configured"}
            linear_issue = issue

    from ..features.coordinator import WorktreeLimitError
    try:
        lane = coordinator.create(
            name,
            repos=repos,
            use_worktrees=True,
            linear_issue=linear_issue,
            linear_title=linear_title,
            linear_url=linear_url,
        )
    except WorktreeLimitError as e:
        return {
            "error": "worktree_limit_reached",
            "message": str(e),
            "current": e.current,
            "limit": e.limit,
            "stale_candidates": e.stale,
        }

    result = lane.to_dict()
    result["worktree_paths"] = coordinator.resolve_paths(name)
    from ..actions import slots as _slots_mod
    slot_id = _slots_mod.slot_for_feature(ws, name)
    if slot_id is not None:
        result["slot_id"] = slot_id
    if issue:
        result["linear_lookup"] = linear_lookup
    return result


# ── Feature done ────────────────────────────────────────────────────────

@mcp.tool()
def feature_done(feature: str, force: bool = False) -> dict:
    """Clean up a completed feature: remove worktrees, delete branches, archive.

    Use this when a feature is merged or abandoned. It removes worktree
    directories, deletes local branches, and marks the feature as 'done'
    in features.json. Does not touch remotes or PRs.

    Fails if worktrees have uncommitted changes unless force=True.

    Args:
        feature: Feature lane name.
        force: If True, remove even with dirty worktrees.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.done(feature, force=force)


# ── Config tools ────────────────────────────────────────────────────────

@mcp.tool()
def workspace_config(
    key: str | None = None,
    value: str | None = None,
) -> dict:
    """Read or write workspace settings in canopy.toml.

    With no arguments: returns all settings.
    With key only: returns that setting's value.
    With key and value: sets the value and returns it.

    Available settings: name, slots.

    Args:
        key: Setting name (e.g. "slots").
        value: New value to set. Omit to read.
    """
    from ..workspace.config import (
        get_config_value, set_config_value, get_all_config,
        WORKSPACE_SETTINGS,
    )

    root = _get_workspace().config.root

    if key is None:
        return get_all_config(root)

    if value is None:
        v = get_config_value(root, key)
        return {"key": key, "value": v}

    coerced = set_config_value(root, key, value)
    return {"key": key, "value": coerced}


# ── Review tools ────────────────────────────────────────────────────────

@mcp.tool()
def review_status(feature: str) -> dict:
    """Check if pull requests exist for a feature across repos.

    For each repo in the feature lane, resolves the GitHub remote and
    checks for an open PR matching the feature branch. Requires a
    GitHub MCP server configured in .canopy/mcps.json.

    Args:
        feature: Feature lane name (e.g. "auth-flow").

    Returns:
        Per-repo PR status including number, title, URL. The top-level
        "has_prs" field is False if no PRs exist in any repo — the
        review workflow cannot proceed without PRs.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.review_status(feature)


@mcp.tool()
def review_comments(feature: str) -> dict:
    """Fetch unresolved PR review comments for a feature across repos.

    Requires an open PR in at least one repo — fails if no PRs exist.
    Returns comments grouped by repo and file, filtered to unresolved
    comments only (resolved and bot comments are excluded).

    This is the primary tool for an agent to understand what reviewers
    want changed before the PR can be merged.

    Args:
        feature: Feature lane name (e.g. "auth-flow").

    Returns:
        Comments grouped by repo, each with path, line, body, author.
        total_comments gives the aggregate count across all repos.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.review_comments(feature)


@mcp.tool()
def review_prep(
    feature: str,
    message: str = "",
) -> dict:
    """Run pre-commit hooks and stage all changes for a feature.

    This is the "get to commit-ready state" workflow:
    1. Finds working directories for the feature (worktrees or repos)
    2. Runs pre-commit hooks in each repo (detects framework vs git hooks)
    3. Stages all changes (git add -A)
    4. Reports per-repo results

    Does NOT create a commit — it leaves the repos staged and ready.
    Call the `commit` tool afterwards to actually commit.

    Args:
        feature: Feature lane name.
        message: Suggested commit message (included in result for
            convenience, not used for committing).

    Returns:
        Per-repo pre-commit results and staging status.
        all_passed is True only if every repo's hooks passed.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    return coordinator.review_prep(feature, message=message)


# ── Workspace lifecycle ──────────────────────────────────────────────────

@mcp.tool()
def workspace_reinit(name: str | None = None, dry_run: bool = False) -> dict:
    """Re-run Canopy's repo/worktree discovery and regenerate canopy.toml.

    Useful when repos or worktrees have been added/removed outside Canopy.
    Always overwrites canopy.toml (no-op check is the caller's job). Set
    `dry_run=True` to preview the new TOML without writing.

    Args:
        name: Override the workspace name (defaults to the existing one or
            the directory basename).
        dry_run: If True, return the new TOML without writing.

    Returns:
        { root, repos, skipped, active_worktrees, toml, written }
    """
    from ..workspace.discovery import discover_repos, generate_toml

    root = Path(os.environ.get("CANOPY_ROOT") or os.getcwd()).resolve()
    repos = discover_repos(root)
    if not repos:
        raise ValueError(f"No Git repositories found in {root}")

    toml_content = generate_toml(root, workspace_name=name)

    toml_path = root / "canopy.toml"
    written = False
    if not dry_run:
        toml_path.write_text(toml_content)
        written = True

    all_dirs = [
        d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")
    ]
    skipped = [d.name for d in all_dirs if not (d / ".git").exists()]
    # Keyed by FEATURE — slot dirs resolve their occupant via slots.json
    # rather than being reported as if the slot id were a feature name.
    from ..workspace.discovery import summarize_worktree_dirs
    active_worktrees: dict[str, list[str]] = summarize_worktree_dirs(root)

    return {
        "root": str(root),
        "repos": [
            {
                "name": r.name,
                "path": r.path,
                "role": r.role,
                "lang": r.lang,
                "is_worktree": r.is_worktree,
                "worktree_main": r.worktree_main,
            }
            for r in repos
        ],
        "skipped": skipped,
        "active_worktrees": active_worktrees,
        "toml": toml_content,
        "written": written,
    }


# ── Issue providers ──────────────────────────────────────────────────────


@mcp.tool()
def issue_get(alias: str) -> dict:
    """Fetch an issue from the workspace's configured issue provider.

    Routes through the provider registry (M5). The workspace's
    ``[issue_provider]`` block in canopy.toml selects the backend
    (Linear / GitHub Issues / future). Aliases are provider-native:
    Linear ``"SIN-7"``, GitHub ``"#142"`` or ``"owner/repo#142"``.

    Returns the canonical Issue dict (id, identifier, title, description,
    state, url, assignee, labels, priority, raw).

    On not-configured / not-found / call-failed: returns a structured
    BlockerError dict so the agent can react programmatically.
    """
    from ..providers import (
        IssueNotFoundError, ProviderNotConfigured, IssueProviderError,
        get_issue_provider,
    )
    from ..actions.aliases import resolve_issue_id
    from ..actions.errors import ActionError, BlockerError, FixAction
    ws = _get_workspace()
    try:
        # Resolve through the M5 alias layer so feature names + provider-
        # native ids both work: SIN-412 / 5 / #5 / owner/repo#5 / URL /
        # auth-flow (looks up linked issue id from features.json).
        try:
            resolved = resolve_issue_id(ws, alias)
        except ActionError as err:
            return err.to_dict()
        provider = get_issue_provider(ws)
        issue = provider.get_issue(resolved)
    except ProviderNotConfigured as e:
        return BlockerError(
            code="issue_provider_not_configured",
            what=f"Issue provider '{ws.config.issue_provider.name}' is not configured",
            details={"alias": alias, "error": str(e)},
            fix_actions=[
                FixAction(
                    action="configure_provider",
                    args={"provider": ws.config.issue_provider.name},
                    safe=True,
                    preview=f"configure {ws.config.issue_provider.name} per docs/architecture/providers.md §4",
                ),
            ],
        ).to_dict()
    except IssueNotFoundError as e:
        return BlockerError(
            code="issue_not_found",
            what=f"Issue '{alias}' not found",
            details={"alias": alias, "error": str(e)},
        ).to_dict()
    except IssueProviderError as e:
        return BlockerError(
            code="issue_provider_failed",
            what=f"Issue provider call failed",
            details={"alias": alias, "error": str(e)},
        ).to_dict()
    return issue.to_dict()


@mcp.tool()
def issue_list_my_issues(limit: int = 25) -> list[dict] | dict:
    """List the current user's open issues from the configured provider.

    Returns ``[]`` when the provider isn't configured (no autocomplete
    available). Returns a structured BlockerError-shaped dict when the
    provider IS configured but the call failed.

    Args:
        limit: Maximum issues to return (default 25).
    """
    from ..providers import (
        IssueProviderError, ProviderNotConfigured, get_issue_provider,
    )
    from ..actions.errors import BlockerError, FixAction
    ws = _get_workspace()
    try:
        provider = get_issue_provider(ws)
    except ProviderNotConfigured:
        return []
    try:
        issues = provider.list_my_issues(limit=limit)
    except ProviderNotConfigured:
        return []
    except IssueProviderError as e:
        return BlockerError(
            code="issue_provider_failed",
            what="Issue provider list call failed",
            details={"provider": ws.config.issue_provider.name, "error": str(e)},
            fix_actions=[
                FixAction(
                    action="configure_provider",
                    args={"provider": ws.config.issue_provider.name},
                    safe=True,
                    preview=f"verify {ws.config.issue_provider.name} config in canopy.toml + .canopy/mcps.json",
                ),
            ],
        ).to_dict()
    return [i.to_dict() for i in issues]


# ── Linear (deprecated aliases — kept one release cycle for backwards compat) ──


@mcp.tool()
def linear_my_issues(limit: int = 25) -> list[dict] | dict:
    """Deprecated. Use ``issue_list_my_issues`` instead.

    Provider-agnostic alias surviving from the pre-M5 era. Forwards to
    ``issue_list_my_issues``; same return shape. Will be removed in a
    future release.

    Args:
        limit: Maximum issues to return (default 25).
    """
    return issue_list_my_issues(limit=limit)


@mcp.tool()
def feature_link_linear(feature: str, issue: str) -> dict:
    """Attach a Linear issue to an existing feature lane.

    Fetches the issue via the configured Linear MCP and updates
    features.json with its identifier, title, and URL. Use this from
    the VSCode dashboard's "Pick from my Linear issues" action when a
    lane was created without an issue attached.

    Args:
        feature: Feature lane name or alias.
        issue: Linear issue identifier (e.g. "ENG-412").

    Returns:
        The updated feature lane dict.
    """
    ws = _get_workspace()
    coordinator = FeatureCoordinator(ws)
    lane = coordinator.link_linear_issue(feature, issue)
    return lane.to_dict()


# ── Sync ─────────────────────────────────────────────────────────────────

@mcp.tool()
def sync(strategy: str = "rebase") -> dict:
    """Pull default branch and rebase/merge feature branches across repos.

    Args:
        strategy: "rebase" or "merge".
    """
    ws = _get_workspace()
    return multi.sync_all(ws, strategy=strategy)


@mcp.tool()
def slots(rich: bool = True) -> dict:
    """Slot occupancy + (default) per-slot enrichment for the dashboard / agent.

    With ``rich=True`` (default for MCP — what the dashboard and the agent
    both want), returns the full payload: per-repo branch, dirty + counts,
    ahead/behind, default branch, last commit, PR + CI rollup, unresolved
    bot threads, linear link, and the computed ``feature_state`` — for
    every occupied slot AND canonical. Empty slots are explicit ``null``.

    With ``rich=False``, returns the lightweight shape from slots.json
    only (slot id → feature + last_touched). Use for cheap polling when
    the caller doesn't need PR/CI/bot data.

    Slot ids returned here are stable and can be passed as feature
    aliases to any tool that accepts one (added in T14).
    """
    from ..actions import slots as slots_mod
    workspace = _get_workspace()
    if not rich:
        state = slots_mod.read_state(workspace)
        return state.to_dict() if state else {"canonical": None, "slots": {}}
    from ..actions.slot_details import rich_slots
    return rich_slots(workspace)


@mcp.tool()
def migrate_slots() -> dict:
    """One-shot migration from pre-3.0 canopy layout to the 3.0 slot model.

    Renames .canopy/worktrees/<feature>/ → .canopy/worktrees/worktree-N/,
    rewrites canopy.toml (max_worktrees → slots), and migrates
    .canopy/state/active_feature.json → .canopy/state/slots.json.

    Refuses to run if slots.json already exists (idempotency guard).
    Returns: {moved: [...], slots: {slot_id: feature}, canonical, slot_count}.
    """
    import os
    from pathlib import Path
    from ..actions.migrate_slots import migrate, AlreadyMigratedError, NotLegacyError

    # Find workspace root via CANOPY_ROOT or walk up from cwd.
    env_root = os.environ.get("CANOPY_ROOT")
    if env_root:
        root = Path(env_root).resolve()
    else:
        root = Path.cwd().resolve()
        while root != root.parent:
            if (root / "canopy.toml").exists():
                break
            root = root.parent
        else:
            return {"error": "not in a canopy workspace"}

    try:
        return migrate(root)
    except AlreadyMigratedError as e:
        return {"error": "already_migrated", "detail": str(e)}
    except NotLegacyError as e:
        return {"error": "nothing_to_migrate", "detail": str(e)}


# ── Entry point ──────────────────────────────────────────────────────────

def main():
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-V"):
        from .. import __version__
        print(f"canopy-mcp {__version__}")
        return
    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
        print(
            "canopy-mcp — Canopy MCP server (stdio JSON-RPC)\n"
            "\n"
            "This is a Model Context Protocol server. It is not run interactively;\n"
            "your MCP-aware client (Claude Code, Claude Desktop, etc.) launches it\n"
            "and communicates with it over stdio.\n"
            "\n"
            "To register canopy with Claude Code, run:\n"
            "    canopy setup-agent\n"
            "\n"
            "Options:\n"
            "  -V, --version    Print version and exit\n"
            "  -h, --help       Print this message and exit"
        )
        return
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
