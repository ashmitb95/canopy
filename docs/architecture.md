# Architecture

```
src/canopy/
├── cli/
│   ├── main.py                # argparse CLI — thin layer, no business logic
│   ├── ui.py                  # rich terminal output (theme, spinners, colors)
│   └── render.py              # structured-error renderer (BlockerError → multi-line CLI)
├── workspace/
│   ├── config.py              # canopy.toml parser (RepoConfig, WorkspaceConfig)
│   ├── discovery.py           # auto-detect repos + worktrees, generate toml
│   ├── context.py             # context detection from cwd
│   └── workspace.py           # Workspace class, RepoState dataclass
├── git/
│   ├── repo.py                # ALL git subprocess calls (single-repo only)
│   ├── multi.py               # cross-repo operations (calls repo.py)
│   ├── hooks.py               # install/uninstall post-checkout hook + state file reader
│   └── templates/
│       └── post-checkout.py   # hook script template (CANOPY_REPO + CANOPY_WORKSPACE_ROOT subbed in)
├── features/
│   └── coordinator.py         # FeatureLane + lifecycle (status, switch, diff, done, review_*)
├── actions/                   # Wave 2+: action layer — completion-driven recipes over primitives
│   ├── errors.py              # ActionError / BlockerError / FailedError / FixAction
│   ├── aliases.py             # universal alias resolver (feature, repo#n, repo:branch, URL)
│   ├── active_feature.py      # .canopy/state/active_feature.json reader/writer + last_touched LRU
│   ├── drift.py               # detect_drift + assert_aligned (cached path)
│   ├── evacuate.py            # per-repo evacuate primitive (stash → wt-add → pop)
│   ├── feature_state.py       # 8-state machine + next_actions (dashboard backend, worktree-aware)
│   ├── preflight_state.py     # .canopy/state/preflight.json read/write + freshness check
│   ├── reads.py               # linear_get_issue / github_get_pr / github_get_branch / github_get_pr_comments
│   ├── realign.py             # internal helper used by switch (deprecated from CLI/MCP in Wave 2.9)
│   ├── review_filter.py       # temporal classifier (actionable vs likely_resolved threads)
│   ├── stash.py               # feature-tagged stash save/list/pop
│   ├── switch.py              # canonical-slot focus primitive (active rotation + wind-down)
│   ├── switch_preflight.py    # predictable-failure detection for switch
│   └── triage.py              # cross-repo PR enumeration + canonical-slot enrichment
├── agent/
│   └── runner.py              # canopy_run — directory-safe shell exec (no path management)
├── agent_setup/               # ships the using-canopy skill + sets up MCP per workspace
│   ├── __init__.py            # install_skill / install_mcp / setup_agent / check_status
│   └── skill.md               # the skill content (canonical source; copies to ~/.claude/skills/)
├── integrations/
│   ├── linear.py              # Linear issue fetching (via mcp/client.py)
│   ├── github.py              # GitHub PR + review comments (MCP or gh CLI fallback)
│   └── precommit.py           # detect + run pre-commit hooks (framework or git hooks)
└── mcp/
    ├── server.py              # MCP server — 41 tools, stdio transport
    └── client.py              # MCP client — stdio + HTTP+OAuth transports
```

## Key boundaries

- **`git/repo.py` is the only module that calls `subprocess.run(["git", ...])`.** Everything else goes through it. The git layer stays replaceable and testable.
- **`mcp/server.py` and `cli/main.py` are thin wrappers.** Business logic lives in `actions/`, `features/coordinator.py`, `git/multi.py`, and `workspace/`. Adding a CLI command + MCP tool is mostly registering an existing function in two places.
- **All external integrations go through `mcp/client.py` (or `gh` CLI fallback).** No direct API calls anywhere in the codebase.
- **Actions wrap primitives.** An `actions/*.py` function composes `git/`, `integrations/`, and `workspace/` calls into a verified workflow. Actions return structured `BlockerError` / dict; never `print()`. The CLI / MCP layers do their own rendering.
- **The agent context contract.** Every action that takes multi-repo state takes semantic inputs (`feature`, `repo`, alias). Path resolution lives inside `workspace/` and `actions/aliases.py`. See [concepts.md](concepts.md#2-the-agent-context-contract).
- **State persistence is split.** Cached state (`.canopy/state/heads.json`, `.canopy/state/preflight.json`) is for fast paths (drift, state machine warm-up). Live git is the source of truth for write actions and `feature_state`. OAuth tokens cache in `~/.canopy/mcp-tokens/` (per-user, not per-workspace).

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
                                     ←─  features ordered by priority

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
                                         per repo (Wave 2.9 canonical-slot):
                                           if Y warm   → worktree_remove(Y)
                                           if X exists → evacuate_repo(X):
                                                            git.stash (if dirty)
                                                            git.checkout(target Y)
                                                            git.worktree_add(X)
                                                            git.stash_pop in worktree
                                           else        → git.stash + git.checkout
                                         active_feature.write (canonical + last_touched)
                                     ←─  {feature, mode, per_repo_paths,
                                          previously_canonical, eviction?, branches_created?}

   feature_state(feature)            ─→  …
                                     ←─  state advanced (e.g. drifted → in_progress)

   ── agent edits files via Read/Edit/Write ──
   ── or runs path-safe shell via run(repo, command) ──

   preflight(feature)                ─→  precommit hooks per repo (sequential v1)
                                         preflight_state.record_result()
                                     ←─  per-repo {passed, output}

   feature_state(feature)            ─→  …
                                     ←─  state: ready_to_commit
```

Path resolution lives entirely in `actions/aliases.py` (`resolve_feature`, `repos_for_feature`) and `agent/runner.py` (`canopy_run`). It never crosses the MCP boundary, so the agent has no surface area to type a wrong path.

### feature_state composition

`feature_state` is a thin shell over many primitives — same pattern other actions follow, but the most-composed example. Decision tree:

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
    ├─ preflight_state.is_fresh(repos)     compares recorded sha vs current HEAD
    │
    └─ _decide_state(facts, summary, preflight_fresh, preflight_entry):
        ├─ dirty + fresh-passed-preflight       → ready_to_commit
        ├─ dirty                                 → in_progress
        ├─ clean + ahead > 0                     → ready_to_push
        ├─ clean + actionable | CHANGES_REQUESTED → needs_work
        ├─ clean + all PRs APPROVED              → approved
        ├─ clean + no PRs                        → no_prs
        └─ clean + PRs open + nothing actionable → awaiting_review
```

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

## State files

What state lives where, who writes it, who reads it:

| Path | Writer | Readers | Purpose |
|---|---|---|---|
| `canopy.toml` | `canopy init` | all canopy commands | workspace definition (which repos) |
| `.canopy/features.json` | `feature_create` / `link_linear` / `done` | most actions | feature lanes + Linear links + branches map |
| `.canopy/state/heads.json` | post-checkout hook | `drift`, `hook_status` | drift fast path |
| `.canopy/state/heads.json.lock` | post-checkout hook | (fcntl flock) | concurrent-fire safety |
| `.canopy/state/preflight.json` | `review_prep` / `cmd_preflight --feature` | `feature_state` | IN_PROGRESS vs READY_TO_COMMIT |
| `.mcp.json` | `canopy init` / `setup-agent` | MCP-aware clients (Claude Code, Cursor) | server registry |
| `~/.canopy/mcp-tokens/<server>.{client,tokens}.json` | `mcp/client.py` OAuth provider | `mcp/client.py` on subsequent calls | OAuth token cache |
| `~/.claude/skills/using-canopy/SKILL.md` | `canopy init` / `setup-agent` | Claude Code (auto-loaded) | agent integration skill |

All workspace state lives under `.canopy/`; agent / per-user state lives under `~/`. The split lets you share workspace state via git (commit `.canopy/features.json` if you want; ignore `.canopy/state/`), while OAuth tokens and skill never leave the user's machine.
