<p align="center">
  <img src="docs/canopy-banner.svg" alt="canopy — typed multi-repo work for AI coding agents" width="600">
</p>

<p align="center">
  <em>The typed multi-repo MCP server your AI coding agent needs.</em>
</p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white">
  <img alt="Tests" src="https://img.shields.io/badge/tests-857%20passing-brightgreen?style=flat-square">
  <img alt="MCP Tools" src="https://img.shields.io/badge/MCP%20tools-67-purple?style=flat-square">
  <a href="https://marketplace.visualstudio.com/items?itemName=SingularityInc.canopy"><img alt="VSCode Extension" src="https://img.shields.io/badge/VSCode-extension-blue?style=flat-square&logo=visualstudiocode"></a>
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-gray?style=flat-square">
</p>

---

Canopy is built for workspaces with **multiple repos that share a feature lifecycle** — backend + frontend, api + mobile, a monolith plus its services. That setting breaks coding agents in specific, fixable ways: shell state doesn't survive between tool calls, paths get constructed wrong, drift accumulates silently between repos, and PR review work pulls the agent across repo boundaries faster than its context can keep up.

Canopy gives the agent a typed contract for that setting — `feature` / `repo` / alias inputs, structured outputs, recoverable errors — so it can drive multi-repo feature work end-to-end without ever shelling `cd /wrong/repo`.

```python
# Without canopy: brittle paths, parsed stderr, no shared state across repos.
bash("cd /Users/.../web/api && git status")
bash("cd /Users/.../web/ui && git status")
bash("gh pr list --author @me --json number,title")
# ... then per-thread "is this still actionable?" logic in the agent's head

# With canopy: one typed call, structured multi-repo response, recoverable error.
mcp__canopy__feature_state(feature="auth-flow")
# → { "state": "needs_work",
#     "next_actions": ["address_review_comments"],
#     "summary": {
#       "ci_aggregate": "passing",
#       "actionable_human_count": 2,
#       "repos": {
#         "api": { "dirty_file_count": 3, "ahead": 2, "behind": 0, "pr": {...} },
#         "ui":  { "dirty_file_count": 0, "ahead": 0, "behind": 0, "pr": {...} }
#       }
#     }
#   }
```

The CLI is the surface humans use to drive the same primitives. Same JSON, two consumers.

## Why multi-repo work breaks coding agents

Each `mcp__canopy__*` tool closes one failure mode that agents reliably hit when the workspace has more than one repo:

| Failure mode | Canopy's fix |
|---|---|
| **Shell state evaporates between tool calls.** `cd /repo-a && command` doesn't persist; the next call lands somewhere else. Multi-repo makes this worse because there's more than one "right" place to land. | Every canopy tool takes `feature` / `repo` / alias as parameters; path resolution lives inside canopy. The agent has no surface area to type the path. |
| **Cross-repo state is invisible.** `git status` in one repo doesn't tell you what's happening in the other. The agent has to query each repo separately and stitch the picture. | `mcp__canopy__feature_state(feature)` returns the full multi-repo picture in one call: per-repo dirty/ahead/behind, PRs, CI, computed state, prioritized next actions. |
| **Drift between tool calls.** The agent `git checkout`'d X in one repo, the next call assumes the OTHER repo is also on X; things go sideways. | Per-repo post-checkout hooks write `.canopy/state/heads.json` (fcntl-locked, atomic-renamed). `mcp__canopy__drift` reads cached state in <50ms. The agent sees misalignments that happened between calls, even when it didn't cause them. |
| **Session re-derivation.** Each new chat re-walks `gh pr list`, `git status` per repo, comment threads, CI status — burning context on bookkeeping the previous chat already did. | `mcp__canopy__feature_resume(alias)` is one call: alias → switch focus if needed → refresh GH+Linear → return structured brief of what changed since last visit. Cross-session state via `.canopy/state/visits.json` + per-feature memory at `.canopy/memory/<feature>.md`. |
| **PR review churn across repos.** A feature with two PRs (one per repo) accumulates threads on both; the agent re-classifies "is this still actionable?" every turn. | `mcp__canopy__github_get_pr_comments(alias)` returns threads pre-bucketed as `actionable` / `likely_resolved` via temporal filtering (comment timestamp vs commits-on-file-since). Resolved threads carry `by_canopy: true` attribution when canopy itself closed them. |
| **Closing GH threads needs raw GraphQL.** REST has no thread IDs; agents fumble with `gh api graphql` query strings. | `mcp__canopy__resolve_thread(thread_id)`, `mcp__canopy__reply_to_thread(thread_id, body, resolve_after=True)`, and `mcp__canopy__commit(address=<id>, resolve_thread=True)` handle the wire format and log resolutions locally for attribution. |
| **Juggling 2–3 features in parallel** loses in-progress work to forgotten stashes or breaks when one repo gets `git checkout`'d alone. | The slot model (Wave 3.0): each feature lives in `canonical` / `warm` / `cold`. `mcp__canopy__switch(feature)` rotates focus atomically across every repo in the feature's lane, evacuating the previous canonical into a warm slot with `stash → checkout → pop`. |
| **Errors come back as stderr text.** Agents have to parse English failure messages to decide recovery. | Structured `BlockerError(code, what, expected, actual, fix_actions)`, each fix carrying `safe: bool` so the agent knows what's auto-runnable vs needs human confirmation. |

## Install

Requires Python 3.10+.

```bash
pipx install git+https://github.com/ashmitb95/canopy.git
cd ~/your-multi-repo-workspace
canopy init
```

If you don't have pipx: `brew install pipx && pipx ensurepath`.

`canopy init` does four things:
1. Discovers your git repos and writes `canopy.toml`.
2. Installs the drift-detection post-checkout git hook in every repo.
3. **Wires the canopy MCP server into Claude Code** by writing a `.mcp.json` entry — this is what makes the agent surface live.
4. Installs the `using-canopy` skill at `~/.claude/skills/using-canopy/SKILL.md` so the agent knows when to reach for canopy tools.

Skip the agent bits with `--no-agent` if you're just using the CLI.

<p align="center">
  <img src="docs/cli-init.svg" alt="canopy init" width="720">
</p>

## The 67-tool surface

Every CLI command has an `mcp__canopy__*` MCP equivalent returning the same JSON. The MCP server is the load-bearing surface for agents; the CLI is the side benefit for humans. Tools by topic:

### Session-start + state

| Tool | What it does |
|---|---|
| `feature_resume(alias)` | The headline primitive. Resolves alias → switches canonical if needed → refreshes GitHub + Linear → returns the structured brief (`since_last_visit`, `current_state`, `intent_hints`). Call this first when a chat opens on a feature. |
| `feature_state(feature)` | 9-state machine (`drifted`, `needs_work`, `awaiting_bot_resolution`, `in_progress`, `ready_to_commit`, `ready_to_push`, `awaiting_review`, `approved`, `no_prs`) + `next_actions` array. Drives the agent's decision tree. |
| `triage` | Cross-feature priority view. Returns features ordered by review-state urgency. |
| `slots(rich=True)` | Dashboard data — canonical + every warm slot with per-repo branch, dirty, ahead/behind, PR, CI, bot threads, Linear, computed `feature_state`. |

### Focus management (the slot model)

| Tool | What it does |
|---|---|
| `switch(feature)` | Promote a feature into the canonical slot. Previous canonical evacuates into a warm slot (active rotation, default) or goes cold with feature-tagged stash (`release_current=True`). Atomic across every repo in the feature's lane. |
| `slot_load(feature, slot_id?)` | Warm a cold feature into a slot **without** changing canonical. Use for pre-warming or inspecting a feature you're not ready to focus on. |
| `slot_clear(slot_id)` | Vacate a slot to cold (feature-tagged stash if dirty). The slot remains, just empty. |
| `slot_swap(slot_a, slot_b)` | Exchange the occupants of two warm slots. |
| `migrate_slots()` | One-shot migration from pre-3.0 layouts. |

### PR review work

| Tool | What it does |
|---|---|
| `github_get_pr_comments(alias)` | Returns `actionable_threads` + `likely_resolved_threads` per repo. Temporal filter has already classified what's worth the agent's attention. |
| `resolve_thread(thread_id, feature?)` | Close a GH review thread via GraphQL + log to `.canopy/state/thread_resolutions.json` for attribution. |
| `reply_to_thread(thread_id, body, feature?, resolve_after=False)` | Post a reply; optionally close after. |
| `commit(message, feature?, address=<id>, resolve_thread=False)` | Commit across the feature's repos. With `address=<comment_id>`, auto-suffixes the message + logs to `bot_resolutions.json`. With `resolve_thread=True`, closes the corresponding GH thread. |
| `bot_comments_status(feature)` | Per-PR bot-comment rollup: total / resolved / unresolved. |
| `draft_replies(feature)` | File-history-based addressed-comment detector + reply templates. |

### Operate across repos without `cd`

| Tool | What it does |
|---|---|
| `preflight(feature?)` | Run each repo's preflight hooks (or `[augments] preflight_cmd` override). Records result for the state machine. |
| `push(feature?)` | Push across every repo in the feature's lane. `set_upstream=True` on first push. |
| `run(repo, command)` | Path-safe shell exec. Canopy resolves the cwd to the right repo dir; the agent never types a path. |

### Read + alias resolution

| Tool | What it does |
|---|---|
| `linear_get_issue(alias)`, `linear_my_issues` | Linear issue data via the issue-provider abstraction. |
| `github_get_pr(alias)`, `github_get_branch(alias)` | PR + branch data. |
| `issue_get(alias)` | Provider-agnostic issue read (Linear or GitHub Issues). |

Every read tool accepts the same alias forms:
- Feature name: `auth-flow`
- Linear issue ID: `TEAM-101` (resolves via lane's `linear_issue`)
- Specific PR: `<repo>#<n>` like `api#142`
- PR URL: `https://github.com/owner/repo/pull/142`
- Specific branch: `<repo>:<branch>`
- Slot id: `worktree-1`, `worktree-2`, ... (resolves to the slot's current occupant)

### Recovery

| Tool | What it does |
|---|---|
| `doctor` | 21 diagnostic codes across 12 categories of state-file drift + install staleness. Each issue carries `severity`, `expected` / `actual`, and an `auto_fixable` flag. `doctor(fix=True)` runs the safe auto-fixes. First call when something feels off. |
| `version` | `{cli_version, mcp_version, schema_version}` handshake. Doctor reports `cli_stale` / `mcp_stale` when these drift. |

### Cross-session memory

`feature_memory(feature)`, `historian_decide(feature, decisions)`, `historian_pause(feature, reason)`, `historian_defer_comment(feature, comment_id, reason)`, `historian_compact(feature, keep_sessions)` — persistent per-feature memory at `.canopy/memory/<feature>.md`. Auto-captured by `commit --address` and `github_get_pr_comments`. Read on `switch` to recover prior session context without re-deriving.

Full reference: [docs/mcp.md](docs/mcp.md).

## The slot model

Every feature lives in one of three states:

- **canonical** — checked out in the main repo dirs. Exactly one canonical feature at a time across all repos. **This is the only place to run code.** Worktrees are passive branch storage; never `cd` into them to launch the app.
- **warm** — sits in a numbered slot at `.canopy/worktrees/worktree-N/<repo>/`. Slot identity (`worktree-1`, `worktree-2`, ...) is stable across feature swaps; feature occupancy is transient. Capped by `[workspace] slots = N` in canopy.toml (default 2).
- **cold** — branch only, no checkout. Cheap and unlimited.

`switch(Y)` is the single primitive that moves features between these states:

- **Active rotation (default):** previous canonical evacuates into a warm slot via `stash → checkout → pop`. Instant to switch back.
- **Wind-down (`release_current=True`):** previous goes cold with a feature-tagged stash.

When the cap fires, `switch` returns `BlockerError(code='worktree_cap_reached')` with explicit `fix_actions` (evict a specific slot, wind down the current focus, raise the cap). **No silent eviction.**

Full design: [docs/concepts.md §4](docs/concepts.md#4-the-slot-model).

## Structured errors

Every error is a typed payload — agents don't parse stderr.

```json
{
  "status": "blocked",
  "code": "drift_detected",
  "what": "branches don't match feature lane 'auth-flow'",
  "expected": {"branches": {"api": "auth-flow", "ui": "auth-flow"}},
  "actual":   {"branches": {"api": "auth-flow", "ui": "main"}},
  "fix_actions": [
    {"action": "switch", "args": {"feature": "auth-flow"}, "safe": true,
     "preview": "promote auth-flow to canonical across all repos"}
  ]
}
```

The agent reads `fix_actions[0]`, checks `safe: true`, calls `mcp__canopy__switch(feature="auth-flow")`. The CLI renders the same payload as colored multi-line output via [`cli/render.py`](src/canopy/cli/render.py). Single source of truth, two surfaces.

## Agent integration

`canopy init` installs the `using-canopy` skill at `~/.claude/skills/using-canopy/SKILL.md` (per-user) and writes `.mcp.json` so Claude Code spawns the canopy MCP server in this workspace. The skill teaches the agent when to reach for canopy:

- See a feature alias or issue ID as the first non-trivial token? Call `feature_resume(alias)` before doing anything else.
- About to `cd <repo> && command`? Use `mcp__canopy__run(repo, command)` or the feature-aware verb.
- About to `gh api graphql` for thread mutations? Use `resolve_thread` / `reply_to_thread` / `commit --address --resolve-thread`.
- See an unfamiliar error? Call `doctor` first.

Opt-in extra skills via `canopy setup-agent --skill <name>`:
- [`augment-canopy`](src/canopy/agent_setup/skills/augment-canopy/SKILL.md) — teaches the agent the `canopy.toml [augments]` schema so it can configure `preflight_cmd`, `review_bots`, `auto_resolve_threads_on_address`, etc. on the user's behalf.

GitHub access works via the `gh` CLI fallback when no `github` MCP server is configured. Linear works via OAuth (browser flow once, no API key).

## For humans

The same primitives are available as a CLI. Daily commands:

```bash
canopy resume <feature>     # session start — print the brief
canopy switch <feature>     # focus — promote to canonical
canopy status               # workspace-wide rollup
canopy state <feature>      # 9-state + next_actions
canopy triage               # cross-feature priority
canopy preflight            # run hooks across the feature's repos
canopy commit -m "..."      # commit across repos at once
canopy push                 # push across repos at once
canopy slots --rich         # dashboard data
canopy doctor               # diagnose drift / staleness
```

<p align="center">
  <img src="docs/cli-state.svg" alt="canopy state" width="720">
</p>

The CLI and MCP server are thin wrappers over the same actions — `canopy state X` and `mcp__canopy__feature_state(feature='X')` return identical bytes. There's also a [VSCode extension](https://marketplace.visualstudio.com/items?itemName=SingularityInc.canopy) reading the same state the agent reads.

Full CLI reference: [docs/commands.md](docs/commands.md).

## Docs

- [Concepts](docs/concepts.md) — the action framework, agent context contract, 9-state machine, slot model, resume brief
- [Agents](docs/agents.md) — skill install, integration recipes, the agent tool loop
- [Commands](docs/commands.md) — full CLI reference
- [MCP](docs/mcp.md) — server tool list, client transports (stdio + HTTP/OAuth), gh fallback
- [Workspace](docs/workspace.md) — `canopy.toml`, `features.json`, state files
- [Architecture](docs/architecture.md) — module boundaries, runtime pathways, state files
- [Providers](docs/architecture/providers.md) — issue-provider abstraction (Linear, GitHub Issues)

## Develop

```bash
git clone https://github.com/ashmitb95/canopy.git ~/projects/canopy
cd ~/projects/canopy
pip install -e ".[dev]"
pytest tests/ -v             # 857 tests, ~225s, all use real temporary Git repos
```

## License

MIT
