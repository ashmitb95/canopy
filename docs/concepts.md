# Concepts

Canopy's vocabulary. Other docs assume these ideas.

## The two surfaces

Canopy 4.0 — *the great distillation* — splits into **two surfaces**, and that split is the frame everything else hangs off.

**1. The agent contract — 15 MCP tools.** The agent sees only what it needs to work safely and stay oriented: **path-safety + registry + focus + safe-git-ops + recovery.** It never names a directory — it names semantic context (`feature`, `repo`, alias) and canopy resolves paths internally, so the agent literally cannot `cd` to the wrong repo or commit from the parent dir. Claude Code enforcement hooks keep git honest at the wire (§7). The agent's context budget goes to **comprehension, not orchestration.**

**2. The human / dashboard management surface — CLI `--json`.** PR triage, review-comment classification, bot rollups, ship, historian, resume briefs, conflict detection, Linear/GitHub reads — the *management* work — is **not** on the agent surface. It lives in `canopy/management/` and is reached by a human (or the dashboard/GUI) via `canopy <cmd> --json`. Same JSON shape across CLI, MCP, and any GUI.

> Pre-4.0, canopy exposed dozens of MCP tools to the agent, and the agent spent context orchestrating PR management instead of understanding code. 4.0 distills the agent surface to the 15 tools of the core loop and moves management to where a human or dashboard consumes it. **Nothing was deleted** — management moved *off* the agent surface. Every `canopy triage / review / ship / resume / conflicts / bot-status / historian` command still works as a CLI command with `--json`. The agent sees less so it can understand more.

The 15 agent tools, grouped by role in the daily loop (this grouping is used verbatim across the docs):

| Group | Tools | Purpose |
|---|---|---|
| **Meta** | `version` | Version handshake for `doctor` staleness checks. |
| **Registry** | `context`, `start`, `join` | The single-read workspace map (feature ↔ repo ↔ branch ↔ path ↔ state, local + remote PR/CI tier); lazy feature start; register a repo into the active feature. See §6. |
| **Focus / slots** | `switch`, `reclaim` | Promote a feature into trunk (the run target); free a warm slot whose PR merged. See §4. |
| **Safe git ops** | `run`, `commit`, `push`, `preflight` | Path-safe shell exec; feature-scoped multi-repo commit (commit-only in 4.0); push across the lane; pre-commit gate. |
| **Recovery** | `doctor`, `drift` | 21-code / 11-category integrity check + repair; branch-drift detection across repos. |
| **WIP + workable slots** | `stash_save_feature`, `stash_pop_feature`, `worktree_bootstrap` | Feature-tagged stash save/pop; bootstrap a warm slot (env / deps / hooks / IDE). |

Full agent reference: [mcp.md](mcp.md). Full CLI (core + management) reference: [commands.md](commands.md).

Everything below defines the ideas these tools are built on. §1–§2 are the invariants both surfaces obey; §3 is a management-surface read; §4–§7 are the 4.0 machinery.

## 1. The action framework

Canopy is organized around **actions**. An action is a recipe with three parts:

```
preconditions  →  steps  →  completion criteria
   (block?)         (do)        (verify, don't assume)
```

If preconditions fail, the action **refuses to run** and returns a structured `BlockerError` describing what's wrong AND how to fix it. If steps complete, the action **verifies** the new state matches the criteria — it doesn't assume "no exception" means "done".

Two flavors:

- **Procedural actions** — canopy runs the recipe deterministically, no LLM in the loop. Examples: `switch`, `preflight`, `commit`, `drift` (agent surface); `triage`, `review`, `ship` (management surface). These are the everyday tools.
- **Agentic actions** — canopy bootstraps an LLM with a prompt + tool allowlist, then verifies completion (planned). These are the higher-order workflows.

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

This is correctness by construction. The single biggest agent failure mode in multi-repo work is `cd /wrong/repo && command`. Canopy eliminates it because the agent has no surface area to type the path. `mcp__canopy__run(repo='ui', command='pnpm test')` resolves the cwd and reports it back; you can't get `cwd` wrong if you don't pass `cwd`. Convention alone isn't enough — the **enforcement hooks (§7)** are the second half of this guarantee, blocking a raw `cd … && git …` that would slip past the tool boundary.

Three concrete rules:

1. **Inputs are semantic, not paths.** `feature: str`, `repo: str`, alias strings — never `cwd`, never absolute paths.
2. **PR is first-class context.** The state read (`context`, §6) carries PR state alongside branch state — number, URL, review decision — in its remote tier. Branches and PRs travel together.
3. **Verification is per-repo, structured.** Multi-repo write ops report `{repo: {status, before, after, reason?}}` so the agent never has to re-query to confirm.

### Universal aliases

Every tool that accepts a feature input accepts the same alias forms. Learn one rule, use everywhere:

| Form | Example | Notes |
|---|---|---|
| Feature name | `SIN-12-search` | Matches `features.json` entry |
| Linear issue ID | `SIN-12` | Matches lane's `linear_issue` field |
| Specific PR | `<repo>#<n>` like `backend#142` | Bypasses feature lookup |
| PR URL | `https://github.com/owner/repo/pull/142` | Parsed |
| Specific branch | `<repo>:<branch>` | For branch reads |
| Slot id | `worktree-2` | Resolves to that warm slot's current occupant (§4) |

For features whose branch differs across repos (e.g., `SIN-13-fixes` in backend, `SIN-13-fixes-v2` in frontend — common when one side rebases or renames mid-flight), the lane's `branches` map handles it transparently. You pass the canonical feature alias; canopy resolves per-repo branches via `lane.branch_for(repo)`.

## 3. The 9-state machine

`canopy state <feature>` (CLI `--json`, backed by `management/feature_state.py`) returns one of 9 states + an ordered `next_actions` array. This is a **management-surface** read — the same data the [VSCode extension](https://marketplace.visualstudio.com/items?itemName=SingularityInc.canopy) dashboard renders as its primary button. The agent doesn't drive the loop by polling state; it orients via `context` (§6) and acts on `next_actions` when a human or the dashboard surfaces one.

| State | Detection | Primary `next_actions` |
|---|---|---|
| **`drifted`** | live `current_branch` ≠ expected for any repo in the lane | `switch(feature)` (slot model — handles both worktree and main-tree cases) |
| **`needs_work`** | clean + (CHANGES_REQUESTED or actionable human comments) | address review comments |
| **`in_progress`** | aligned + dirty + no fresh preflight | `preflight(feature)` |
| **`ready_to_commit`** | aligned + dirty + preflight passed for current HEAD | `commit(feature)` |
| **`ready_to_push`** | aligned + clean + ahead of remote | `push(feature)` |
| **`awaiting_bot_resolution`** | clean + PR open + no human signal + ≥1 unresolved bot comment | address bot comments |
| **`awaiting_review`** | aligned + clean + PRs open + no actionable threads | refresh / wait |
| **`approved`** | all PRs APPROVED | `merge` (+ secondary bot-comment cleanup if bot threads remain) |
| **`no_prs`** | aligned + clean + no PRs anywhere | open a PR (`canopy ship`) |

**Bot vs human comment classification:** a comment counts as a bot when GitHub reports `author_type == "Bot"`. With `[augments] review_bots = ["coderabbit", ...]` set in canopy.toml, the author also has to substring-match the configured list — so an unconfigured bot account drops out of bot tracking and stays in the human bucket. Bot nits never gate `approved`; human approval is the merge gate.

Detection uses **live git state** (not the cached `.canopy/state/heads.json`) for correctness — even if the post-checkout hook hasn't fired, `feature_state` is right. The hook + `heads.json` exist to power the agent's `drift` fast path.

`next_actions[0]` is the suggested primary CTA. A human (or the dashboard) reads this instead of re-deriving the rules.

### State transitions

```
                       ┌────────── drift detected ─────────┐
                       ▼                                   │
                   drifted ──── switch ───┐                │
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
        address review comments
        │
        └────────────────► (back to in_progress)
```

Drift always wins — it supersedes all other states because operating on misaligned state corrupts subsequent work.

For **worktree-backed** features, drift detection runs against the worktree path (not main), so a worktree-backed feature is only `drifted` if someone manually `git checkout`'d to a different branch *inside the worktree*. The fix is `switch` (re-establishes the feature context), not a main-tree realign that would undo the protection worktrees provide.

### Cross-session memory

The historian keeps a per-feature persistent log at `<workspace>/.canopy/memory/<feature>.md` — decisions, comment activity, PR context, and session entries. It is a **management-surface** facility (`canopy historian …`, and read into the resume brief, §5), not an agent MCP tool. The log is append-only (concurrent writers flock-serialize), with three top-level sections:

- **Resolutions log** — per-comment outcomes (✓ resolved, ⊙ likely-resolved by classifier, ⊘ deferred). Never compacted.
- **PR context** — one block per PR with rationale + chronological updates. Never compacted.
- **Sessions** — newest-first per-session entries (decisions, pauses, events). Trimmed by `historian compact`.

## 4. The slot model

Every feature in canopy lives in exactly one of three states:

- **canonical (trunk)** — checked out in the main repo. There's exactly one canonical feature at a time, across all repos. This is what your IDE, git GUI, default `git status`, blame, and log all naturally reflect. **Canonical is the only place to run code full-stack** — boot the app, hit real ports, integration-test.
- **warm** — occupies a numbered **slot** at `.canopy/worktrees/worktree-N/<repo>/`. Slot identity (`worktree-1`, `worktree-2`, ...) is stable across feature swaps; feature occupancy is transient. A slot holds one feature at a time; that feature's repos sit as siblings inside the slot. Capped by `[workspace] slots = N` in canopy.toml (default **2** — so you keep at most 1 canonical + 2 warm = 3 simultaneous live trees). **Warm slots are workable, not just parked:** they're auto-bootstrapped on creation, so you can edit / commit / push / lint / unit-test right there without switching. What you can't do in a warm slot is run the project full-stack — that still needs trunk.
- **cold** — branch exists, no slot, no checkout. Cheap, unlimited. Plus any feature-tagged stash that was preserved when it was last unloaded.

### Intent-gated switch: worktree vs trunk

**Intent decides whether you switch — not the act of returning to a feature.** The two-tier model is: trunk is the RUN target, worktrees are the WORK target for review.

- **"Address the review comments on DOC-Y"** → edit / commit / push **in DOC-Y's warm worktree**. No switch. `canopy context` gives you the path; the enforcement gate (§7) allows commits/pushes there. You never leave whatever's currently running in trunk.
- **"Run DOC-Y full-stack / verify it in the app"** → `canopy switch DOC-Y` promotes it into trunk — the only place with ports, services, the full env.

Routing is implicit and one-directional: canopy publishes the map (`context` gives feature ↔ repo ↔ path ↔ slot state), the enforcement gate keeps work honest wherever you are, and `run --feature X` resolves to X's current location (its warm worktree, or trunk if it's canonical) — there's no separate `work` verb. `switch` is the one control verb, and it means specifically "move X into trunk so it can run." This evolves, not breaks, the older "canonical is the only run target" rule — trunk is still the only run target; worktrees are now the work target for review instead of purely passive storage.

`canopy switch <Y>` is the primitive that moves features between {canonical, warm, cold}. What happens to the outgoing canonical feature X is no longer a mode you choose up front — it's a rule:

### Warm-vs-cold rule

When X vacates trunk (because Y is switching in to run), X goes:

- **warm** iff it has an **open PR** or **live/uncommitted WIP** — it's either being shepherded through review or mid-flight enough that you'll want it back instantly.
- **cold** (with a feature-tagged stash for any dirty work) otherwise.

`--release-current` forces cold regardless (explicit wind-down, for when you know X is parked/finished even if the rule would keep it warm). `--evict <f>` / `--evict-to <slot-N>` remain as explicit overrides on which feature or slot is affected. When Y is *already warm*, the swap is a fast 5-op-per-repo dance: no `mv`, no `git worktree repair`, no slot renaming — the slot ids stay put, only the features inside them swap.

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
- The merged local branch is kept by default — deleting it is separate opt-in cleanup.

Detection is **passive, not polled**: `canopy reclaim` runs it on demand; `context` with the remote tier (§6) also runs it as a side effect (any remote-aware read that already sees a merged PR reclaims eagerly); `doctor` flags stragglers too. There's no background poller watching PR state.

### Auto-bootstrap on slot creation

A slot arrives workable, not empty. Split by cost:

- **Fast steps run synchronously** at slot creation: env-file copy, IDE workspace gen, and per-clone hook install (husky's `prepare` script, or pointing `core.hooksPath` at an existing `.husky/`). The worktree is immediately usable for edit / commit / push the moment `switch` / `worktree_bootstrap` returns.
- **Deps install (`install_cmd`) runs detached in the background.** Status lives in `slots.json` per slot+repo and surfaces in `context`: `installing` → `ready` → `failed` (failure is a loud state, never a silent "ready when it isn't" — stderr is captured to `.canopy/logs/`). A failed or still-installing slot names its own retry: `canopy worktree-bootstrap --deps <feature>`.
- **Lockfile-unchanged short-circuits the install** — slot dirs are stable, so deps mostly install once per slot, not once per tenant.
- **`--interactive`** runs the deps install in the foreground instead, for installs that need a prompt (auth, a pnpm build-script approval) the detached background attempt can't satisfy. **`--force`** bypasses the lockfile short-circuit / overwrites existing env files.

This split (fast-sync / deps-background) is **provisional** — a working hypothesis being validated by dogfooding, not a settled contract. It's a manual command too: `canopy worktree-bootstrap <feature> [--step env|deps|ide] [--deps] [--interactive] [--force]`.

### Slot vocabulary

Two verbs are on the agent (MCP) surface — `switch` and `reclaim`; the finer slot controls (`slot load` / `slot clear` / `slot swap`) are CLI-side, since a feature's location is otherwise driven by intent through `switch`.

| Verb | Surface | What it does |
|---|---|---|
| `switch <Y>` | agent + CLI | Promote Y to canonical (trunk) — the RUN verb. Vacating-feature rotation handled by the warm-vs-cold rule above. `--evict-to <slot-N>` pins where the outgoing canonical goes; `--to-slot <slot-N>` promotes whatever feature already occupies that slot. |
| `reclaim` | agent + CLI | Free every warm slot whose feature's PR(s) merged/closed and whose worktree is clean — vacate to base, drop the slot entry, return it to the pool. Dirty merged slots are reported as advisories, not touched. |
| `slot load <Y> [<slot-N>]` | CLI | Warm a cold Y into a slot **without** touching canonical. Used for pre-warming or inspecting a feature before switching to it. |
| `slot clear <slot-N>` | CLI | Evict that slot's occupant to cold (with feature-tagged stash if dirty). The slot itself remains; it's just empty. |
| `slot swap <slot-A> <slot-B>` | CLI | Exchange the occupants of two warm slots. v1 requires identical repo scope on both features. |

`worktree-N` is also a universal alias form (§2) — any tool that takes a feature alias also accepts a slot id and resolves to the slot's current occupant.

### Why this model

It matches a mental model where there's one feature **running** — booted, live at localhost, the thing your git GUI is staring at — while others sit in workable warm slots getting review comments addressed, or cold and out of the way. `switch` makes managing *what's running* easier: one verb to promote whichever feature deserves trunk right now, with the previously-running one either parked warm (still open-PR-active, instant to switch back) or wound down cold depending on the warm-vs-cold rule.

Decoupling slot identity from feature identity matters because:
- The dashboard can render slots in stable order even as occupants change.
- A "swap" is just a JSON edit + per-repo checkouts; no directory rename.
- `worktree-N` is a stable shell PATH to a warm tree you can actually work in — edit, commit, push, lint, unit-test — just not run full-stack.
- Reclaim can vacate a slot back to the pool without deleting the directory or its installed deps.
- Migration from pre-3.0 layouts is a one-shot, idempotent operation (`canopy migrate-slots`).

### What `switch` is *not*

- **Not branch-management.** `switch` doesn't create branches that don't exist (that's `start` / `join`), doesn't open IDEs, doesn't commit/push (those are `commit` / `push`). It only moves features between {canonical, warm, cold}.
- **Not slot-allocation either.** Use `slot load` to warm a cold feature into a slot without changing canonical. Use `slot clear` to free a slot without bringing a new feature in. `switch` is specifically the "what's running" verb.
- **Not the review-changes verb.** Addressing PR comments, small edits, lint/unit-test fixes — those happen in the feature's warm worktree with no `switch` at all (see the intent-gated section). Reach for `switch` only when you need to actually run the feature.
- **Not unsafe.** `switch` validates every in-scope repo before mutating any (branches exist, worktrees clean-or-stashable, target slot resolved or the cap-choice already made) — this closes the partial-mutation class behind two historical bricking bugs. A fast-path 5-op-per-repo swap covers the case where Y is already warm; a journaled rollback walker plus a `slots.json.in_flight` marker back up the residual real-world failures (disk full, network blip, partial multi-repo failure). Either every repo finishes the switch or every repo rolls back to its pre-switch state.

## 5. Returning to a feature — the resume brief

When a human returns to a feature in a new session, `canopy resume <alias>` (CLI `--json`, backed by `management/resume.py`) runs the full recovery chain:

```
alias → switch-if-needed → refresh GitHub + Linear → brief → bump last-visit anchor
```

One call gets you oriented. There's no separate "switch, then fetch PR state, then read comments" dance.

**The resume brief is a management-surface read** — it's how the human (or the dashboard) sees "what changed since I was last here." The **agent** doesn't call resume; at session start it orients via the SessionStart hook brief (§7) and `context` (§6), then acts. `resume` is the human's richer, network-backed counterpart.

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
    {"kind": "review_comments", "summary": "2 open threads", "priority": 1}
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
- `intent_hints` — canopy's best guess at the most likely next action categories (e.g., `review_comments`, `check_ci`, `push`). Derived from the brief data. Use as a prompt, not a constraint.

### Freshness policy

- **Every `resume` call refreshes GitHub + Linear.** The brief is never cached at the canopy layer; upstream HTTP/MCP layers may cache.
- **Auxiliary state** (`bot_resolutions`, `thread_resolutions`, `visits.json`) is read live on every call.
- **`switch` always bumps `last_visit`.** Every `switch` call (whether invoked directly or triggered internally by `resume`) bumps `last_visit` for the incoming feature after the slot state is written. A direct `switch` return includes a lightweight `since_last_visit_summary` (counts only, no intent hints) so a quick focus change still shows whether anything changed. `degraded: true` appears there when GitHub is unreachable.

### Last-visit anchor — the single-bump invariant

`visits.json` stores `{feature: {last_visit: <ISO>, previous_visit: <ISO|null>}}`. The anchor advances exactly once per `resume` call. If `resume` triggered a `switch`, the bump happened inside `switch` — `resume` does NOT bump again. If no switch ran, `resume` bumps at the END of the call (after the brief is computed). Either way, exactly one bump per invocation.

This invariant means:
- The delta window always reflects the period since you last *consciously* resumed the feature, not since the last focus change.
- Repeated `resume` calls in quick succession return the same delta (not a 0-minute window the second time).
- `--reset-anchor` explicitly resets the anchor to now — use when you want to start fresh without reopening a new session.

## 6. The registry

The registry is the agent's single orientation read, and the write verbs that put a feature on the map. Three tools: `context`, `start`, `join`.

**`context` — the single-read workspace map.** One call returns feature ↔ repo ↔ branch ↔ path ↔ state for the whole workspace. It supersedes the pre-4.0 `workspace_status` / `workspace_context` / `feature_list` / `feature_status` / `slots` tools — the agent no longer stitches state together from five reads. Two tiers:

- **Tier 1 — local, instant (default).** Everything derivable from disk + `.canopy/state/`: canonical feature, per-repo branch + dirty, slot occupancy, bootstrap status. No network.
- **Tier 2 — remote overlay (`remote=True`).** Adds the live PR + CI + origin-divergence overlay at network cost. Ask for it only when the task depends on remote state (addressing PR comments, checking CI). The remote tier is also where passive slot reclaim (§4) fires — a merged PR seen here reclaims eagerly.

**`start <feature>`** lazily begins new work on a feature — zero repos until you `join`. **`join <repo>`** registers a repo into the active feature (creating + registering its branch). Together they replace the old eager `feature_create`: you declare intent, then attach repos as the work actually touches them.

The registry is the canonical answer to "where am I, what's live, what's this feature's shape" — for the agent, `context` is that answer in one read.

## 7. Enforcement hooks

Path-safety (§2) is a contract the tools honor by construction — but an agent can still shell out to raw `git` through `run` or `Bash`. The enforcement hooks are the wire-level backstop, installed into `<workspace>/.claude/settings.json` via `canopy setup-agent --hooks`. Two hooks:

**PreToolUse git gate** (`actions/hook_gate.py`) — inspects every Bash command before it runs. It splits the command on top-level operators, resolves the **effective directory** of each segment (tracking `cd`-chains, `git -C`, and heredocs), and judges only the git *mutation* segments. If a mutation targets the wrong path or the wrong branch, the gate blocks it (exit code 2; the reason goes to stderr, which Claude Code feeds back to the model). Its contract is **fail-open**: any parse failure, unresolvable path, or internal error allows the command — the gate blocks only when it is *sure* the mutation is misplaced. This is the enforcement half of "the agent can't `cd` wrong."

**SessionStart brief** (`actions/hook_context.py`) — injects one compact block (kept under ~10 lines to protect the session's context budget) at the start of every session: the workspace name, the canonical feature, each repo's current branch + dirty count, warm-slot occupants, any advisories, and a closing reminder to confirm the branch matches the chat's ticket and `canopy switch <feature>` FIRST if it doesn't. The mismatch is visible *before* the agent reads a single file.

See [agents.md](agents.md) for installation detail and the full hook payload shapes.
