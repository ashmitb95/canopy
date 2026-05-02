# Wave 2.4 — `ship` as the canonical-feature delivery primitive

## Mental model

`ship` is the capstone of the per-feature workflow: take the canonical feature from "code is committed" to "PR is open + everything's pushed + reviewers can look." It's the multi-repo equivalent of:

```bash
git push -u origin HEAD && gh pr create --fill --base main
```

…repeated per repo, with cross-repo PR descriptions that link to each other so a reviewer landing on the backend PR knows about the frontend PR (and vice versa).

After Wave 2.9 + Wave 2.3, the user has:

- `canopy switch X` — focus a feature
- `canopy commit -m "msg"` — commit across all repos in the feature
- `canopy push` — push commits

`ship` is the next step: `canopy ship` opens (or updates) one PR per repo in the canonical feature, with linked descriptions and the Linear issue ID in the title. After ship, the workflow is reactive — wait for review, address comments, then `canopy ship` again to push the fixes.

**Idempotent.** First `ship` opens PRs. Second `ship` (after more commits + push) does nothing PR-wise — the PRs auto-update because they track the branch. Third `ship` (after closing one PR manually) reopens the missing one.

**No silent destruction.** If a PR exists but its branch was force-pushed and now diverges from main in unexpected ways, surface a warning, don't silently update the PR description.

---

## Behavioral spec

`canopy ship [--feature X] [--draft] [--reviewers user1,user2] [--dry-run]`

Pre: feature must have all repos pushed (commits exist on remote). If not, `ship` runs `push --set-upstream` first as part of the recipe — no separate command needed for the first ship.

| Pre-condition (per repo in scope) | Behavior |
|---|---|
| No commits unique to feature branch (branch == main HEAD) | `{repo, status: "skipped", reason: "no commits ahead of main"}`. Don't open empty PR. |
| Branch has unpushed commits | Run `push --set-upstream` first; on success, continue. |
| No PR exists for branch | `gh pr create --base <default> --head <branch> --title "<linear-id?> <feature-title>" --body <generated>` (+ `--draft` if flag, `--reviewer ...` if flag). Returns `{repo, status: "opened", pr_number, url}`. |
| PR exists, head matches our pushed sha | `{repo, status: "up_to_date", pr_number, url}`. PRs auto-track branch — nothing to do. |
| PR exists, head doesn't match (force-push divergence) | `{repo, status: "diverged", pr_number, url, warning: "PR head sha doesn't match local; manual review recommended"}`. Don't update the description. |
| PR is closed/merged | `{repo, status: "closed", pr_number, url, reason: "PR is closed; manual reopen needed"}`. Don't open a new PR (that'd duplicate review history). |
| Branch missing on remote | Push first (set-upstream), then create PR. |

**Returns:** `{ feature, results: { <repo>: {status, pr_number?, url?, reason?, warning?} }, cross_repo_links_updated: bool }`.

### PR title format

`<LINEAR-ID> <feature title or feature name>`

If feature has `linear_issue` set: `SIN-12 Add /search endpoint with shared filter types`. Else: just the feature name.

### PR body template (auto-generated)

```markdown
[Linear: SIN-12](<linear-url>)

This PR is part of the canopy feature `sin-12-search` (1 of 2 repos):

- backend: this PR (#<this-number>)
- frontend: <link to frontend PR>

## Commits in this PR

<bulleted list of commit subjects on the branch ahead of main>

---

🌳 Opened by [canopy](https://github.com/ashmitb95/canopy)
```

The cross-repo link section is what makes this primitive useful — reviewers see the related PRs without hunting. After ALL PRs are open, `ship` runs a second pass to update each PR's body with the *now-known* sibling PR numbers (initial open won't have them).

---

## State model changes

None at the canopy layer. PRs are GitHub state, not canopy state. The dashboard's `reviewStatus` MCP tool already reads PR existence — `ship` just causes more PRs to exist.

Optional (post-2.4 extension): cache `{feature, repo} → pr_number` in `.canopy/state/prs.json` so we can short-circuit the GitHub roundtrip when re-rendering the dashboard. Not required for 2.4; defer.

---

## Command surface changes

| Today | After Wave 2.4 |
|---|---|
| `canopy ship` (does not exist) | New CLI command + MCP tool. |
| `canopy review` | Unchanged (read-only PR status). |
| `canopy preflight` | Unchanged. |
| `canopy commit` / `canopy push` (Wave 2.3) | Unchanged; `ship` invokes `push` internally on first run. |

---

## Files to touch

### New

- `src/canopy/actions/ship.py` — orchestrator. Resolves canonical/explicit feature → for each repo: ensure-pushed → ensure-PR-exists → return result. Then runs the cross-repo description-update second pass.
- `src/canopy/integrations/github_pr.py` — split out from existing `integrations/github.py` if it's getting fat. Implements `create_pr(repo, branch, base, title, body, draft, reviewers)`, `get_pr(repo, branch)`, `update_pr_body(repo, pr_number, body)`. MCP-first, gh-CLI fallback (existing pattern).
- `tests/test_ship.py` — table-driven cases per row. Use the `gh` mock pattern from existing GitHub integration tests.

### Modified

- `src/canopy/cli/main.py` — `cmd_ship(args)`, dispatch + subparser.
- `src/canopy/mcp/server.py` — register `@mcp.tool() ship(...)`.
- `src/canopy/integrations/github.py` — if not splitting, add the three new functions here. Keep `BlockerError(code='github_not_configured')` semantics consistent with reads.
- `docs/commands.md` — add `ship` section with example flow.
- `docs/agents.md` — add to the workflow recipe ("preflight → commit → push → ship").
- Both skill files — flag `ship` as the preferred way to open canopy-feature PRs.

---

## Tasks (rough sequence)

### T1 — GitHub integration: PR create/get/update

`integrations/github.py` (or `github_pr.py`) gets three functions:

- `create_pr(repo, branch, base, title, body, draft=False, reviewers=None) -> {pr_number, url}` — uses MCP `create_pull_request` if configured, else `gh pr create --json number,url`.
- `get_pr(repo, branch) -> {pr_number, url, head_sha, state} | None` — uses MCP `get_pull_request` or `gh pr view --json`.
- `update_pr_body(repo, pr_number, body) -> None` — uses MCP `update_pull_request` or `gh pr edit --body`.

All three swallow `not configured` into `BlockerError(code='github_not_configured', fix_actions: [...install GitHub MCP / gh CLI...])`.

Tests: mock `gh` subprocess calls (existing pattern) + happy/blocker paths.

### T2 — `actions/ship.py` orchestrator

Resolve feature scope (canonical default; `--feature` override). For each repo in `lane.repos`:
  1. Check if branch ahead of main (else skip with "no commits").
  2. Check if pushed (else `push --set-upstream` via Wave 2.3 primitive).
  3. Check if PR exists (`get_pr`); if no → `create_pr`; if yes → return current.
  4. Append result row.

Second pass: now that all `(repo, pr_number)` pairs are known, regenerate each PR body with cross-repo links and call `update_pr_body` for each repo where the body changed (i.e., this is the first `ship` for that PR).

`--dry-run` populates the structured return without firing any state-changing call.

Tests: workspace_with_feature + 2 repos + variants per pre-condition row.

### T3 — CLI + MCP wrappers

CLI prints a per-repo summary table (status / PR # / URL) on stdout; `--json` returns the structured dict. MCP tool returns `result.to_dict()` directly.

### T4 — Cross-repo body regeneration

The body template lives in `actions/ship.py:_render_body(feature_lane, repo, all_pr_numbers)`. Test it as a pure function — given a fixture lane + dict of pr_numbers, snapshot the rendered markdown.

### T5 — Docs + skills

- `docs/commands.md` — `ship` section with example invocation + sample output.
- `docs/agents.md` — full workflow recipe (preflight → commit → push → ship; what each step adds).
- Skill files — `ship` listed as the preferred way to open PRs across canopy features.

---

## Edge cases to remember

- **Single-repo features.** Cross-repo link section in body collapses to "1 of 1 repos" — still useful as scaffolding.
- **PR exists but for a different branch.** Shouldn't happen if branches are unique per feature, but if user manually opened a PR for `feature-name` from a different fork or branch, treat as `diverged` and warn.
- **Reviewers don't exist.** `gh pr create --reviewer nobody` errors. Surface verbatim; don't drop reviewers silently.
- **Drafts.** `--draft` flag on first ship; subsequent ships don't auto-undraft. Use `gh pr ready` (or future `canopy ship --ready`) for that — out of scope here.
- **Network failures mid-pass.** If 2 of 3 PRs open and the 3rd network-fails, return a partial result. The user can re-run `ship` and the 2 already-open PRs return `up_to_date` while the 3rd retries. Idempotent.

---

## Out of scope

- Auto-merging PRs after CI passes. Use `gh pr merge --auto` or a CI bot.
- Reviewer assignment by team / CODEOWNERS. Reviewers come from `--reviewers` flag only.
- Updating PR title after first ship. Title is set once; user edits manually if they change the feature name.
- Shipping non-canopy features (random branches the user just created). `ship` operates only on canopy-tracked features.

---

## After this lands

- The CLI workflow is end-to-end: `switch X` → edit → `preflight` → `commit -m` → `push` → `ship` → wait for review → repeat.
- The dashboard's review section auto-detects the new PRs (existing `reviewStatus` watches GitHub).
- The action drawer (Plan 5) gets a "Ship feature" button — even though it's not in the current mockup, it's the logical capstone.
- The agent's `using-canopy` skill recipe collapses from a 5-step "use these MCP tools in this order" to a 2-step "commit + ship."
