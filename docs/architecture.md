# Architecture

Canopy 3.1.0.

```
src/canopy/
├── cli/
│   ├── main.py                # argparse CLI — all commands; thin wrapper, no business logic
│   ├── ui.py                  # rich terminal output (theme, spinners, colors)
│   └── render.py              # structured-error renderer (BlockerError → multi-line CLI)
├── workspace/
│   ├── config.py              # canopy.toml parser (RepoConfig, WorkspaceConfig)
│   ├── discovery.py           # auto-detect repos + worktrees, generate toml
│   ├── context.py             # context detection (feature_dir, repo_worktree, repo, workspace_root)
│   └── workspace.py           # Workspace class, RepoState dataclass
├── git/
│   ├── repo.py                # ALL git subprocess calls (single-repo only)
│   ├── multi.py               # cross-repo operations (calls repo.py)
│   ├── hooks.py               # install/uninstall post-checkout hook + heads.json reader
│   └── templates/
│       └── post-checkout.py   # hook script (Python; fcntl-locked; never blocks git)
├── features/
│   └── coordinator.py         # FeatureLane + FeatureCoordinator; branches map for per-repo branches
├── actions/                   # Wave 2+: action layer — completion-driven recipes over primitives
│   ├── errors.py              # ActionError / BlockerError / FailedError / FixAction
│   ├── aliases.py             # universal alias resolver (feature, repo#n, repo:branch, URL, worktree-N)
│   ├── augments.py            # M2: per-workspace augment resolver (preflight_cmd, review_bots, …)
│   ├── bootstrap.py           # M6: env-file copy + install_cmd + IDE workspace gen for worktrees
│   ├── bot_resolutions.py     # M3: persistent log of bot comments addressed via `commit --address`
│   ├── bot_status.py          # M3: per-feature bot-comment rollup
│   ├── commit.py              # commit action (per-repo staging + conventional-commit support)
│   ├── conflicts.py           # M12: cross-feature file/line overlap detection
│   ├── doctor.py              # diagnostic checks + fix hints (21-code recovery primitive)
│   ├── draft_replies.py       # M9: file-history-based addressed-comment classifier + reply templates
│   ├── drift.py               # detect_drift + assert_aligned (cached path via heads.json)
│   ├── evacuate.py            # per-repo evacuate primitive (stash → wt-add → pop)
│   ├── feature_state.py       # 9-state machine + next_actions (dashboard backend, worktree-aware)
│   ├── historian.py           # M4: cross-session feature memory at .canopy/memory/<feature>.md
│   ├── ide_workspace.py       # M6: pure renderer for .code-workspace files
│   ├── last_visit.py          # Plan 2: per-feature last-visit anchor (visits.json get/mark/reset)
│   ├── migrate_slots.py       # Wave 3.0: one-shot pre-3.0 → 3.0 layout migration
│   ├── preflight_state.py     # .canopy/state/preflight.json read/write + freshness check
│   ├── push.py                # push action (per-repo upstream + force-with-lease)
│   ├── reads.py               # alias-aware read primitives (linear, github PR/branch/comments)
│   ├── resume.py              # Plan 2: feature_resume compound action + resume_summary (counts-only)
│   ├── review_filter.py       # temporal classifier (actionable vs likely_resolved threads)
│   ├── ship.py                # M8: PR open/update orchestrator with cross-repo body links
│   ├── slot_details.py        # Wave 3.0: rich slot shape (PR/CI/bots/linear per slot + canonical)
│   ├── slot_load.py           # Wave 3.0: slot_load / slot_clear / slot_swap primitives
│   ├── slots.py               # Wave 3.0: slots.json reader/writer + path resolution + LRU
│   ├── stash.py               # feature-tagged stash save/list/pop
│   ├── switch.py              # Wave 3.0: slot-model focus primitive (+ --to-slot / --evict-to)
│   ├── switch_preflight.py    # predictable-failure detection for switch (cap, locks, leftover paths)
│   ├── thread_actions.py      # Plan 2: GH thread resolve/reply via GraphQL + local resolution log
│   ├── thread_resolutions.py  # Plan 2: thread_resolutions.json load/record/filter_since
│   └── triage.py              # cross-repo PR enumeration + priority tiers (slot-enriched)
├── agent/
│   └── runner.py              # canopy_run — directory-safe shell exec (no path management)
├── agent_setup/               # ships bundled skills + setup_agent installer
│   ├── __init__.py            # install_skill / install_mcp / check_status
│   └── skills/
│       ├── using-canopy/SKILL.md     # default skill, always installed
│       └── augment-canopy/SKILL.md   # opt-in via --skill augment-canopy
├── integrations/
│   ├── linear.py              # Linear issue fetching (via mcp/client.py)
│   ├── github.py              # GitHub PR + review comments (MCP or gh CLI fallback)
│   └── precommit.py           # detect + run pre-commit hooks
└── mcp/
    ├── server.py              # MCP server — 67 tools, stdio transport
    └── client.py              # MCP client — stdio + HTTP+OAuth transports
```

## Key boundaries

- **`git/repo.py` is the only module that calls `subprocess.run(["git", ...])`.** Everything else routes through it. The git layer stays replaceable and testable.
- **`mcp/server.py` and `cli/main.py` are thin wrappers.** Business logic lives in `actions/`, `features/coordinator.py`, `git/multi.py`, and `workspace/`. Adding a CLI command + MCP tool is mostly registering an existing function in two places.
- **All external integrations go through `mcp/client.py` (or `gh` CLI fallback).** No direct API calls anywhere in the codebase. When no `github` MCP server is configured, `integrations/github.py` falls back to `gh api` / `gh pr` for the same return shapes.
- **Actions wrap primitives.** An `actions/*.py` function composes `git/`, `integrations/`, and `workspace/` calls into a verified workflow. Actions return structured `BlockerError` / dict; never `print()`. The CLI / MCP layers do their own rendering.
- **The agent context contract.** Every action that takes multi-repo state takes semantic inputs (`feature`, `repo`, alias). Path resolution lives inside `workspace/` and `actions/aliases.py`. See [concepts.md](concepts.md#2-the-agent-context-contract).
- **Per-repo branches map.** `FeatureLane.branches: dict[repo, branch]` overrides "branch == feature name" for legacy mismatched-naming features. Use `lane.branch_for(repo)` or `repos_for_feature(workspace, feature)` everywhere — never recompute as `[r for r in feature.repos]` with feature name as branch.
- **State persistence is split.** Cached state (`.canopy/state/heads.json`, `slots.json`, etc.) supports fast paths and state machine warm-up. Live git is the source of truth for write actions and `feature_state`. OAuth tokens cache in `~/.canopy/mcp-tokens/` (per-user, not per-workspace).
- **Feature-aware stash tagging.** `stash save --feature` writes `[canopy <feature> @ <ts>] <message>`. The parser tolerates git's `On <branch>: ` auto-prefix. Feature stashes survive branch switches and are listed per-feature by `stash_list_grouped`.

## Module dependency direction

```
   cli/  ←→  mcp/server.py             (sibling adapters)
        ↓
   actions/   ←   agent_setup/         (setup writes to ~ and the workspace)
        ↓
   features/, integrations/
        ↓
   git/, workspace/, mcp/client.py
```

Always top-down. `actions/` depends on `git/`, `integrations/`, `features/`, `workspace/` — never the reverse. Tests can stub any layer below by patching at the import boundary.

## Runtime pathways

The dynamic stories — what happens when calls land. These complement the static module tree above.

### The agent tool loop

A typical session through canopy MCP. Every arrow is one MCP call. Note the agent never specifies a path; every input is semantic (feature name, repo name, alias).

```
  Agent                                  Canopy
  ─────                                  ──────
   triage()                          ─→  gh.list_open_prs per repo (MCP or gh CLI)
                                         group by feature lane
                                         classify priority via temporal filter
                                         enrich with slot occupancy from slots.json
                                     ←─  features ordered by priority

   feature_resume(feature)           ─→  resolve_feature → canonical name
                                         switch(feature) if not already canonical
                                         refresh: historian + bot_status + review_filter
                                           + pr_checks + linear
                                         compose resume brief (since last_visit anchor)
                                         mark_visited (single bump per resume call)
                                     ←─  brief {state, since_ts, commits_delta,
                                          open_threads, bot_threads, checks, intent_hints}

   feature_state(feature)            ─→  live git.current_branch per repo
                                         git.divergence per repo
                                         gh.get_review_comments + classify
                                         gh.find_pull_request
                                         preflight_state.is_fresh()
                                     ←─  state + summary + next_actions

   ── read next_actions[0] ──

   switch(feature)                   ─→  switch_preflight (no state change):
                                           branch existence, leftover paths,
                                           git lock, cap-reached prediction
                                         per repo (slot model):
                                           if Y warm   → remove worktree
                                           if X exists → evacuate_repo(X):
                                                            git.stash (if dirty)
                                                            git.checkout(target Y)
                                                            git.worktree_add(X slot)
                                                            git.stash_pop in worktree
                                           else        → git.stash + git.checkout
                                         slots.write (canonical + last_touched)
                                     ←─  {feature, mode, per_repo_paths,
                                          previously_canonical, eviction?, branches_created?}

   feature_state(feature)            ─→  …
                                     ←─  state advanced (e.g. drifted → in_progress)

   ── agent edits files via Read/Edit/Write ──
   ── or runs path-safe shell via run(repo, command) ──

   preflight(feature)                ─→  precommit hooks per repo (sequential)
                                         preflight_state.record_result()
                                     ←─  per-repo {passed, output}

   feature_state(feature)            ─→  …
                                     ←─  state: ready_to_commit
```

Path resolution lives entirely in `actions/aliases.py` (`resolve_feature`, `repos_for_feature`) and `agent/runner.py` (`canopy_run`). It never crosses the MCP boundary, so the agent has no surface area to type a wrong path.

### feature_state composition

`feature_state` is a thin shell over many primitives — same pattern other actions follow, but the most-composed example. Decision tree across the 9 states:

```
  feature_state(f)
    │
    ├─ resolve_feature(f)                  alias → canonical name
    │
    ├─ repos_for_feature(f)                {repo: expected_branch}  (honors lane.branches map)
    │
    ├─ _live_drift(repos, branches)        actual git current_branch per repo
    │   │
    │   └─ drifted? → state = "drifted"   ◄── supersedes everything below
    │
    ├─ _per_repo_facts(f, repos)
    │   ├─ git.is_dirty / dirty_file_count
    │   ├─ git.sha_of(branch)
    │   ├─ git.divergence(branch, origin/branch)  → ahead, behind
    │   ├─ gh.find_pull_request                   → review_decision, draft, …
    │   └─ gh.get_review_comments + classify_threads → actionable, likely_resolved
    │
    ├─ bot_status(f)                       unresolved bot comments → awaiting_bot_resolution?
    │
    ├─ preflight_state.is_fresh(repos)     compares recorded sha vs current HEAD
    │
    └─ _decide_state(facts, summary, preflight_fresh, preflight_entry):
        ├─ dirty + fresh-passed-preflight       → ready_to_commit
        ├─ dirty                                 → in_progress
        ├─ clean + ahead > 0                     → ready_to_push
        ├─ clean + CHANGES_REQUESTED             → needs_work
        ├─ clean + bot threads unresolved        → awaiting_bot_resolution
        ├─ clean + all PRs APPROVED              → approved
        ├─ clean + no PRs                        → no_prs
        └─ clean + PRs open + nothing actionable → awaiting_review
```

The ninth state (`awaiting_bot_resolution`) is reached when open bot-authored review threads exist but no human CHANGES_REQUESTED is present — bot threads alone route here, not to `needs_work`. See [concepts.md](concepts.md#3-the-feature-state-machine) for the full state table.

### Drift detection: two pathways

Two paths exist because they answer different questions and have different costs.

```
  ┌─ Cached fast path (canopy drift) ──────────────────────────────┐
  │                                                                │
  │  git checkout <branch>                                         │
  │       │                                                        │
  │       ▼                                                        │
  │  .git/hooks/post-checkout    (Python; fcntl-locked)            │
  │       │                                                        │
  │       ▼                                                        │
  │  .canopy/state/heads.json    {repo: {branch, sha, ts}}         │
  │       │                                                        │
  │       ▼                                                        │
  │  canopy drift                read heads.json + features.json,  │
  │                              report alignment per feature      │
  └────────────────────────────────────────────────────────────────┘

  ┌─ Live correct path (canopy state, feature_state MCP tool) ─────┐
  │                                                                │
  │  feature_state(f)                                              │
  │       │                                                        │
  │       ▼                                                        │
  │  git.current_branch per repo  (subprocess; authoritative)      │
  │       │                                                        │
  │       ▼                                                        │
  │  alignment vs repos_for_feature(f) → drifted / aligned         │
  └────────────────────────────────────────────────────────────────┘
```

The hook is shared across all worktrees of a repo via git's `commondir` mechanism — installing in the main repo covers every linked worktree. Honors `core.hooksPath` (Husky-compatible). Pre-existing user hooks are chained: canopy's hook moves them to `post-checkout.canopy-chained` and execs them after writing state.

### Action contract pathway

Every action follows a fixed three-phase structure. Errors flow back as `BlockerError` (preconditions failed; no side effects) or `FailedError` (mid-flight; partial side effects). Both serialize to the same `{status, code, what, expected, actual, fix_actions, details}` shape.

```
  def some_action(workspace, feature, **kw):

      # 1. PRECONDITIONS — verify before any side effect
      assert_aligned(workspace, feature)         # raises BlockerError on drift
      validate_inputs(...)

      # 2. STEPS — per-repo execution with per-repo result tracking
      results = {}
      for repo, expected_branch in repos_for_feature(workspace, feature).items():
          before = git.current_branch(repo)
          try:
              do_the_thing(repo, expected_branch)
              after = git.current_branch(repo)
              results[repo] = {"status": "ok", "before": before, "after": after}
          except git.GitError as e:
              results[repo] = {"status": "failed", "reason": str(e), ...}

      # 3. COMPLETION — verify the new state matches criteria, don't assume
      if not all_repos_ok(results):
          raise FailedError(code="...", actual={"per_repo": results}, fix_actions=[...])

      return {"feature": feature, "aligned": True, "repos": results}
```

CLI renders the error via `cli/render.py` (multi-line with `fix_actions` and `safe`/`needs review` tags). MCP returns `BlockerError.to_dict()` directly. Same shape, two consumers — the agent and the human read the same JSON, just rendered differently.

## Slot model internals

The slot model is the runtime guarantee that at most one canonical checkout and `N` warm worktrees exist at any time. `switch` is the only public entry point; `slots.py`, `slot_load.py`, and `switch_preflight.py` are its internal implementation.

**`slots.json` schema:**

```
{
  "canonical": {feature, activated_at, per_repo_paths} | null,
  "previous_canonical": str | null,
  "slots": {
    "worktree-1": {feature, occupied_at} | null,
    "worktree-2": {feature, occupied_at} | null
  },
  "last_touched": {feature: ISO, ...},
  "in_flight": {feature_being_promoted, previously_canonical, ...} | null
}
```

**Transaction safety.** `in_flight` is set atomically before a multi-repo switch starts and cleared on success. If the process is interrupted mid-flight, subsequent `switch()` calls detect a non-null `in_flight` and raise `BlockerError(code='slot_state_inconsistent')`. Recovery is via `canopy doctor`, which inspects actual worktree paths and reconstructs a consistent state.

**LRU eviction policy.** When the slot cap is reached and the caller did not pass `--evict-to`, canopy raises `BlockerError(code='worktree_cap_reached')` with the LRU candidate in `details`. Canopy never silently evicts — the human or the agent must explicitly choose. The LRU ordering is computed from `last_touched` timestamps; the slot with the oldest entry is the eviction candidate.

**Slot identity is stable; feature occupancy is transient.** Slot directories (`worktree-1/`, `worktree-2/`) persist across feature swaps. A slot keeps its numbered id; features move in and out. This means pre-built worktrees re-use their node_modules, venvs, and build artifacts when a feature rotates back into the same slot.

## Plan 2 — resume and threads

`feature_resume` (via `actions/resume.py`) is the session-start primitive for returning to a feature. It orchestrates: alias resolution, `switch` if not already canonical, data refresh (historian + bot_status + review_filter + pr_checks + linear), and brief section composition. The result is a structured `{state, since_ts, commits_delta, open_threads, bot_threads, checks, intent_hints}` snapshot scoped to activity since the last visit.

**Single-bump invariant.** Exactly one `mark_visited` call happens per `feature_resume` invocation — either inside `switch` (if a slot transition occurred) or at the end of `resume` itself. The `visits.json` anchor never moves twice for the same resume.

**Thread round-trip.** `actions/thread_actions.py` and `actions/thread_resolutions.py` close the GitHub review-thread loop: canopy can resolve threads and reply via GraphQL, with attribution logged locally to `thread_resolutions.json`. `filter_since` scopes the log to the current visit window, so the resume brief can report "N threads resolved by canopy since last visit" without re-reading all history.

## State files

What state lives where, who writes it, who reads it:

| Path | Writer | Readers | Purpose |
|---|---|---|---|
| `canopy.toml` | `canopy init` | all canopy commands | workspace definition (repos, slots cap, augments) |
| `.canopy/features.json` | `feature_create` / `link_linear` / `done` | most actions | feature lanes + Linear links + per-repo branches map |
| `.canopy/state/heads.json` | post-checkout hook | `drift`, `doctor` | drift fast path |
| `.canopy/state/heads.json.lock` | post-checkout hook | (fcntl flock) | concurrent-fire safety |
| `.canopy/state/preflight.json` | `preflight` / `review_prep` | `feature_state` | in_progress vs ready_to_commit |
| `.canopy/state/slots.json` | `switch` / `slot_load` / `slot_clear` / `slot_swap` | `triage`, `slots`, `doctor` | canonical + slot occupancy + last_touched LRU + in_flight marker |
| `.canopy/state/visits.json` | `last_visit.mark_visited` | `resume`, `draft_replies` | per-feature `{last_visit, previous_visit}` anchor |
| `.canopy/state/thread_resolutions.json` | `thread_resolutions.record` | `resume`, `draft_replies` | GH threads canopy resolved: `{thread_id: {resolved_by_canopy_at, feature, …}}` |
| `.canopy/state/bot_resolutions.json` | `bot_resolutions.record_resolution` | `bot_status`, `feature_state` | per-comment resolution log for bot-authored comments |
| `.canopy/memory/<feature>.md` | `historian` | `feature_resume` | cross-session feature memory (plain markdown) |
| `.mcp.json` | `canopy init` / `setup-agent` | MCP-aware clients | server registry |
| `~/.canopy/mcp-tokens/<server>.{client,tokens}.json` | `mcp/client.py` OAuth provider | `mcp/client.py` | OAuth token cache (per-user) |
| `~/.claude/skills/<skill>/SKILL.md` | `canopy init` / `setup-agent` | Claude Code (auto-loaded) | agent integration skills (using-canopy, augment-canopy) |

All workspace state lives under `.canopy/`; agent and per-user state lives under `~/`. The split lets you share workspace state via git (commit `.canopy/features.json` if you want; ignore `.canopy/state/`), while OAuth tokens and skills never leave the user's machine.
