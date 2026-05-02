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

## 4. The canonical-slot model

Every feature in canopy lives in exactly one of three states:

- **canonical** — checked out in the main repo. There's exactly one canonical feature at a time, across all repos. This is what your IDE, git GUI, default `git status`, blame, and log all naturally reflect.
- **warm** — has a worktree directory at `.canopy/worktrees/<feature>/<repo>/`. Live working tree, instant to switch into. Capped by `max_worktrees` config (default **2** — so you keep at most 1 canonical + 2 warm = 3 simultaneous live trees).
- **cold** — branch exists, no worktree, no checkout. Cheap, unlimited. Plus any feature-tagged stash that was preserved when it was last unloaded.

`canopy switch <Y>` is the single primitive that moves features between these states. Two modes:

- **Active rotation (default)** — when Y becomes canonical, the previous canonical X **evacuates to a warm worktree** (with full stash → checkout → pop). Use when X still needs your attention soon — instant to switch back.
- **Wind-down (`--release-current`)** — when Y becomes canonical, X goes **straight to cold** (with feature-tagged stash for any dirty work). Use when X is parked/finished.

```
        switch(Y, default)              switch(Y, --release-current)
   ┌──────────────────────────┐      ┌──────────────────────────┐
   │  before                   │      │  before                   │
   │    main: X                │      │    main: X                │
   │    warm: A, B             │      │    warm: A, B             │
   │                           │      │                           │
   │  after                    │      │  after                    │
   │    main: Y                │      │    main: Y                │
   │    warm: A, B, X (cap=2!) │      │    warm: A, B             │
   │                           │      │    cold: X (+ stash)      │
   │  if cap=2 hit:            │      │                           │
   │    BlockerError —         │      │  no eviction needed       │
   │    pick wind-down or      │      │                           │
   │    evict an existing warm │      │                           │
   └──────────────────────────┘      └──────────────────────────┘
```

When the cap is hit in active-rotation mode, canopy **does not silently evict**. It returns a `BlockerError(code='worktree_cap_reached')` with explicit `fix_actions`: wind-down the current focus instead, evict a specific LRU warm to cold (with auto-stash), or raise the cap. The user (or agent on their behalf) picks intent — never a silent surprise.

### Why this model

It matches a mental model where there's one feature **in focus** — open in the IDE, live at localhost, the thing your git GUI is staring at — while others are being worked on concurrently. `switch` makes managing that focus easier: one verb to promote whichever feature deserves the canonical slot right now, with the previously-focused one either parked warm (still close at hand) or wound down cold (preserved but out of the way) depending on how active it still is.

### What `switch` is *not*

- **Not `realign`.** `realign` is an internal helper (it just runs `git checkout` per repo). The agent-facing surface is `switch`. `realign` exists for backward-compat in 2.9; expect it to be removed from CLI/MCP in a later wave.
- **Not branch-management.** `switch` doesn't create branches that don't exist (that's `feature_create`), doesn't open IDEs (that's `code`), doesn't commit/push (those are `commit`/`push`/`ship`). It only moves features between {canonical, warm, cold}.
- **Not unsafe.** Three layers of defense: a preflight catches predictable failures cheaply; a fast-path 3-checkout swap when both X and Y already have homes; a journaled rollback walker for the residual real-world failures (disk full, network blip). Either every repo finishes the switch or every repo rolls back to its pre-switch state.
