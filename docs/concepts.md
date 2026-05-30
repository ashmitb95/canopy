# Concepts

Four ideas hold canopy together. Other docs assume them.

## 1. The action framework

Canopy is organized around **actions**. An action is a recipe with three parts:

```
preconditions  →  steps  →  completion criteria
   (block?)         (do)        (verify, don't assume)
```

If preconditions fail, the action **refuses to run** and returns a structured `BlockerError` describing what's wrong AND how to fix it. If steps complete, the action **verifies** the new state matches the criteria — it doesn't assume "no exception" means "done".

Two flavors:

- **Procedural actions** — canopy runs the recipe deterministically, no LLM in the loop. Examples: `realign`, `preflight`, `triage`, `drift`. These are the everyday tools.
- **Agentic actions** — canopy bootstraps an LLM with a prompt + tool allowlist, then verifies completion. Example: `address_review_comments` (planned). These are the higher-order workflows.

### Structured errors

Every error from an action carries enough machine-readable context that the consumer (a human reading CLI output, or an agent reading MCP JSON) can act on it without parsing prose:

```json
{
  "status": "blocked",
  "code": "drift_detected",
  "what": "branches don't match feature lane 'SIN-12-search'",
  "expected": {"branches": {"backend": "SIN-12-search", "frontend": "SIN-12-search"}},
  "actual":   {"branches": {"backend": "SIN-12-search", "frontend": "main"}},
  "fix_actions": [
    {"action": "switch", "args": {"feature": "SIN-12-search"},
     "safe": true, "preview": "promote SIN-12-search to canonical in all repos"}
  ]
}
```

The CLI renders this as colored multi-line output; MCP returns the JSON directly. Same shape, two consumers. The `fix_actions[0]` with `safe: true` is what an agent should auto-run; `safe: false` requires human confirmation.

## 2. The agent context contract

Every canopy tool that touches multi-repo state takes **semantic context** — `feature`, `repo`, alias — and resolves paths internally. The agent never specifies a path.

This is correctness by construction. The single biggest agent failure mode in multi-repo work is `cd /wrong/repo && command`. Canopy eliminates it because the agent has no surface area to type the path. `mcp__canopy__run(repo='ui', command='pnpm test')` resolves the cwd and reports it back; you can't get `cwd` wrong if you don't pass `cwd`.

Three concrete rules:

1. **Inputs are semantic, not paths.** `feature: str`, `repo: str`, alias strings — never `cwd`, never absolute paths.
2. **PR is first-class context.** Any tool that returns feature/repo state also returns PR state for that branch (number, URL, review decision). Branches and PRs travel together.
3. **Verification is per-repo, structured.** Multi-repo write ops report `{repo: {status, before, after, reason?}}` so the agent never has to re-query to confirm.

### Universal aliases

Every read tool accepts the same alias forms. Learn one rule, use everywhere:

| Form | Example | Notes |
|---|---|---|
| Feature name | `SIN-12-search` | Matches `features.json` entry |
| Linear issue ID | `SIN-12` | Matches lane's `linear_issue` field |
| Specific PR | `<repo>#<n>` like `backend#142` | Bypasses feature lookup |
| PR URL | `https://github.com/owner/repo/pull/142` | Parsed |
| Specific branch | `<repo>:<branch>` | For `branch info` |

For features whose branch differs across repos (e.g., `SIN-13-fixes` in backend, `SIN-13-fixes-v2` in frontend — common when one side rebases or renames mid-flight), the lane's `branches` map handles it transparently. You pass the canonical feature alias; canopy resolves per-repo branches.

## 3. The 9-state machine

`canopy state <feature>` (and the MCP tool `feature_state(feature)`) returns one of 9 states + an ordered `next_actions` array. Same data the [VSCode extension](https://marketplace.visualstudio.com/items?itemName=SingularityInc.canopy) dashboard renders.

| State | Detection | Primary `next_actions` |
|---|---|---|
| **`drifted`** | live `current_branch` ≠ expected for any repo in the lane | `switch(feature)` (canonical-slot model — handles both worktree and main-tree cases) |
| **`needs_work`** | clean + (CHANGES_REQUESTED or actionable human comments) | `address_review_comments(feature)` |
| **`in_progress`** | aligned + dirty + no fresh preflight | `preflight(feature)` |
| **`ready_to_commit`** | aligned + dirty + preflight passed for current HEAD | `commit(feature)` |
| **`ready_to_push`** | aligned + clean + ahead of remote | `push(feature)` |
| **`awaiting_bot_resolution`** (M3) | clean + PR open + no human signal + ≥1 unresolved bot comment | `address_bot_comments(feature)` → `commit --address <id>` |
| **`awaiting_review`** | aligned + clean + PRs open + no actionable threads | refresh / wait |
| **`approved`** | all PRs APPROVED | `merge` (+ secondary `address_bot_comments` if bot threads remain) |
| **`no_prs`** | aligned + clean + no PRs anywhere | `pr_create(feature)` |

**Bot vs human comment classification** (M3): a comment counts as a bot when GitHub reports `author_type == "Bot"`. With `[augments] review_bots = ["coderabbit", ...]` set in canopy.toml, the author also has to substring-match the configured list — so an unconfigured bot account drops out of bot tracking and stays in the human bucket. Resolved bot comments (those addressed via `canopy commit --address <id>`) are subtracted from `actionable_bot_count`. Bot nits never gate `approved`; human approval is the merge gate.

Detection uses **live git state** (not the cached `.canopy/state/heads.json`) for correctness — even if the post-checkout hook hasn't fired, `feature_state` is right. The hook + `heads.json` exist to power `canopy drift`'s fast path.

`next_actions[0]` is the suggested primary CTA. The agent should read this and call it (or surface it to the human) instead of re-deriving the rules. Same data the dashboard renders as the primary button.

### State transitions

```
                       ┌────────── drift detected ─────────┐
                       ▼                                   │
                   drifted ──── realign ──┐                │
                                          ▼                │
        ┌─── make changes ────────► in_progress            │
        │                                │                 │
        │                                preflight pass    │
        │                                │                 │
        │                                ▼                 │
        │                          ready_to_commit         │
        │                                │                 │
        │                                commit            │
        │                                │                 │
        │                                ▼                 │
        │                          ready_to_push           │
        │                                │                 │
        │                                push              │
        │                                │                 │
        │                                ▼                 │
        │                          awaiting_bot_resolution ── (only bot nits
        │                                │                     unresolved)
        │                                ▼                 │
        │                          awaiting_review ───── (manual git checkout
        │                                │                 elsewhere = drift)
        │                  reviewer comments               │
        │                                │                 │
        ▼                                ▼                 │
   needs_work ◄───────── feedback ──── any state ──────────┘
        │
        address_review_comments
        │
        └────────────────► (back to in_progress)
```

The dashboard's CTA is whichever node you're sitting on. Drift always wins — it supersedes all other states because operating on misaligned state corrupts subsequent work.

For **worktree-backed** features, the drift detection runs against the worktree path (not main), so a worktree-backed feature is only `drifted` if someone manually `git checkout`'d to a different branch *inside the worktree*. The fix is `switch` (re-establishes the feature context), not `realign` (which would touch main and undo the protection worktrees were supposed to provide).

### Cross-session memory (M4)

`canopy switch` returns a `memory: <markdown>` field rendered from `<workspace>/.canopy/memory/<feature>.md` — a per-feature persistent log of decisions, comment activity, PR context, and session entries. Agents read it on switch instead of re-deriving "where was I, what's resolved, what's blocked." The memory is append-only (concurrent agents on the same feature flock-serialize), with three top-level sections:

- **Resolutions log** — per-comment outcomes (✓ resolved, ⊙ likely-resolved by classifier, ⊘ deferred). Never compacted.
- **PR context** — one block per PR with rationale + chronological updates. Never compacted.
- **Sessions** — newest-first per-session entries (decisions, pauses, events). Trimmed by `historian_compact`.

Auto-capture wires existing canopy actions: `commit --address` mirrors the bot resolution into memory; `github_get_pr_comments` records each actionable thread + the temporal classifier's likely-resolved batch (deduped per session). Explicit `historian_decide` / `historian_pause` cover the agent's narrative side. See [docs/plans/historian.md](plans/historian.md) for the full design.

## 4. The slot model

Every feature in canopy lives in exactly one of three states:

- **canonical** — checked out in the main repo. There's exactly one canonical feature at a time, across all repos. This is what your IDE, git GUI, default `git status`, blame, and log all naturally reflect. **Canonical is the only place to run code.** Worktrees are passive branch storage — never `cd` into them to launch the app or run tests.
- **warm** — occupies a numbered **slot** at `.canopy/worktrees/worktree-N/<repo>/`. Slot identity (`worktree-1`, `worktree-2`, ...) is stable across feature swaps; feature occupancy is transient. A slot holds one feature at a time; that feature's repos sit as siblings inside the slot. Capped by `[workspace] slots = N` in canopy.toml (default **2** — so you keep at most 1 canonical + 2 warm = 3 simultaneous live trees).
- **cold** — branch exists, no slot, no checkout. Cheap, unlimited. Plus any feature-tagged stash that was preserved when it was last unloaded.

`canopy switch <Y>` is the single primitive that moves features between these states. Two modes:

- **Active rotation (default)** — when Y becomes canonical, the previous canonical X **evacuates into a warm slot** (with full stash → checkout → pop). Use when X still needs your attention soon — instant to switch back. When Y is *already warm*, the swap is a fast 5-op-per-repo dance: no `mv`, no `git worktree repair`, no slot renaming. The slot ids stay put; only the features inside them swap.
- **Wind-down (`--release-current`)** — when Y becomes canonical, X goes **straight to cold** (with feature-tagged stash for any dirty work). Use when X is parked/finished.

```
        switch(Y, default)              switch(Y, --release-current)
   ┌──────────────────────────┐      ┌──────────────────────────┐
   │  before                   │      │  before                   │
   │    canonical: X           │      │    canonical: X           │
   │    worktree-1: A          │      │    worktree-1: A          │
   │    worktree-2: B          │      │    worktree-2: B          │
   │                           │      │                           │
   │  after                    │      │  after                    │
   │    canonical: Y           │      │    canonical: Y           │
   │    worktree-1: A          │      │    worktree-1: A          │
   │    worktree-2: B          │      │    worktree-2: B          │
   │    (X needs a slot —      │      │    cold: X (+ stash)      │
   │     cap=2 hit!)           │      │                           │
   │                           │      │  no eviction needed       │
   │  if cap=2 hit:            │      │                           │
   │    BlockerError —         │      │                           │
   │    pick wind-down or      │      │                           │
   │    evict a specific slot  │      │                           │
   └──────────────────────────┘      └──────────────────────────┘
```

When the cap is hit in active-rotation mode, canopy **does not silently evict**. It returns a `BlockerError(code='worktree_cap_reached')` with explicit `fix_actions`: wind-down the current focus instead, evict a specific slot to cold (with auto-stash), or raise the cap. The user (or agent on their behalf) picks intent — never a silent surprise.

### Slot vocabulary

Four verbs total, all with CLI + MCP parity:

| Verb | What it does |
|---|---|
| `switch <Y>` | Promote Y to canonical. Slot rotation handled automatically. `--evict-to <slot-N>` pins where the outgoing canonical goes; `--to-slot <slot-N>` promotes whatever feature already occupies that slot. |
| `slot load <Y> [<slot-N>]` | Warm a cold Y into a slot **without** touching canonical. Used for pre-warming or inspecting a feature before switching to it. |
| `slot clear <slot-N>` | Evict that slot's occupant to cold (with feature-tagged stash if dirty). The slot itself remains; it's just empty. |
| `slot swap <slot-A> <slot-B>` | Exchange the occupants of two warm slots. v1 requires identical repo scope on both features. |

`worktree-N` is also a universal alias form — any tool that takes a feature alias also accepts a slot id (`feature_state worktree-2`, `pr worktree-1`, etc.) and resolves to the slot's current occupant.

### Why this model

It matches a mental model where there's one feature **in focus** — open in the IDE, live at localhost, the thing your git GUI is staring at — while others are being worked on concurrently. `switch` makes managing that focus easier: one verb to promote whichever feature deserves the canonical slot right now, with the previously-focused one either parked in a warm slot (still close at hand) or wound down cold (preserved but out of the way) depending on how active it still is.

Decoupling slot identity from feature identity matters because:
- The dashboard can render slots in stable order even as occupants change.
- A "swap" is just a JSON edit + per-repo checkouts; no directory rename.
- `worktree-N` is a stable shell PATH if you really do need to peek at a warm tree (read-only — don't run code there).
- Migration from pre-3.0 layouts is a one-shot, idempotent operation (`canopy migrate-slots`).

### What `switch` is *not*

- **Not branch-management.** `switch` doesn't create branches that don't exist (that's `feature_create`), doesn't open IDEs (that's `code`), doesn't commit/push (those are `commit`/`push`/`ship`). It only moves features between {canonical, warm, cold}.
- **Not slot-allocation either.** Use `slot load` to warm a cold feature into a slot without changing canonical. Use `slot clear` to free a slot without bringing a new feature in. `switch` is specifically the "what's in focus" verb.
- **Not unsafe.** Three layers of defense: a preflight catches predictable failures cheaply; a fast-path 5-op-per-repo swap when Y is already warm; a journaled rollback walker plus a `slots.json.in_flight` marker for the residual real-world failures (disk full, network blip, partial multi-repo failure). Either every repo finishes the switch or every repo rolls back to its pre-switch state.

## 5. Returning to a feature — the resume brief

When the agent (or human) returns to a feature in a new session, `canopy resume <alias>` (or `mcp__canopy__feature_resume(alias)`) runs the full recovery chain:

```
alias → switch-if-needed → refresh GitHub + Linear → brief → bump last-visit anchor
```

One call gets you oriented. There's no separate "switch, then fetch PR state, then read comments" dance.

### What the brief carries

```json
{
  "feature": "SIN-12-search",
  "switch_performed": true,
  "first_visit": false,
  "window_hours": 18.4,
  "since_last_visit": {
    "new_commits": 3,
    "new_threads": 1,
    "resolved_threads": 2,
    "draft_replies_available": 1
  },
  "current_state": "needs_work",
  "next_actions": ["address_review_comments"],
  "intent_hints": ["review_comments", "check_ci"]
}
```

- `switch_performed` — whether `resume` had to call `switch` to move the feature to canonical.
- `first_visit` — true when no prior anchor exists; no delta computed.
- `window_hours` — wall-clock hours since the last visit anchor was set.
- `since_last_visit` — counts-only delta (commits, threads, GH thread closures, draft-reply availability) since the last visit. Does NOT re-read every comment body — just counts, so it fits in a summary line.
- `current_state` + `next_actions` — forwarded from `feature_state`, so the agent knows what to do next without an extra round-trip.
- `intent_hints` — canopy's best guess at the most likely next action categories (e.g., `review_comments`, `check_ci`, `push`). Use as a prompt, not a constraint.

### Freshness policy

- **Every `resume` call refreshes GitHub + Linear.** The brief is never cached at the canopy layer; upstream HTTP/MCP layers may cache.
- **Auxiliary state** (`bot_resolutions`, `thread_resolutions`, `visits.json`) is read live on every call.
- **`switch` also bumps `last_visit`.** When you call `switch` without `resume` — e.g., a quick focus change mid-session — the switch return includes a lightweight `since_last_visit_summary` (counts only, no intent hints) so you immediately see whether anything changed since you were last here. `degraded: true` appears in this field when GitHub is unreachable.

### Last-visit anchor — the single-bump invariant

`visits.json` stores `{feature: {last_visit: <ISO>, previous_visit: <ISO|null>}}`. The anchor advances exactly once per `resume` call, at the END of the call (after the brief is computed). It does NOT advance on `switch` alone, nor on repeated `resume` calls in the same logical session (within ~5 minutes of the same anchor time).

This invariant means:
- The delta window always reflects the period since you last *consciously* resumed the feature, not since the last focus change.
- Repeated `resume` calls in quick succession return the same delta (not a 0-minute window the second time).
- `--reset-anchor` (CLI) / `reset_anchor=True` (MCP) explicitly resets the anchor to now — use when you want to start fresh without reopening a new session.
