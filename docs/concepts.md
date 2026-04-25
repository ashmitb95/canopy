# Concepts

Three ideas hold canopy together. Other docs assume them.

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
  "what": "branches don't match feature lane 'doc-3029'",
  "expected": {"branches": {"api": "doc-3029", "ui": "doc-3029"}},
  "actual":   {"branches": {"api": "doc-3029", "ui": "main"}},
  "fix_actions": [
    {"action": "realign", "args": {"feature": "doc-3029"},
     "safe": true, "preview": "checkout doc-3029 in ui (clean)"}
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
| Feature name | `doc-3029-paired` | Matches `features.json` entry |
| Linear issue ID | `ENG-412` | Matches lane's `linear_issue` field |
| Specific PR | `<repo>#<n>` like `docsum-api#1287` | Bypasses feature lookup |
| PR URL | `https://github.com/owner/repo/pull/1287` | Parsed |
| Specific branch | `<repo>:<branch>` | For `branch info` |

For features whose branch differs across repos (e.g., `doc-1003-fixes` in api, `DOC-1003-fixes-v2` in ui), the lane's `branches` map handles it transparently. You pass the canonical feature alias; canopy resolves per-repo branches.

## 3. The 8-state machine

`canopy state <feature>` (and the MCP tool `feature_state(feature)`) returns one of 8 states + an ordered `next_actions` array. Same data the [VSCode extension](https://marketplace.visualstudio.com/items?itemName=SingularityInc.canopy) dashboard renders.

| State | Detection | Primary `next_actions` |
|---|---|---|
| **`drifted`** | live `current_branch` ≠ expected for any repo in the lane | `realign(feature)` |
| **`needs_work`** | clean + (CHANGES_REQUESTED or actionable comments) | `address_review_comments(feature)` |
| **`in_progress`** | aligned + dirty + no fresh preflight | `preflight(feature)` |
| **`ready_to_commit`** | aligned + dirty + preflight passed for current HEAD | `commit(feature)` |
| **`ready_to_push`** | aligned + clean + ahead of remote | `push(feature)` |
| **`awaiting_review`** | aligned + clean + PRs open + no actionable threads | refresh / wait |
| **`approved`** | all PRs APPROVED | `merge` |
| **`no_prs`** | aligned + clean + no PRs anywhere | `pr_create(feature)` |

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
