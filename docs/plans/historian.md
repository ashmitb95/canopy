# Historian — cross-session feature memory

## Why

Agents waste 30–50% of their context on bookkeeping every session: re-parsing PR state, re-deriving "is this comment still actionable?", re-discovering past decisions. When an agent picks up a feature it (or another agent) was working on Monday, by Wednesday it has zero context — the user has to re-explain "we were halfway through wiring up empty-state, blocked on design-system copy."

Historian moves that knowledge into a persistent markdown memory file per feature, written automatically as the agent works, read automatically on `canopy switch`. The handoff scenario:

- Monday: 2 hours on `sin-7-empty-state`. Agent reads design docs, edits 3 files, runs preflight, blocked on copy from design system, pauses.
- Tuesday: switch to `sin-6-cache-stats`, work there.
- Wednesday: `canopy switch sin-7-empty-state` — agent's response includes the memory file; agent knows immediately what was decided, what's resolved, where it left off. No re-derivation.

This eliminates an entire class of context-loss tax that's invisible to users because they've adapted to it.

## Goal

A persistent markdown file per feature (`<workspace>/.canopy/memory/<feature>.md`) that:

- Captures decisions, events, comment activity, and PR context across sessions
- Is auto-read on `canopy switch` (response includes a `memory: <markdown>` field)
- Is auto-written via PostToolUse hooks (events, comment activity, PR context) and explicit MCP calls (decisions, pauses)
- Renders in three sections: Resolutions log (structured, never compacted), PR context, Sessions (newest first, older sessions LLM-compacted)

## Non-goals

- LLM-based summarization on every event (too slow, too costly). Compaction is the only LLM call, and only on switch-away.
- Cross-machine memory sync. Memory is local to the workspace's `.canopy/memory/` and follows the workspace.
- Replacing PR descriptions or commit messages. Historian is for *in-session work* — commits and PRs remain separate.
- Conflict-free distributed memory (CRDT). Just append-only with file locks; rare conflicts get resolved by manual edit.
- Per-machine memory (memory is per-workspace, not per-machine).

## Eight capture categories

| # | Category | Examples | Trigger |
|---|---|---|---|
| 1 | Decisions | "chose `jwt.decode` over `pyjwt`; reason: stdlib only" | **Hybrid** (see Capture mechanism below): primary `mcp__canopy__historian_decide` + Stop-hook tail-parse backup |
| 2 | Events | "edited `src/auth/oauth.py`", "ran preflight (passed)" | PostToolUse hook on Bash + Edit (in active worktree only); summarized to one line |
| 3 | Pauses | "blocked on design-system copy; need confirmation from Phil" | Stop hook (end of agent session) or explicit `historian_pause` |
| 4 | Comments read | "read coderabbit comment on `src/api/cache.py:42` — suggested rename `hit_rate → cache_hit_rate`" | PostToolUse on `review_comments` MCP call; logs each unique comment URL once per session |
| 5 | Comments resolved | "addressed comment 123456 in `abc123de`: renamed `hit_rate → cache_hit_rate` per suggestion" | PostToolUse on `commit --address` (consumes N2's bot-resolutions flow); pulls comment title + commit sha + diff snippet |
| 6 | Classifier-resolved | "temporal classifier marked these 3 threads likely-resolved (file already touched in commits since)" | PostToolUse on `review_comments` when classifier output includes `likely_resolved` entries; logged once per session |
| 7 | PR context | "opened PR #142 against main. Includes commits abc/def/ghi. Rationale: implements SIN-7 cache stats; closes 3 actionable threads from review round 1" | PostToolUse on `ship` MCP tool (Wave 2.4) or explicit `historian_pr_opened` |
| 8 | PR updates | "pushed 2 commits to PR #142: addressed bot comment 789, added test for the cache-hit-rate edge case" | PostToolUse on `push` MCP tool (when an open PR exists for the feature) |

Categories 4–8 are the agent-handoff layer — the new agent reads the memory and can answer "is comment X resolved?", "what's the rationale for this PR?", and "what was the last action?" without scrolling through `gh pr view` or re-deriving state.

## Capture mechanism for decisions (hybrid)

Explicit MCP tool calls (primary) + Stop-hook tail-parse (backup).

- **Primary: explicit tool calls.** Skill teaches the agent to call `mcp__canopy__historian_decide(feature, decisions=[...])` after committing to an approach (after a commit, after a pivot, on pause). Reliable; structured input validated by the MCP protocol.
- **Backup: Stop-hook tail-parse.** Skill teaches: at end of turn where you decided something but didn't call the tool, emit `<historian-decisions>[{title, rationale}, ...]</historian-decisions>` in the response. Stop hook scans the last assistant message; parses; writes any decisions not already captured (deduped by title).
- **Rejected: extra-prompt round-trip.** A hook that fires after commit and asks the agent "any decisions worth recording?" wastes an LLM turn given the tool-call primitive exists.

The hybrid handles two failure modes: (a) agent forgets to call the tool but mentions the decision in their response (tail-parse rescue), (b) agent does both (deduped by title). Format-only would have ~5–10% silent gaps in long sessions; tool-only would miss free-text decisions that didn't trigger an explicit call. The hybrid pushes silent-gap rate to near zero.

## File format (`.canopy/memory/<feature>.md`)

Three top-level sections, newest content first within each:

```markdown
# Feature: <name> · <linear-id>

## Resolutions log
- ✓ comment <id> (<author>, <file:line>) resolved by <sha>
  <gist of resolution>
- ⊙ comment <id> (<author>, <file:line>) likely-resolved by classifier
  <classifier rationale>
- ⚠ comment <id> (<author>, <file:line>) UNRESOLVED
  <last status>
- ⊘ comment <id> (<author>, <file:line>) DEFERRED
  <deferral reason>

## PR context
### PR #<n> — <title>
**Opened:** <date> against <base>
**Branch:** <feature>
**Rationale:** <why this PR>
**Commits:** <count>; review rounds: <n>

### Updates
- <date>: <action>
  ...

## Sessions (newest first)
### <date> — <status>
**Where we are:** ...
**Last decision:** ...
**Open questions:** ...
**Last command:** ...
**Touched:** ...
```

The Resolutions log + PR context sections are **never compacted** — they're the always-current source of truth. Sessions get LLM-compacted on switch-away.

## Switch integration

`mcp__canopy__switch(feature)` response includes a `memory: <markdown>` field for the new active feature. Agent sees memory immediately on switch — no extra MCP call.

```python
# After switch_impl():
result["memory"] = format_for_agent(workspace, feature)  # renders the .md
```

## Compaction

Old sessions get LLM-summarized when:
- (a) `canopy switch <other>` — compact the just-finished session of the previously-active feature
- (b) Explicit `mcp__canopy__historian_compact(feature)`

Resolution log + PR context sections are NEVER compacted. Only the Sessions section.

The compaction LLM call is the only LLM call in the historian flow. Everything else is mechanical.

## New CLI / MCP surface

- `mcp__canopy__historian_decide(feature, decisions: list[{title, rationale}])` — log decisions
- `mcp__canopy__historian_pause(feature, reason: str)` — log pause
- `mcp__canopy__historian_defer_comment(feature, comment_id: str, reason: str)` — log deferral with rationale
- `mcp__canopy__feature_memory(feature)` — read full memory as markdown
- `mcp__canopy__historian_compact(feature)` — manual compaction trigger
- `canopy historian show <feature>` — CLI inspection (read-only)
- `canopy historian compact <feature>` — CLI manual compact

## Files to touch

- **New:** `src/canopy/actions/historian.py` — `record_decision`, `record_event`, `record_pause`, `record_comment_read`, `record_comment_resolved`, `record_comment_deferred`, `record_pr_context`, `record_pr_update`, `compact`, `read`, `format_for_agent`
- **New:** `tests/test_historian.py`
- `src/canopy/mcp/server.py` — register the 5 historian tools (`historian_decide`, `historian_pause`, `historian_defer_comment`, `feature_memory`, `historian_compact`)
- `src/canopy/cli/main.py` — `cmd_historian_show`, `cmd_historian_compact` (read-only inspection + manual compact trigger)
- `src/canopy/actions/switch.py` — extend response with `memory: <markdown>` field via `format_for_agent(feature)` call
- `src/canopy/actions/commit.py` — when `--address` succeeds, also call `record_comment_resolved` (extends N2's flow)
- `src/canopy/actions/reads.py` — when `review_comments` returns, call `record_comment_read` and `record_classifier_resolved`
- `src/canopy/agent_setup/skills/using-canopy/SKILL.md` — teach: read memory on switch; call `historian_decide` at meaningful moments; emit `<historian-decisions>` tail as fallback
- Stop hook (autopilot integration): scan last assistant message for `<historian-decisions>` block; parse; dedup against tool-call writes; persist
- PostToolUse hooks (autopilot integration): events for Bash/Edit, comment-read for `review_comments`, comment-resolved for `commit --address`, pr-context for `ship`, pr-update for `push`

## Implementation order

1. New `actions/historian.py`. File IO + record functions for each category. Pure module; unit-tested independently.
2. MCP tool registration. The 5 new tools wrap the record functions.
3. Skill update: `using-canopy/SKILL.md` gains a "Historian" section teaching when to call each tool, plus the tail-fallback format.
4. Switch integration: extend `switch_impl` response with `memory: format_for_agent(feature)`.
5. Hooks integration: PostToolUse + Stop hook bundle (lands as part of autopilot's observer category).
6. Commit + review integration: extend N2's `commit --address` flow to call `record_comment_resolved`; extend `review_comments` reads to call `record_comment_read` and `record_classifier_resolved`.
7. Compaction: LLM-summarize old sessions; trigger on switch-away.

## Verification

- Unit: each `record_*` appends correctly; `format_for_agent` renders all 3 sections in order; compaction summarizes without losing resolution log or PR context.
- Integration: `workspace_with_feature` → simulate session: `review_comments` call → `commit --address` → `historian_decide` → switch away → switch back → assert memory has resolution-log entry + classifier-resolved entry + decision entry + session entry.
- Hybrid mechanism: agent calls `historian_decide` directly: persisted once. Agent emits format-tail without tool call: Stop-hook persists. Agent does both with same title: deduped to one entry.
- Manual: real PR with bot comments → use canopy normally for an hour → `canopy historian show <feature>` → eyeball that memory captures decisions, events, resolutions, classifier output, PR context.

## Edge cases

- **Privacy / secrets in tool output.** Bash output can contain API keys, paths, tokens. Hook-based event capture redacts aggressively: defaults to NOT logging tool output (just tool name + 1-line summary). User opts into verbose logging per category.
- **Multi-agent contention on same feature.** Two agents writing to `.canopy/memory/<feature>.md` simultaneously — solved with append-only writes + `fcntl.flock` (same pattern as `heads.json`). Each event is its own line; agents don't overwrite each other.
- **Stale context after long absence.** If the codebase has changed since the last session, old memory might mislead. Mitigation: compaction includes a "since last session" diff summary so the agent knows what's changed independently of what was logged.
- **Cross-feature crosstalk.** Memory must be strictly scoped to the feature. If the agent is in `sin-7` and asks about `sin-6`, they shouldn't accidentally get sin-6's memory. Strict per-feature scoping.
- **PostToolUse hook noise.** PostToolUse on every Bash + Edit is noisy. Filter: only fire on `Bash(git ...)` and `Edit(...)` of files in the *active* feature's worktree. Anything else passes through unlogged.
- **Comment marked likely_resolved → re-opened.** A comment marked "likely_resolved" in session 1 might be re-opened in session 3 (reviewer adds a follow-up). Historian re-renders the temporal classifier's current output; doesn't manually clean up. The classifier handles the transition.

## Effort

~5–6 days. Depends on autopilot's Stop + PostToolUse hook infrastructure being in place; if those slip, historian's auto-capture (categories 2, 4, 5, 6, 7, 8) defers and only categories 1 (decisions, hybrid) and 3 (pauses, explicit) ship in v1.

## Dependencies

- **N2 (bot-tracking):** historian's "comments resolved" log consumes N2's `bot_resolutions.json` + `commit --address` flow as data sources. Without N2, historian would have to reimplement structured comment-resolution state.
- **Augments (N3):** the `review_bots` augment list scopes which authors count as bots for the comments-read / comments-resolved categories. Without it, historian falls back to the hardcoded `author_type == "Bot"` substring.
- **Autopilot observer hooks:** historian's auto-capture for events / comment-activity / PR-context relies on the PostToolUse + Stop hook bundle.

## After this lands

- An agent picking up `sin-7` after a 3-day gap reads the memory on switch and knows immediately: what was decided, which comments are resolved, which are deferred, what's still open. No re-derivation.
- The README's "Why it's load-bearing" table picks up another row: *"Cross-session context loss: agent re-derives PR state, past decisions, file context every session."* → historian is the persistent memory layer that makes session boundaries seamless.
- Pairs with future agent-driven workflows (multi-step refactors, long-running PR review loops): historian carries the narrative; structured state files (`bot_resolutions.json`, `heads.json`, etc.) carry the lookup.
- Auto-population of agent context becomes a pattern other plans can adopt: when a new feature requires persistent narrative, follow historian's shape.
