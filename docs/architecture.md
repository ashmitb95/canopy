# Architecture

Canopy 4.0.0-rc1.

Canopy 4.0 (the "great distillation") splits into **two surfaces**, and that split
organizes this document:

- **The agent surface** — 15 MCP tools (`mcp/server.py`). Path-safety, registry,
  focus, safe git ops, recovery. The agent sees only what it needs to work safely
  and stay oriented; its context budget goes to comprehension, not orchestration.
- **The management surface** — PR triage, review-comment classification, bot
  rollups, ship, historian, resume briefs, conflict detection, and Linear/GitHub
  reads. This lives in `canopy/management/` and is reached by the human (or the
  dashboard) via `canopy <cmd> --json`. It is **not** on the agent's MCP surface.

Nothing was deleted in the prune — management *moved off* the agent surface. See
[concepts.md](concepts.md) for the two-surface vocabulary and the slot model.

```
src/canopy/
├── cli/
│   ├── main.py                # argparse CLI — ALL commands (core + management); thin wrapper
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
│   └── coordinator.py         # FeatureLane + FeatureCoordinator; per-repo branches map
│                              #   (review methods extracted to management/review_ops.py in 4.0)
├── actions/                   # AGENT-CORE — the 15-tool surface + core primitives
│   ├── errors.py              # ActionError / BlockerError / FailedError / FixAction
│   ├── aliases.py             # universal alias resolver (feature, repo#n, repo:branch, URL, worktree-N)
│   ├── registry.py            # context — two-tier registry read (local instant + remote PR/CI overlay)
│   ├── start.py               # start <alias> — lazy feature create + branch in trunk
│   ├── join.py                # join <repo> — register a repo into the active feature (lazy growth)
│   ├── active.py              # intended-focus pointer (.canopy/state/active.json)
│   ├── advisories.py          # observe-as-advisory: surface (never enforce) registry/disk drift
│   ├── switch.py              # slot-model focus primitive (promote feature into trunk = run target)
│   ├── switch_preflight.py    # predictable-failure detection for switch (cap, locks, leftover paths)
│   ├── reclaim.py             # free a warm slot when its PR is merged (checkout base + drop worktree)
│   ├── slots.py               # slots.json reader/writer + path resolution + LRU
│   ├── slot_policy.py         # warm-vs-cold policy for a feature vacating trunk
│   ├── slot_load.py           # slot_load / slot_clear / slot_swap primitives
│   ├── slot_bootstrap.py      # auto-bootstrap on slot creation (fast sync + background deps)
│   ├── bootstrap.py           # env-file copy + install_cmd + IDE workspace gen for worktrees
│   ├── ide_workspace.py       # pure renderer for .code-workspace files
│   ├── evacuate.py            # per-repo evacuate primitive (stash → wt-add → pop)
│   ├── migrate_slots.py       # one-shot pre-3.0 → 3.0 layout migration
│   ├── commit.py              # commit — feature-scoped multi-repo commit (commit-only in 4.0)
│   ├── push.py                # push action (per-repo upstream + force-with-lease)
│   ├── stash.py               # feature-tagged stash save/list/pop
│   ├── preflight_state.py     # .canopy/state/preflight.json read/write + freshness check
│   ├── drift.py               # detect_drift + assert_aligned (cached path via heads.json)
│   ├── pr_map.py              # NEW 4.0: core PR-mapping (branch ↔ PR ↔ feature); remote-tier of context
│   ├── prs_cache.py           # NEW 4.0: offline fallback cache for the remote PR overlay
│   ├── repo_paths.py          # NEW 4.0: resolve_repo_paths — per-repo path resolution (worktree-aware)
│   ├── augments.py            # per-workspace augment resolver (preflight_cmd, review_bots, …)
│   ├── hook_gate.py           # NEW 4.0: PreToolUse git gate — blocks mutations from wrong path/branch
│   ├── hook_context.py        # NEW 4.0: SessionStart brief — one compact orientation block
│   └── doctor.py              # diagnostic checks + fix hints (21-code / 11-category recovery)
├── management/                # NEW 4.0: quarantined HUMAN/dashboard surface — CLI --json only, NO MCP
│   ├── review_ops.py          # review_status / review_comments / review_prep (extracted from coordinator)
│   ├── review_filter.py       # temporal classifier (actionable vs likely_resolved threads)
│   ├── reads.py               # alias-aware read primitives (linear, github PR/branch/comments)
│   ├── draft_replies.py       # file-history-based addressed-comment classifier + reply templates
│   ├── thread_actions.py      # GH thread resolve/reply via GraphQL + local resolution log
│   ├── thread_resolutions.py  # thread_resolutions.json load/record/filter_since
│   ├── bot_status.py          # per-feature bot-comment rollup
│   ├── bot_resolutions.py     # persistent log of bot comments addressed via commit
│   ├── historian.py           # cross-session feature memory at .canopy/memory/<feature>.md
│   ├── resume.py              # feature_resume compound action + resume_summary (counts-only)
│   ├── last_visit.py          # per-feature last-visit anchor (visits.json get/mark/reset)
│   ├── ship.py                # PR open/update orchestrator with cross-repo body links
│   ├── conflicts.py           # cross-feature file/line overlap detection
│   ├── triage.py              # cross-repo PR enumeration + priority tiers (slot-enriched)
│   ├── slot_details.py        # rich slot shape (PR/CI/bots/linear per slot + canonical)
│   └── feature_state.py       # 9-state machine + next_actions (dashboard backend, worktree-aware)
├── agent/
│   └── runner.py              # canopy_run — directory-safe shell exec (no path management)
├── agent_setup/               # ships bundled skills + setup_agent installer
│   ├── __init__.py            # install_skill / install_mcp / check_status
│   └── skills/
│       ├── using-canopy/SKILL.md     # default skill, always installed
│       └── augment-canopy/SKILL.md   # opt-in via --skill augment-canopy
├── integrations/              # SHARED infra — used by both surfaces, not management-owned
│   ├── linear.py              # Linear issue fetching (via mcp/client.py)
│   ├── github.py              # GitHub PR + review comments (MCP or gh CLI fallback)
│   └── precommit.py           # detect + run pre-commit hooks
└── mcp/
    ├── server.py              # MCP server — 15 agent tools, stdio transport
    └── client.py              # MCP client — stdio + HTTP+OAuth transports
```

## Key boundaries

- **`git/repo.py` is the only module that calls `subprocess.run(["git", ...])`.** Everything else routes through it. The git layer stays replaceable and testable.
- **The agent/management boundary (4.0).** Agent-core (`actions/`, `features/`, `agent/`) imports **nothing** from `canopy.management`. This is enforced statically by [`tests/test_import_boundary.py`](../tests/test_import_boundary.py), which scans the source (catching lazy/function-local imports too) against an explicit `AGENT_CORE` allowlist and a `MANAGEMENT_NAMES` denylist. The dependency arrow only runs `cli/ → management/`; management may reach *down* into agent-core primitives, never the reverse. `integrations/github.py` and `integrations/linear.py` are **shared infra** consumed by both surfaces — they are not part of `management/`.
- **`mcp/server.py` and `cli/main.py` are thin wrappers.** Business logic lives in `actions/`, `management/`, `features/coordinator.py`, `git/multi.py`, and `workspace/`. `mcp/server.py` registers exactly the **15 agent tools**; `cli/main.py` keeps **all** commands (core + management), each with `--json`.
- **All external integrations go through `mcp/client.py` (or `gh` CLI fallback).** No direct API calls anywhere in the codebase. When no `github` MCP server is configured, `integrations/github.py` falls back to `gh api` / `gh pr` for the same return shapes.
- **Actions wrap primitives.** An `actions/*.py` (or `management/*.py`) function composes `git/`, `integrations/`, and `workspace/` calls into a verified workflow. Actions return structured `BlockerError` / dict; never `print()`. The CLI / MCP layers do their own rendering.
- **The agent context contract.** Every action that takes multi-repo state takes semantic inputs (`feature`, `repo`, alias). Path resolution lives inside `workspace/`, `actions/aliases.py`, and `actions/repo_paths.py`. See [concepts.md](concepts.md#2-the-agent-context-contract).
- **Per-repo branches map.** `FeatureLane.branches: dict[repo, branch]` overrides "branch == feature name" for legacy mismatched-naming features. Use `lane.branch_for(repo)` or `repos_for_feature(workspace, feature)` everywhere — never recompute as `[r for r in feature.repos]` with feature name as branch.
- **State persistence is split.** Cached state (`.canopy/state/heads.json`, `slots.json`, `prs.json`, etc.) supports fast paths and state-machine warm-up. Live git is the source of truth for write actions and `feature_state`. OAuth tokens cache in `~/.canopy/mcp-tokens/` (per-user, not per-workspace).
- **Feature-aware stash tagging.** `stash save --feature` writes `[canopy <feature> @ <ts>] <message>`. The parser tolerates git's `On <branch>: ` auto-prefix. Feature stashes survive branch switches and are listed per-feature by `stash_list_grouped`.

## Module dependency direction

```
   cli/  ──────────────→  management/         (CLI is the only caller of management)
     │                        │
     ↓                        ↓
   mcp/server.py  ─→  actions/   ←   agent_setup/   (setup writes to ~ and the workspace)
                          ↓
              features/, integrations/
                          ↓
                 git/, workspace/, mcp/client.py
```

Always top-down. `actions/` depends on `git/`, `integrations/`, `features/`, `workspace/` — never the reverse, and **never on `management/`**. `management/` sits above and to the side: it may reach down into agent-core primitives, but only `cli/main.py` reaches into it. `mcp/server.py` binds solely to `actions/` (plus a few workspace reads), which is what keeps the agent surface at 15 tools. Tests stub any layer below by patching at the import boundary.

## Runtime pathways

The dynamic stories — what happens when calls land. These complement the static module tree above.

### The agent tool loop

A typical session through the 15-tool canopy MCP surface. Every arrow is one MCP
call. Note the agent never specifies a path; every input is semantic (feature
name, repo name, alias), and canopy resolves the directory internally.

```
  Agent                                  Canopy
  ─────                                  ──────
   context()                         ─→  Tier 1 (local, ZERO network):
                                           feature ↔ repo ↔ branch ↔ path ↔ slot state
                                         Tier 2 (remote, opt-in):
                                           pr_map overlay → PR + CI per branch
                                     ←─  the single workspace map (supersedes the old
                                          workspace_status / feature_list / slots reads)

   start(alias)                      ─→  resolve alias (Linear best-effort)
                                         create feature record + branch in trunk (lazy)
                                     ←─  {feature, repos, branches_created}

   join(repo)                        ─→  adopt active feature's branch into <repo> trunk
                                     ←─  {feature, repo, branch}

   ── read context().state / next steps ──

   switch(feature)                   ─→  switch_preflight (no state change):
                                           branch existence, leftover paths,
                                           git lock, cap-reached prediction
                                         slot_policy: warm (open PR / live WIP) vs cold
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

   ── agent edits files via Read/Edit/Write ──
   ── or runs path-safe shell via run(repo, command) ──

   preflight(feature)                ─→  precommit hooks per repo (sequential)
                                         preflight_state.record_result()
                                     ←─  per-repo {passed, output}

   commit(feature)                   ─→  stage tracked changes (or explicit paths) per repo
                                         conventional-commit across every feature repo
                                     ←─  per-repo {sha, files}

   push(feature)                     ─→  per-repo upstream (force-with-lease)
                                     ←─  per-repo {remote, ref}

   drift()                           ─→  heads.json vs repos_for_feature → aligned / drifted
                                     ←─  per-feature alignment

   reclaim(slot)                     ─→  PR merged? checkout base + drop worktree
                                     ←─  freed slot

   doctor()                          ─→  21-code / 11-category integrity scan + fix hints
                                     ←─  findings + fix_actions
```

Path resolution lives entirely in `actions/aliases.py` (`resolve_feature`,
`repos_for_feature`), `actions/repo_paths.py` (`resolve_repo_paths`), and
`agent/runner.py` (`canopy_run`). It never crosses the MCP boundary, so the agent
has no surface area to type a wrong path. **Enforcement** closes the loop: canopy
ships Claude Code hooks — `hook_gate.py` (a PreToolUse Bash gate that resolves the
effective directory of a git command through cd-chains, `git -C`, and heredocs,
then blocks mutations from the wrong path/branch) and `hook_context.py` (a
SessionStart orientation brief).

Management verbs the agent no longer calls — `triage`, `feature_resume`,
`feature_state`, `ship`, `review_*`, `draft_replies`, the historian and thread
tools, and the Linear/GitHub reads — remain fully wired on the **CLI** (`canopy
triage --json`, `canopy resume --json`, …) for the human and the dashboard.

### feature_state composition

`feature_state` is now a **management module** (`management/feature_state.py`,
reached via `canopy state --json`, not MCP). It is a thin shell over many
primitives — the most-composed example of the action pattern. Decision tree across
the 9 states:

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

The ninth state (`awaiting_bot_resolution`) is reached when open bot-authored review threads exist but no human CHANGES_REQUESTED is present — bot threads alone route here, not to `needs_work`. See [concepts.md](concepts.md#3-the-feature-state-machine) for the full state table. Note that `feature_state` reads `preflight_state` — an agent-core primitive — but the reverse is forbidden by the import boundary; management reaches down into agent-core, never the other way.

### Drift detection: two pathways

Two paths exist because they answer different questions and have different costs.

```
  ┌─ Cached fast path (canopy drift, drift MCP tool) ──────────────┐
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

  ┌─ Live correct path (canopy state — management surface) ────────┐
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

`drift` is the agent-facing tool (cached, cheap); `feature_state` is the live,
authoritative management read. Separately, `advisories.py` surfaces registry/disk
drift as *advisory* signals (observe, never enforce) — the enforcing counterpart
is the `hook_gate.py` PreToolUse gate.

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

The slot model is the runtime guarantee that at most one canonical checkout and `N` warm worktrees exist at any time. `switch` is the only public entry point; `slots.py`, `slot_policy.py`, `slot_load.py`, `slot_bootstrap.py`, and `switch_preflight.py` are its internal implementation. Trunk (canonical) is the only place to *run* full-stack; warm slots are the workbench for PR-review changes — intent decides whether you switch (review changes happen in the worktree, no switch; `switch X` moves X into trunk only to run it). See [concepts.md §4](concepts.md#4-the-slot-model).

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

**Warm-vs-cold policy.** When a feature vacates trunk, `slot_policy.py` decides its fate: **warm** (keep a worktree) iff it has an open PR (it's being shepherded) or live WIP; otherwise **cold** + a feature-tagged stash. A newly created slot is made workable by `slot_bootstrap.py` — fast steps (env, IDE, husky hooks) run synchronously so the worktree is usable immediately; dependency installs run in the background with a loud failure state.

**Transaction safety.** `in_flight` is set atomically before a multi-repo switch starts and cleared on success. If the process is interrupted mid-flight, subsequent `switch()` calls detect a non-null `in_flight` and raise `BlockerError(code='slot_state_inconsistent')`. Recovery is via `canopy doctor`, which inspects actual worktree paths and reconstructs a consistent state.

**LRU eviction policy.** When the slot cap (`slots = N`, default 2) is reached and the caller did not pass `--evict-to`, canopy raises `BlockerError(code='worktree_cap_reached')` with the LRU candidate in `details`. Canopy never silently evicts — the human or the agent must explicitly choose. The LRU ordering is computed from `last_touched` timestamps; the slot with the oldest entry is the eviction candidate.

**Slot identity is stable; feature occupancy is transient.** Slot directories (`worktree-1/`, `worktree-2/`) persist across feature swaps. A slot keeps its numbered id; features move in and out. This means pre-built worktrees re-use their node_modules, venvs, and build artifacts when a feature rotates back into the same slot. `reclaim` frees a warm slot when its PR merges (checkout base + drop the worktree).

## Resume and threads (management surface)

`feature_resume` (via `management/resume.py`, reached by `canopy resume --json`) is the session-start primitive for returning to a feature — a **human/dashboard** tool now, not an MCP tool; the agent orients via `context()` instead. It orchestrates: alias resolution, data refresh (historian + bot_status + review_filter + pr_checks + linear), and brief-section composition. The result is a structured `{state, since_ts, commits_delta, open_threads, bot_threads, checks, intent_hints}` snapshot scoped to activity since the last visit.

**Single-bump invariant.** Exactly one `mark_visited` call happens per `feature_resume` invocation. The `visits.json` anchor never moves twice for the same resume.

**Thread round-trip.** `management/thread_actions.py` and `management/thread_resolutions.py` close the GitHub review-thread loop: canopy can resolve threads and reply via GraphQL, with attribution logged locally to `thread_resolutions.json`. `filter_since` scopes the log to the current visit window, so the resume brief can report "N threads resolved by canopy since last visit" without re-reading all history.

## State files

What state lives where, who writes it, who reads it:

| Path | Writer | Readers | Purpose |
|---|---|---|---|
| `canopy.toml` | `canopy init` | all canopy commands | workspace definition (repos, slots cap, augments) |
| `.canopy/features.json` | `start` / `join` / `link_linear` / `done` | most actions | feature lanes + Linear links + per-repo branches map |
| `.canopy/state/active.json` | `start` | `context`, `advisories`, `join` | intended-focus pointer (which feature the session works on) |
| `.canopy/state/heads.json` | post-checkout hook | `drift`, `doctor` | drift fast path |
| `.canopy/state/heads.json.lock` | post-checkout hook | (fcntl flock) | concurrent-fire safety |
| `.canopy/state/preflight.json` | `preflight` / `review_prep` | `feature_state` | in_progress vs ready_to_commit |
| `.canopy/state/slots.json` | `switch` / `slot_load` / `slot_clear` / `slot_swap` | `context`, `triage`, `slots`, `doctor` | canonical + slot occupancy + last_touched LRU + in_flight marker |
| `.canopy/state/prs.json` | `pr_map` / `prs_cache` | `context` (remote tier), `triage` | offline fallback cache for the PR/CI overlay |
| `.canopy/state/visits.json` | `last_visit.mark_visited` | `resume`, `draft_replies` | per-feature `{last_visit, previous_visit}` anchor |
| `.canopy/state/thread_resolutions.json` | `thread_resolutions.record` | `resume`, `draft_replies` | GH threads canopy resolved: `{thread_id: {resolved_by_canopy_at, feature, …}}` |
| `.canopy/state/bot_resolutions.json` | `bot_resolutions.record_resolution` | `bot_status`, `feature_state` | per-comment resolution log for bot-authored comments |
| `.canopy/memory/<feature>.md` | `historian` | `resume` | cross-session feature memory (plain markdown) |
| `.mcp.json` | `canopy init` / `setup-agent` | MCP-aware clients | server registry |
| `~/.canopy/mcp-tokens/<server>.{client,tokens}.json` | `mcp/client.py` OAuth provider | `mcp/client.py` | OAuth token cache (per-user) |
| `~/.claude/skills/<skill>/SKILL.md` | `canopy init` / `setup-agent` | Claude Code (auto-loaded) | agent integration skills (using-canopy, augment-canopy) |

All workspace state lives under `.canopy/`; agent and per-user state lives under `~/`. The split lets you share workspace state via git (commit `.canopy/features.json` if you want; ignore `.canopy/state/`), while OAuth tokens and skills never leave the user's machine.
