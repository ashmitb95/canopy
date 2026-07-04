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

- **canonical (trunk)** — checked out in the main repo. There's exactly one canonical feature at a time, across all repos. This is what your IDE, git GUI, default `git status`, blame, and log all naturally reflect. **Canonical is the only place to run code full-stack** — boot the app, hit real ports, integration-test.
- **warm** — occupies a numbered **slot** at `.canopy/worktrees/worktree-N/<repo>/`. Slot identity (`worktree-1`, `worktree-2`, ...) is stable across feature swaps; feature occupancy is transient. A slot holds one feature at a time; that feature's repos sit as siblings inside the slot. Capped by `[workspace] slots = N` in canopy.toml (default **2** — so you keep at most 1 canonical + 2 warm = 3 simultaneous live trees). **Warm slots are workable, not just parked** (4.0 phase 4): they're auto-bootstrapped on creation, so you can edit / commit / push / lint / unit-test right there without switching. What you can't do in a warm slot is run the project full-stack — that still needs trunk.
- **cold** — branch exists, no slot, no checkout. Cheap, unlimited. Plus any feature-tagged stash that was preserved when it was last unloaded.

### Intent-gated switch: worktree vs trunk (4.0 phase 4)

**Intent decides whether you switch — not the act of returning to a feature.** The two-tier model is: trunk is the RUN target, worktrees are the WORK target for review.

- **"Address the review comments on DOC-Y"** → edit / commit / push **in DOC-Y's warm worktree**. No switch. `canopy context` gives you the path; the enforcement gate allows commits/pushes there. You never leave whatever's currently running in trunk.
- **"Run DOC-Y full-stack / verify it in the app"** → `canopy switch DOC-Y` promotes it into trunk — the only place with ports, services, the full env.

Routing is implicit and one-directional: canopy publishes the map (`context` gives feature ↔ repo ↔ path ↔ slot state), the enforcement gate keeps work honest wherever you are, and `run --feature X` resolves to X's current location (its warm worktree, or trunk if it's canonical) — there's no separate `work` verb to invoke. `switch` is the one control verb, and it means specifically "move X into trunk so it can run." This evolves, not breaks, the older "canonical is the only run target" rule — trunk is still the only run target; worktrees are now the work target for review instead of being purely passive storage.

`canopy switch <Y>` is the primitive that moves features between {canonical, warm, cold}. What happens to the outgoing canonical feature X is no longer a mode you choose up front — it's a rule:

### Warm-vs-cold rule (default, 4.0 phase 4)

When X vacates trunk (because Y is switching in to run), X goes:

- **warm** iff it has an **open PR** or **live/uncommitted WIP** — it's either being shepherded through review or mid-flight enough that you'll want it back instantly.
- **cold** (with a feature-tagged stash for any dirty work) otherwise.

`--release-current` forces cold regardless (explicit wind-down, for when you know X is parked/finished even if the rule above would keep it warm). `--evict <f>` / `--evict-to <slot-N>` remain as explicit overrides on which feature or slot is affected. When Y is *already warm*, the swap is a fast 5-op-per-repo dance: no `mv`, no `git worktree repair`, no slot renaming — the slot ids stay put, only the features inside them swap.

```
        switch(Y, default rule)                switch(Y, --release-current)
   ┌──────────────────────────────┐      ┌──────────────────────────┐
   │  before                       │      │  before                   │
   │    canonical: X               │      │    canonical: X           │
   │    worktree-1: A              │      │    worktree-1: A          │
   │    worktree-2: B              │      │    worktree-2: B          │
   │                               │      │                           │
   │  after (X has open PR/WIP)    │      │  after                    │
   │    canonical: Y               │      │    canonical: Y           │
   │    worktree-1: A              │      │    worktree-1: A          │
   │    worktree-2: B              │      │    worktree-2: B          │
   │    (X needs a slot —          │      │    cold: X (+ stash)      │
   │     cap=2 hit!)               │      │                           │
   │                               │      │  no eviction needed       │
   │  after (X has no PR/WIP)      │      │                           │
   │    cold: X (+ stash)          │      │                           │
   │    no cap pressure            │      │                           │
   └──────────────────────────────┘      └──────────────────────────┘
```

When the warm-vs-cold rule wants X warm but the cap is already full, canopy **does not silently evict**. It returns `BlockerError(code='worktree_cap_reached')` with three explicit `fix_actions`, surfaced to the agent as a question:

1. **Raise the cap** (`slots = N+1`, persisted to canopy.toml) — keep everything warm.
2. **Send X cold this time** (`--release-current`) — cold + stash, re-warms later if a slot frees.
3. **Evict a specific warm PR** (`--evict <f>`) — canopy suggests the LRU candidate; the user picks which to park.

The user (or agent on their behalf) picks intent — never a silent surprise.

### Reclaim-as-vacate

Slots are stable, reusable dirs — reclaim frees one, it doesn't destroy it. When a warm feature's PR merges:

- **Clean worktree** → `git checkout <default_branch>` in the slot's worktree(s), drop the feature's `slots.json` entry. The slot returns to the pool — on base, ready for the next tenant, dir + warm deps (`node_modules`, etc.) persist for whoever lands there next.
- **Dirty worktree** → left untouched; surfaced as an advisory (`reclaimable_but_dirty`) instead of auto-vacating. Resolve the dirty state first.
- The merged local branch is kept by default — deleting it is separate opt-in cleanup (`branch delete`).

Detection is **passive, not polled**: `canopy reclaim` runs it on demand; `canopy context --remote` also runs it as a side effect (any remote-aware read that already sees a merged PR reclaims eagerly); `doctor` flags stragglers too. There's no background poller watching PR state.

### Auto-bootstrap on slot creation

A slot arrives workable, not empty. Split by cost:

- **Fast steps run synchronously** at slot creation: env-file copy, IDE workspace gen, and per-clone hook install (husky's `prepare` script, or pointing `core.hooksPath` at an existing `.husky/`). The worktree is immediately usable for edit / commit / push the moment `switch`/`worktree`/`slot load` returns.
- **Deps install (`install_cmd`) runs detached in the background.** Status lives in `slots.json` per slot+repo and surfaces in `canopy context`: `installing` → `ready` → `failed` (failure is a loud state, never a silent "ready when it isn't" — stderr is captured to `.canopy/logs/`). A failed or still-installing slot names its own retry: `canopy worktree-bootstrap --deps <feature>`.
- **Lockfile-unchanged short-circuits the install** — slot dirs are stable, so deps mostly install once per slot, not once per tenant.
- **`--interactive`** runs the deps install in the foreground instead, for installs that need a prompt (auth, a pnpm build-script approval) the detached background attempt can't satisfy. **`--force`** bypasses the lockfile short-circuit / overwrites existing env files.

This split (fast-sync / deps-background) is **provisional** — a working hypothesis being validated by dogfooding, not a settled contract. It's a manual command too: `canopy worktree-bootstrap <feature> [--step env|deps|ide] [--deps] [--interactive] [--force]`.

### Slot vocabulary

Five verbs total, all with CLI + MCP parity:

| Verb | What it does |
|---|---|
| `switch <Y>` | Promote Y to canonical (trunk) — the RUN verb. Vacating-feature rotation handled by the warm-vs-cold rule above. `--evict-to <slot-N>` pins where the outgoing canonical goes; `--to-slot <slot-N>` promotes whatever feature already occupies that slot. |
| `slot load <Y> [<slot-N>]` | Warm a cold Y into a slot **without** touching canonical. Used for pre-warming or inspecting a feature before switching to it. |
| `slot clear <slot-N>` | Evict that slot's occupant to cold (with feature-tagged stash if dirty). The slot itself remains; it's just empty. |
| `slot swap <slot-A> <slot-B>` | Exchange the occupants of two warm slots. v1 requires identical repo scope on both features. |
| `reclaim` | Free every warm slot whose feature's PR(s) merged/closed and whose worktree is clean — vacate to base, drop the slot entry, return it to the pool. Dirty merged slots are reported as advisories, not touched. |

`worktree-N` is also a universal alias form — any tool that takes a feature alias also accepts a slot id (`feature_state worktree-2`, `pr worktree-1`, etc.) and resolves to the slot's current occupant.

### Why this model

It matches a mental model where there's one feature **running** — booted, live at localhost, the thing your git GUI is staring at — while others sit in workable warm slots getting review comments addressed, or cold and out of the way. `switch` makes managing *what's running* easier: one verb to promote whichever feature deserves trunk right now, with the previously-running one either parked warm (still open-PR-active, instant to switch back) or wound down cold (preserved but out of the way) depending on the warm-vs-cold rule.

Decoupling slot identity from feature identity matters because:
- The dashboard can render slots in stable order even as occupants change.
- A "swap" is just a JSON edit + per-repo checkouts; no directory rename.
- `worktree-N` is a stable shell PATH to a warm tree you can actually work in — edit, commit, push, lint, unit-test — just not run full-stack.
- Reclaim can vacate a slot back to the pool without deleting the directory or its installed deps.
- Migration from pre-3.0 layouts is a one-shot, idempotent operation (`canopy migrate-slots`).

### What `switch` is *not*

- **Not branch-management.** `switch` doesn't create branches that don't exist (that's `feature_create`), doesn't open IDEs (that's `code`), doesn't commit/push (those are `commit`/`push`/`ship`). It only moves features between {canonical, warm, cold}.
- **Not slot-allocation either.** Use `slot load` to warm a cold feature into a slot without changing canonical. Use `slot clear` to free a slot without bringing a new feature in. `switch` is specifically the "what's running" verb.
- **Not the review-changes verb.** Addressing PR comments, small edits, lint/unit-test fixes — those happen in the feature's warm worktree with no `switch` at all (see the intent-gated section above). Reach for `switch` only when you need to actually run the feature.
- **Not unsafe.** `switch` validates every in-scope repo before mutating any (branches exist, worktrees clean-or-stashable, target slot resolved or the cap-choice already made) — this closes the partial-mutation class behind two historical bricking bugs (a `no_free_slot` firing after some repos had already flipped; an `in_flight` stamp left on a clean no-op). A fast-path 5-op-per-repo swap covers the case where Y is already warm; a journaled rollback walker plus a `slots.json.in_flight` marker back up the residual real-world failures (disk full, network blip, partial multi-repo failure). Either every repo finishes the switch or every repo rolls back to its pre-switch state.

## 5. Returning to a feature — the resume brief

When the agent (or human) returns to a feature in a new session, `canopy resume <alias>` (or `mcp__canopy__feature_resume(alias)`) runs the full recovery chain:

```
alias → switch-if-needed → refresh GitHub + Linear → brief → bump last-visit anchor
```

One call gets you oriented. There's no separate "switch, then fetch PR state, then read comments" dance.

### What the brief carries

```json
{
  "version": 1,
  "feature": "SIN-12-search",
  "now": "2026-05-30T10:00:00Z",
  "last_visit": "2026-05-29T15:30:00Z",
  "first_visit": false,
  "window_hours": 18.5,
  "switch_performed": true,
  "switch_summary": {"status": "ok"},
  "intent_hints": [
    {"kind": "review_comments", "summary": "2 open threads", "suggested_tool": "github_get_pr_comments", "suggested_args": {}, "priority": 1}
  ],
  "since_last_visit": {
    "commits": {
      "backend": [{"sha": "abc1234", "short_sha": "abc1234", "at": "2026-05-30T09:00:00Z", "author": "alice", "subject": "fix: auth token refresh"}]
    },
    "threads_new": [
      {"thread_id": "PRRT_1", "comment_id": 42, "author": "bob", "path": "src/auth.py", "line": 10, "body_excerpt": "This needs a guard.", "created_at": "2026-05-30T08:00:00Z", "url": "https://github.com/...", "repo": "backend", "pr_number": 7}
    ],
    "threads_resolved_on_github": [],
    "threads_resolved_by_canopy": [],
    "ci_status_delta": {},
    "draft_replies_pending": 1,
    "historian_excerpt": "Last session: implemented token refresh. Left off before adding tests."
  },
  "current_state": {
    "feature_state": "needs_work",
    "open_thread_count": 2,
    "ci_summary_per_repo": {"backend": "passing"},
    "bot_unresolved_total": 0,
    "draft_replies_summary": {"addressed_total": 1, "unaddressed_total": 1},
    "branch_position_per_repo": {"backend": {"branch": "SIN-12-search", "default_branch": "main", "ahead": 3, "behind": 0, "last_sync_at": "2026-05-30T09:00:00Z"}},
    "linear_issue": "SIN-12",
    "linear_url": "https://linear.app/..."
  }
}
```

- `switch_performed` — whether `resume` had to call `switch` to move the feature to canonical.
- `first_visit` — true when no prior anchor exists; no delta computed.
- `window_hours` — wall-clock hours since the last visit anchor was set.
- `since_last_visit` — full delta since the last visit: `commits` (per-repo list), `threads_new` (unresolved threads whose first comment is newer than last_visit), `threads_resolved_on_github` and `threads_resolved_by_canopy` (two separate resolution logs), `draft_replies_pending` count, `historian_excerpt`.
- `current_state` — live snapshot from `feature_state` + branch positions + Linear link. NOT forwarded verbatim; the brief extracts specific fields into this sub-object.
- `intent_hints` — canopy's best guess at the most likely next action categories (e.g., `review_comments`, `check_ci`, `push`). Derived from the brief data, not from `feature_state`. Use as a prompt, not a constraint.

### Freshness policy

- **Every `resume` call refreshes GitHub + Linear.** The brief is never cached at the canopy layer; upstream HTTP/MCP layers may cache.
- **Auxiliary state** (`bot_resolutions`, `thread_resolutions`, `visits.json`) is read live on every call.
- **`switch` always bumps `last_visit`.** Every `switch` call (whether invoked directly or triggered internally by `resume`) bumps `last_visit` for the incoming feature after the slot state is written. When you call `switch` without `resume` — e.g., a quick focus change mid-session — the switch return includes a lightweight `since_last_visit_summary` (counts only, no intent hints) so you immediately see whether anything changed since you were last here. `degraded: true` appears in this field when GitHub is unreachable.

### Last-visit anchor — the single-bump invariant

`visits.json` stores `{feature: {last_visit: <ISO>, previous_visit: <ISO|null>}}`. The anchor advances exactly once per `feature_resume` call. If `resume` triggered a `switch`, the bump happened inside `switch` — `resume` does NOT bump again. If no switch ran, `resume` bumps at the END of the call (after the brief is computed). Either way, exactly one bump per `feature_resume` invocation.

This invariant means:
- The delta window always reflects the period since you last *consciously* resumed the feature, not since the last focus change.
- Repeated `resume` calls in quick succession return the same delta (not a 0-minute window the second time).
- `--reset-anchor` (CLI) / `reset_anchor=True` (MCP) explicitly resets the anchor to now — use when you want to start fresh without reopening a new session.
