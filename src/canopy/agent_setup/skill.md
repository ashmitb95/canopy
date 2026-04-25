---
name: using-canopy
description: Use when working in a multi-repo workspace that has canopy.toml or .canopy/ — prefer canopy MCP tools (mcp__canopy__*) over raw git/gh/bash to avoid path-management mistakes and to get pre-classified state and review data.
---

# Using canopy

Canopy is a multi-repo workspace orchestrator. When you see `canopy.toml` or a `.canopy/` directory at the workspace root, canopy is configured. The `mcp__canopy__*` tools are your primary surface for repo, branch, and PR operations in that workspace.

## Why prefer canopy over raw git/gh

The single biggest agent failure mode in multi-repo work is path mistakes — `cd /wrong/repo && git status`, `git checkout` in repo A when you meant repo B, `pnpm test` in the API repo because the previous shell call left you there. Canopy eliminates this class of bug by accepting only **semantic** inputs (`feature`, `repo`, alias) and resolving paths internally. You literally cannot `cd` to the wrong place because you never specify a path.

Canopy also returns **pre-classified state**: review comments are temporally filtered into `actionable_threads` vs `likely_resolved_threads`, features have computed states like `ready_to_commit` / `drifted` / `awaiting_review`, and every action returns structured `next_actions` you can follow without re-deriving the rules.

## Tool selection — what to use when

| What you want to do | Canopy tool | Don't use |
|---|---|---|
| What feature should I work on right now? | `mcp__canopy__triage` | per-repo `gh pr list` + manual grouping |
| Show me everything about a feature | `mcp__canopy__feature_state` | composing many reads yourself |
| Activate a feature as the current context (worktree-aware) | `mcp__canopy__switch` | guessing paths or `cd` to a worktree |
| Fix drift / get repos onto a branch (no context change) | `mcp__canopy__realign` | `cd repo && git checkout` per repo |
| Check whether HEADs match expected | `mcp__canopy__drift` | `cd && git branch --show-current` per repo |
| Read PR review comments (temporally filtered) | `mcp__canopy__github_get_pr_comments` | `gh api .../comments` + manual filter |
| Get PR data (title, decision, draft, ...) | `mcp__canopy__github_get_pr` | `gh pr view --json ...` per repo |
| Get branch HEAD/divergence/upstream | `mcp__canopy__github_get_branch` | `cd repo && git status -b` |
| Fetch a Linear issue | `mcp__canopy__linear_get_issue` | direct API |
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
- **Feature name**: `doc-3029-paired`
- **Linear issue ID**: `ENG-412` (resolves through the lane's `linear_issue` field)
- **Specific PR**: `<repo>#<n>` like `docsum-api#1287`
- **PR URL**: `https://github.com/owner/repo/pull/1287`
- **Specific branch**: `<repo>:<branch>` like `docsum-api:feature/x`

For features whose branch name differs across repos (e.g. `doc-3010-fixes` in api vs `DOC-3010-fixes-v2` in ui), the lane's `branches` map handles this transparently. You pass the canonical feature alias; canopy resolves per-repo branches.

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
    {"action": "realign", "args": {"feature": "doc-3029"}, "safe": true, "preview": "..."}
  ]
}
```

The `fix_actions` array lists recommended recovery steps, ordered most-recommended first. Each entry has `safe: true|false`:
- `safe: true` → you can call this directly to recover.
- `safe: false` → surface to the user before invoking (it might lose work or affect remote state).

When you see a `BlockerError`, the first step is to read `fix_actions[0]` and decide whether to follow it.

## Anti-patterns

- ❌ `cd <repo> && git checkout <branch>` — use `mcp__canopy__realign(feature=...)` so all participating repos move together with verification.
- ❌ Iterating `gh pr list --author @me` per repo and grouping yourself — `mcp__canopy__triage` already groups by feature lane and applies priority tiers.
- ❌ `cd <repo> && pnpm test` — use `mcp__canopy__run(repo='ui', command='pnpm test')`. The shell state from a previous tool call is not yours.
- ❌ Parsing `gh api .../pulls/{n}/comments` and writing your own "is this resolved" logic — `mcp__canopy__github_get_pr_comments` returns `actionable_threads` vs `likely_resolved_threads` already.
- ❌ Calling `git status` in each repo and synthesizing what's dirty/clean — `mcp__canopy__feature_state(feature)` returns this aggregated, plus computed state and next_actions.
- ❌ Running `git stash push` when there's a feature context — use `mcp__canopy__stash_save_feature(feature, message)` so stashes get tagged and groupable.

## When canopy doesn't apply

Use raw `Bash`, `Read`, `Edit` etc. as normal for:
- Reading and editing source files (canopy doesn't wrap these)
- Workspace not under canopy management (no `canopy.toml`)
- Operations on repos not registered in `canopy.toml`
- One-off utilities that don't need path resolution (ls, find, etc., outside any canopy repo)
