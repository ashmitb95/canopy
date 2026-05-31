---
name: using-canopy
description: Use when working in a multi-repo workspace that has canopy.toml or .canopy/ — prefer canopy MCP tools (mcp__canopy__*) over raw git/gh/bash to avoid path-management mistakes and to get pre-classified state and review data.
---

# Using canopy

Canopy is a multi-repo workspace orchestrator. When you see `canopy.toml` or a `.canopy/` directory at the workspace root, canopy is configured. The `mcp__canopy__*` tools are your primary surface for repo, branch, and PR operations in that workspace.

## Why prefer canopy over raw git/gh

The single biggest agent failure mode in multi-repo work is path mistakes — `cd /wrong/repo && git status`, `git checkout` in repo A when you meant repo B, `pnpm test` in the API repo because the previous shell call left you there. Canopy eliminates this class of bug by accepting only **semantic** inputs (`feature`, `repo`, alias) and resolving paths internally. You literally cannot `cd` to the wrong place because you never specify a path.

Canopy also returns **pre-classified state**: review comments are temporally filtered into `actionable_threads` vs `likely_resolved_threads`, features have computed states like `ready_to_commit` / `drifted` / `awaiting_review`, and every action returns structured `next_actions` you can follow without re-deriving the rules.

## Session start — call `feature_resume` first

When the user opens a chat and references a feature alias (a Linear issue ID like `TEAM-101`, a feature name, a slot id like `worktree-1`, or a PR URL/`<repo>#<n>`), call `mcp__canopy__feature_resume(<alias>)` *before* acting on whatever intent they've stated. This is a compound action: it resolves the alias, switches the canonical slot if it's not already there, refreshes from GitHub + Linear, and returns a structured brief with `intent_hints` for the most likely next actions.

Patterns that trigger this:
- A bare alias as the first non-trivial token: `"TEAM-101"`, `"TEAM-101, let's address comments"`, `"jump into auth-flow"`.
- Explicit return: `"I am back on TEAM-101"`, `"resuming auth-flow"`.
- Topic-shift to another feature mid-session.

Once you have the brief, look at `intent_hints` (sorted by `priority`) and pair the top hint with what the user said. Examples:

| User says | Top hints | Your move |
|---|---|---|
| "address PR comments" | `address_comments`, `post_drafts` | call `review_comments` with the alias from `intent_hints[0].suggested_args`, then walk through actionable threads |
| "align with dev" | `align_with_default` | inspect `current_state.branch_position_per_repo`, propose rebase or merge per repo |
| (nothing specific) | (read top 3 hints) | summarize the brief + hints in 3–5 lines, ask the user which to pursue |

Do **not** call `feature_resume` more than once per session per feature unless you've done work that materially changes state (e.g. pushed, resolved a thread, posted replies). The brief is fresh-per-call (refreshes GH/Linear) so repeated calls are wasteful, not stale.

`feature_resume` supersedes `mcp__canopy__switch` as the session-start primitive — it does the switch internally plus the full brief. Use `switch` directly only when you want to focus a slot without the overhead of a fresh brief (e.g. mid-session slot rotation).

### Closing out review threads

When you finish reviewing a thread:
- If your commit addresses it: `commit --address <comment_id> --resolve-thread` (or post-process with `mcp__canopy__resolve_thread`).
- If the comment is wrong: `mcp__canopy__reply_to_thread <thread_id> <body>` with concrete evidence. Pass `resolve_after=true` when the pushback closes the discussion.

## Tool selection — what to use when

| What you want to do | Canopy tool | Don't use |
|---|---|---|
| What feature should I work on right now? | `mcp__canopy__triage` | per-repo `gh pr list` + manual grouping |
| Show me everything about a feature | `mcp__canopy__feature_state` | composing many reads yourself |
| Promote a feature to the canonical slot (the focus primitive) | `mcp__canopy__switch` | `cd repo && git checkout` per repo, or guessing paths |
| Inspect slot occupancy (dashboard grid) | `mcp__canopy__slots(rich=True)` | hand-rolling `ls .canopy/worktrees/` + per-slot `feature_state` |
| Pre-warm a cold feature into a slot without changing canonical | `mcp__canopy__slot_load(feature, slot_id?)` | `mcp__canopy__switch` (changes canonical too) |
| Free a slot without bringing a new feature in | `mcp__canopy__slot_clear(slot_id)` | manual stash + branch checkout |
| Exchange two slots' occupants | `mcp__canopy__slot_swap(slot_a, slot_b)` | two `slot_load` calls with `replace=True` |
| Migrate a pre-3.0 workspace to the slot model | `mcp__canopy__migrate_slots` | hand-renaming `.canopy/worktrees/` dirs |
| Hibernate current focus + start something new | `mcp__canopy__switch(feature, release_current=True)` *(`release_current` is the API param; user-facing label is "hibernate")* | manual stash + checkout dance |
| Commit across the canonical feature (one message, all repos) | `mcp__canopy__commit(message=...)` *(canonical feature inferred; pass `feature=` for non-canonical)* | `mcp__canopy__run(... 'git commit')` per repo |
| Push the canonical feature to origin | `mcp__canopy__push()` *(add `set_upstream=True` on first push; the `no_upstream` blocker tells you when)* | `mcp__canopy__run(... 'git push')` per repo |
| Check whether HEADs match expected | `mcp__canopy__drift` | `cd && git branch --show-current` per repo |
| Recover from "something is off" — opaque errors, missing paths, stale state | `mcp__canopy__doctor` (then `doctor(fix=True)` if `auto_fixable`) | hunting through stash lists / worktree paths manually |
| Read PR review comments (temporally filtered) | `mcp__canopy__github_get_pr_comments` | `gh api .../comments` + manual filter |
| Get PR data (title, decision, draft, ...) | `mcp__canopy__github_get_pr` | `gh pr view --json ...` per repo |
| Get branch HEAD/divergence/upstream | `mcp__canopy__github_get_branch` | `cd repo && git status -b` |
| Fetch an issue (Linear / GitHub Issues — provider-agnostic) | `mcp__canopy__issue_get` | direct API |
| Run a shell command in a specific repo | `mcp__canopy__run` | `cd /path && cmd` (path mistake risk) |
| Stash dirty changes for a feature | `mcp__canopy__stash_save_feature` | raw `git stash push` |
| List/restore stashes by feature | `mcp__canopy__stash_list_grouped` / `stash_pop_feature` | `git stash list` + manual filter |

## The daily workflow loop

```
1. triage()                 → pick a feature from the prioritized list
2. feature_state(feature)   → get current state + next_actions
3. follow next_actions[0]   → primary CTA (canopy decided what to do next)
4. feature_state again      → confirm state advanced
5. repeat
```

The `next_actions` array is canopy's recommendation. Trust it unless you have a specific reason not to.

## Aliases

Every tool that takes a feature accepts the same alias forms — learn one rule, use everywhere:
- **Feature name**: `SIN-12-search`
- **Linear issue ID**: `SIN-12` (resolves through the lane's `linear_issue` field)
- **Specific PR**: `<repo>#<n>` like `backend#142`
- **PR URL**: `https://github.com/owner/repo/pull/142`
- **Specific branch**: `<repo>:<branch>` like `backend:feature/x`
- **Slot id**: `worktree-1`, `worktree-2`, ... — resolves to the slot's current occupant (Wave 3.0). Lets you say "tell me about worktree-2" without first looking up what's in it.

For features whose branch name differs across repos (e.g. `SIN-13-fixes` in backend vs `SIN-13-fixes-v2` in frontend), the lane's `branches` map handles this transparently. You pass the canonical feature alias; canopy resolves per-repo branches.

## Slots (Wave 3.0)

Canopy organizes worktrees into **numbered slots** — `.canopy/worktrees/worktree-1/`, `.canopy/worktrees/worktree-2/`, etc. A slot is a stable disk resource; the feature inside it is a transient tenant. When you `switch` from feature X to feature Y, the slot ids don't change — only which feature occupies which slot.

**Want to see what's in each slot?** Call `mcp__canopy__slots` (defaults to `rich=True`) — returns the full dashboard grid in a single call: canonical + every warm slot, each with per-repo branch / dirty / ahead-behind / PR / CI / bot threads / linear / computed `feature_state`. Empty slots come back as explicit `null`.

The slot vocabulary (CLI + MCP parity):

- `mcp__canopy__switch(feature)` — promote a feature to canonical. Slot rotation is automatic. `evict_to=<slot-N>` pins where the outgoing canonical lands; `to_slot=<slot-N>` promotes whatever feature already sits in that slot.
- `mcp__canopy__slot_load(feature, slot_id?)` — warm a cold feature into a slot **without** changing canonical. Use this to pre-warm a slot before review or before a planned switch. `replace=True` evicts the current occupant to cold first.
- `mcp__canopy__slot_clear(slot_id)` — evict that slot's occupant to cold (with feature-tagged stash if dirty). The slot itself remains.
- `mcp__canopy__slot_swap(slot_a, slot_b)` — exchange the occupants. v1 requires identical repo scope on both features.
- `mcp__canopy__migrate_slots()` — one-shot migration from a pre-3.0 workspace (where worktrees were named after their feature). Idempotent. Run once per workspace if `BlockerError(code='pre_migration')` ever surfaces.

**Canonical is the only place to run code.** Slots are passive branch storage. Never `cd` into `.canopy/worktrees/worktree-N/` to launch the app, run tests, or open a dev server — switch the feature into canonical first (`mcp__canopy__switch(feature)`). If you need to *inspect* a warm slot's files without changing focus, that's fine (read-only Read / Grep is harmless), but anything that runs the project should happen against canonical.

## Errors are structured — read them

Canopy errors come back as:
```json
{
  "status": "blocked",
  "code": "drift_detected",
  "what": "branches don't match feature lane",
  "expected": {...},
  "actual": {...},
  "fix_actions": [
    {"action": "switch", "args": {"feature": "SIN-12-search"}, "safe": true, "preview": "..."}
  ]
}
```

The `fix_actions` array lists recommended recovery steps, ordered most-recommended first. Each entry has `safe: true|false`:
- `safe: true` → you can call this directly to recover.
- `safe: false` → surface to the user before invoking (it might lose work or affect remote state).

When you see a `BlockerError`, the first step is to read `fix_actions[0]` and decide whether to follow it.

## Recovery: when canopy itself looks broken

If a canopy call returns an unexpected error — `KeyError` from a state read, a "feature not found" for one you just created, a worktree path that should exist but doesn't — call `mcp__canopy__doctor` first. It reports 21 codes across 12 categories of state-file drift + install-staleness (including slot-state checks added in Wave 3.0: `slot_dir_orphan`, `slot_entry_orphan`, `slot_branch_mismatch`, `slot_detached_head`), each with `code`, `severity`, `expected`/`actual`, and an `auto_fixable` flag.

- `summary.errors == 0` → not a state problem; investigate the original error normally.
- Errors present, mostly `auto_fixable: true` → call `doctor(fix=True)`; report `fixed`/`skipped` to the user.
- `auto_fixable: false` (e.g., `features_unknown_repo`, `branches_missing`, `cli_stale`) → surface the issue's `fix_action` text. The human needs to decide.

The `mcp__canopy__version` tool returns `{cli_version, mcp_version, schema_version}` for the same handshake.

## Customizing canopy for this workspace

If the user wants canopy to behave differently here — *"use ruff for preflight"*, *"track CodeRabbit and Korbit as bots"*, *"the api repo runs `uv run pytest tests/fast` before commits"* — that's a **canopy.toml augment**. Suggest invoking the `augment-canopy` skill, which knows the schema and how to mutate the file safely. Install it with `canopy setup-agent --skill augment-canopy` if it isn't already.

## Cross-session memory (Historian)

Each feature has a persistent memory file at `<workspace>/.canopy/memory/<feature>.md` that survives session boundaries. When you call `mcp__canopy__switch(feature)`, the response includes a `memory: <markdown>` field — read it first before re-deriving anything.

Three sections in the memory: **Resolutions log** (per-comment outcomes — never compacted), **PR context** (one block per PR), and **Sessions** (newest first; older sessions get trimmed by `historian_compact`).

What to call when:

- `mcp__canopy__historian_decide(feature, decisions=[{title, rationale}, ...])` — after picking an approach, after a pivot, before pausing. Decisions are deduped per-session by title, so it's safe to call repeatedly.
- `mcp__canopy__historian_pause(feature, reason)` — when stopping work mid-flow. The next session reads it on switch.
- `mcp__canopy__historian_defer_comment(feature, comment_id, reason)` — when intentionally skipping a review comment for a stated reason.
- `mcp__canopy__feature_memory(feature)` — re-read the memory at any point in the same session.
- `mcp__canopy__historian_compact(feature, keep_sessions=5)` — manual trim when the file grows long. Resolutions + PR context are never compacted.

Auto-capture from canopy actions (no extra calls needed):

- `mcp__canopy__commit(address=...)` records the resolution into memory automatically (mirrors `bot_resolutions.json`).
- `mcp__canopy__github_get_pr_comments(alias)` records `comment_read` for each actionable thread + `classifier_resolved` for the temporal-classifier output, deduped per-session.

If you decided something but forgot to call `historian_decide`, end the turn with a `<historian-decisions>[{"title": "...", "rationale": "..."}, ...]</historian-decisions>` block. A future Stop hook (autopilot) will tail-parse it and persist (deduped against the explicit calls).

## Bot review comments

When `mcp__canopy__feature_state` returns state `awaiting_bot_resolution`, only bot nits (CodeRabbit, Korbit, Cubic, etc.) are blocking — humans haven't requested changes. The `summary` splits the actionable count into `actionable_bot_count` and `actionable_human_count` so you can tell which side needs attention.

- `mcp__canopy__bot_comments_status(feature)` returns the per-PR rollup: total / resolved / unresolved + per-thread metadata (id, author, file, body preview).
- `mcp__canopy__commit(message, address=<comment-id>)` (or `canopy commit --address <id>`) auto-suffixes the commit message with the bot comment's title + URL and persists the resolution to `.canopy/state/bot_resolutions.json`. Resolved comments drop out of `actionable_bot_count` on the next `feature_state` call.
- Address one comment per commit so the resolution log stays granular and the agent's next `bot-status` call has clean per-comment provenance.

## Anti-patterns

- ❌ `cd <repo> && git checkout <branch>` — use `mcp__canopy__switch(feature=...)` so all participating repos move together with verification (and the previously-canonical feature evacuates into a warm slot, preserving its work-in-progress).
- ❌ `cd .canopy/worktrees/worktree-N/<repo> && pnpm dev` (or `pytest`, or any command that runs the project) — worktrees are passive branch storage. Switch the feature into canonical (`mcp__canopy__switch(feature)`) and run there. Read-only inspection (Read / Grep against a warm slot) is fine; execution is not.
- ❌ Iterating `gh pr list --author @me` per repo and grouping yourself — `mcp__canopy__triage` already groups by feature lane and applies priority tiers.
- ❌ `cd <repo> && pnpm test` — use `mcp__canopy__run(repo='repo-b', command='pnpm test')`. The shell state from a previous tool call is not yours.
- ❌ Parsing `gh api .../pulls/{n}/comments` and writing your own "is this resolved" logic — `mcp__canopy__github_get_pr_comments` returns `actionable_threads` vs `likely_resolved_threads` already.
- ❌ Calling `git status` in each repo and synthesizing what's dirty/clean — `mcp__canopy__feature_state(feature)` returns this aggregated, plus computed state and next_actions.
- ❌ Running `git stash push` when there's a feature context — use `mcp__canopy__stash_save_feature(feature, message)` so stashes get tagged and groupable.
- ❌ `mcp__canopy__run(repo='...', command='git commit ...')` to commit one repo at a time — use `mcp__canopy__commit(message=...)` so the whole canonical feature commits with one message and the wrong-branch / hooks-failed cases come back classified.
- ❌ `mcp__canopy__run(repo='...', command='git push')` per repo — use `mcp__canopy__push()`. First push needs `set_upstream=True`; the `no_upstream` blocker tells you when (and the fix-action carries the same args + `set_upstream=True` so you can retry mechanically).

## When canopy doesn't apply

Use raw `Bash`, `Read`, `Edit` etc. as normal for:
- Reading and editing source files (canopy doesn't wrap these)
- Workspace not under canopy management (no `canopy.toml`)
- Operations on repos not registered in `canopy.toml`
- One-off utilities that don't need path resolution (ls, find, etc., outside any canopy repo)
