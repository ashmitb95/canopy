# CI status integration in `feature_state`

## Why

Today canopy's 8-state machine knows about PR review state (`changes_requested`, `approved`, etc.) but is blind to CI check runs. That makes `approved` a misleading terminal state when 2 of 3 GitHub Actions are red — the agent (or you) thinks the feature is ready to merge, runs `gh pr merge`, and discovers the gating problem post-hoc.

The real "ready to merge" question is `approved && all_required_checks_passing && no_pending_checks`. Canopy's state machine should answer that.

This plan adds CI status as a first-class field on `feature_state.repos[*].pr` and introduces a new `awaiting_ci` state that sits between `awaiting_review` and `approved`, so the lifecycle reads:

```
needs_work → in_progress → ready_to_commit → ready_to_push
  → awaiting_review → awaiting_ci → approved → (merged via gh)
```

The agent reads `feature_state(feature).next_actions` and knows: ignore, address comments, run preflight, push, wait for review, *wait for CI*, merge.

---

## Behavioral spec

### New field on `feature_state.repos[*].pr`

```python
{
  "pr": {
    "number": 142,
    "url": "https://github.com/.../pull/142",
    "state": "open",
    "review_decision": "approved",        # existing
    "ci_status": {                         # NEW
      "status": "pending" | "passing" | "failing" | "no_checks",
      "passed": 8,                         # count
      "failing": 1,
      "pending": 2,
      "skipped": 0,
      "required_failing": ["lint", ...],   # required checks that are failing (gating)
      "required_pending": ["e2e-test"],    # required checks pending
      "details_url": "https://...",        # GH checks tab
    }
  }
}
```

`status` is the rolled-up answer: `passing` only when every required check passed and zero pending; `failing` when any required failed; `pending` when nothing failing but at least one required is pending; `no_checks` when the PR has no associated check runs.

### State machine extension

Insert `awaiting_ci` between `awaiting_review` and `approved`. Rules per repo:

| review_decision | ci_status | Resulting state contribution |
|---|---|---|
| (none) | (any) | feed into `awaiting_review` (existing) |
| `changes_requested` | (any) | `needs_work` (existing) |
| `approved` | `passing` | `approved` |
| `approved` | `pending` | `awaiting_ci` (NEW) |
| `approved` | `failing` | `needs_work` (CI is a blocker — same intent as a request for changes) |
| `approved` | `no_checks` | `approved` (no CI configured = trust review) |

Multi-repo aggregation: feature-level state is the "least-ready" repo state in canonical lifecycle order. So if api is `approved` and ui is `awaiting_ci`, the feature is `awaiting_ci`.

### `next_actions` updates

When state is `awaiting_ci`, next_actions reads:

```
1. Wait for {required_pending} to complete (estimated <duration>)
2. If a check is failing: investigate the failing check at <details_url>
3. (Optional) Re-run failing checks via `gh pr checks --watch` or by pushing an empty commit
```

Action 1 surfaces only when nothing is failing yet. Action 2 surfaces when there's a failing required check.

### CLI rendering

`canopy state <feature>` and `canopy review <feature>` both gain a CI line per repo:

```
test-api    PR #142  approved  ci: 8 passed, 1 failing (lint), 2 pending
                              ↗ https://github.com/acme/test-api/pull/142/checks
```

`canopy triage` rolls up: a feature in `awaiting_ci` with failing required checks gets surfaced near `changes_requested` (not at the bottom with `approved`).

---

## State model changes

- New state enum value: `awaiting_ci`. Total states: 9 (was 8).
- `feature_state.repos[*].pr.ci_status` field added (optional — old MCP clients still work, just don't see it).
- `next_actions` array can include CI-driven entries.

---

## Command surface changes

| Today | After |
|---|---|
| `canopy review <feature>` | Output adds CI line per PR. Field `ci_status` in `--json`. |
| `canopy state <feature>` | New possible state `awaiting_ci`. |
| `mcp__canopy__pr_checks(alias)` (does not exist) | New MCP tool returning the raw check-run list for a PR (useful when the rolled-up `ci_status` isn't enough — e.g., agent wants to look at one specific check's logs). |
| `canopy triage` | Sort order accounts for `awaiting_ci` failing-required ahead of plain `approved`. |

---

## Files to touch

### New

- `src/canopy/integrations/github_checks.py` — wraps `gh pr checks --json` (or MCP `get_pr_checks` if configured). Returns the structured check-run list. Mirrors the existing pattern in `integrations/github.py` for review_status.
- `tests/test_ci_status.py` — table-driven cases for each state-machine row above.

### Modified

- `src/canopy/integrations/github.py` — add `get_pr_checks(repo, pr_number)` helper returning the rolled-up `ci_status` dict + raw check list. Or split into `github_checks.py` if it's getting fat.
- `src/canopy/actions/feature_state.py` — extend `_per_repo_facts` to call `get_pr_checks` per repo with an open PR, populate `ci_status`. Extend the state-resolution function to incorporate ci_status per the matrix above. Add `awaiting_ci` to the state enum + `next_actions` for it.
- `src/canopy/actions/triage.py` — adjust priority sort to weight `awaiting_ci`-with-failures above `approved`.
- `src/canopy/cli/main.py` — `cmd_review` and `cmd_state` render the new CI line.
- `src/canopy/mcp/server.py` — register `pr_checks(alias)` tool (universal-alias resolved).
- `docs/concepts.md` — update the state machine diagram + state list.
- `docs/agents.md` — update review-loop recipe with `awaiting_ci` handling.
- `docs/commands.md` — `state` and `review` sections show the CI rendering.

---

## Tasks (rough sequence)

### T1 — `get_pr_checks` integration

Wrap `gh pr checks <pr-number> --json name,state,bucket,conclusion,workflow,detailsUrl,startedAt`. Compute `ci_status` rollup from the raw list. Distinguish required vs informational checks via `gh api repos/.../branches/main/protection` (cached per workspace, refreshed lazily). Fallback when MCP `pull_request_checks` tool is configured: prefer that.

Returns `(ci_status, raw_check_list)`.

Tests: mock `gh` subprocess + happy / failing / pending / no-checks variants.

### T2 — Extend `feature_state`

`_per_repo_facts` calls `get_pr_checks` for each open PR. Populates `ci_status`. State-resolution function gets the new matrix branch.

Tests: workspace_with_feature + variants per matrix row. Snapshot test the resulting `feature_state` JSON.

### T3 — `awaiting_ci` state + `next_actions` text

Add the enum value. Implement the next_actions builder for the new state — distinguishing "wait" (all required pending, none failing) from "investigate" (at least one required failing).

Tests: snapshot the `next_actions` strings for representative inputs.

### T4 — CLI rendering

Extend `cmd_review` and `cmd_state` output. Add the per-repo CI line. Honor `--json` (already passes through structured).

### T5 — Triage priority

`actions/triage.py` priority weights: `changes_requested` > `awaiting_ci (failing required)` > `awaiting_ci (pending)` > `awaiting_review` > `approved`. Update sort.

Tests: triage fixture with mixed-state features asserts the order.

### T6 — `pr_checks` MCP tool

Universal-alias resolved (existing pattern). Returns the raw check list (the second value from `get_pr_checks`).

### T7 — Docs + skills

`docs/concepts.md` state diagram updated. `docs/agents.md` review recipe extended. `docs/commands.md` rendering examples. Both skill files note `awaiting_ci` and `pr_checks`.

---

## Edge cases to remember

- **Repo with no GH Actions configured at all.** `gh pr checks` returns an empty list. Treat as `no_checks`, state contribution is `approved` (no CI to wait for).
- **Required-checks list is empty (branch protection lax).** Same as no_checks for state-machine purposes; CI runs are informational.
- **A check is rerunning.** Looks like `pending` from `gh pr checks`. Treated as pending. If the rerun was started by canopy, that's fine; if by the user, also fine.
- **Stale PR with old check runs.** `gh pr checks` returns the latest run per check. No special handling.
- **Privately-hosted GitHub.** `gh` honors `GH_HOST` / `GITHUB_HOST` env. Should work without code changes; doc the requirement.
- **PR closed/merged before checks completed.** Closed PRs return checks but the state-machine ignores them — feature drops out of active triage.

---

## Out of scope

- **Auto-merging when CI passes.** That's `gh pr merge --auto`'s job. Canopy reports state; merge is a human/agent action.
- **Re-running failed checks.** Same — out of scope. User runs `gh run rerun` or `gh pr comment` with `/rerun`.
- **CI provider abstraction.** v1 is GitHub Actions via `gh pr checks`. CircleCI / Buildkite / GitLab are future extensions; the abstraction would live in `integrations/ci.py` with provider-specific backends. Not v1.
- **Required vs informational distinction precision.** v1 reads branch protection rules; teams that gate via CODEOWNERS or arbitrary GH Apps may need follow-up tuning.

---

## After this lands

- The "approved" state actually means "ready to merge." No more "approved + 1 failing check" surprise at merge time.
- Agents in the post-review loop can wait correctly for CI before claiming the feature is done.
- `canopy triage` better reflects what's blocked vs what's ready — `awaiting_ci`-with-failures floats up; pure `approved` floats up too but is differentiated.
- Pairs with the (future) `ship` MCP tool (Wave 2.4 plan): `ship` becomes safer because it knows whether to merge or wait.
