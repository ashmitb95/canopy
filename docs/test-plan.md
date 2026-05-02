# Canopy — Manual Integration Test Plan

**Workspace under test:** `~/projects/canopy-test` (2 repos: `canopy-test-api`, `canopy-test-ui`; both backed by GitHub remotes; MCP wired for canopy + Linear).

**Purpose:** validate every shipped milestone (M0–M5) end-to-end against a real workspace — the unit suite proves modules; this proves the integrated product. Walk through once after each milestone; re-run before each release.

**Format:** every check has *steps* (concrete commands), *expected* (what passes), and a *status* slot (`[ ]` → `[✓]`/`[✗]`). Skip with `[~]` and a one-line reason.

---

## 0. Pre-conditions

Run these before anything else. Fail any of these → stop and fix install before testing milestones.

| # | Check | Steps | Expected |
|---|---|---|---|
| 0.1 | Canopy CLI on PATH | `canopy --version` | Prints a version (e.g. `0.5.0`); no `command not found` |
| 0.2 | MCP entry registered | `cat ~/projects/canopy-test/.mcp.json` | Has a `canopy` server with `CANOPY_ROOT=/Users/ashmit/projects/canopy-test` |
| 0.3 | `gh` authenticated | `gh auth status` | "Logged in to github.com" |
| 0.4 | Linear MCP available | `cat ~/projects/canopy-test/.canopy/mcps.json` | Linear entry present |
| 0.5 | Workspace parses | `cd ~/projects/canopy-test && canopy state --json \| head -5` | Returns JSON, not an exception |

Status: `[ ]` `[ ]` `[ ]` `[ ]` `[ ]`

---

## 1. M1 — `canopy doctor` (17 categories + version handshake)

| # | Check | Steps | Expected |
|---|---|---|---|
| 1.1 | Doctor runs clean | `cd ~/projects/canopy-test && canopy doctor --json` | `summary.errors == 0` (or only known/expected ones). Categories cover state, install, mcp, skill, vsix. |
| 1.2 | Detects state drift | `mv ~/projects/canopy-test/.canopy/state/heads.json /tmp/heads-bak.json && canopy doctor` | Reports `heads_missing` (or similar). Restore: `mv /tmp/heads-bak.json ~/projects/canopy-test/.canopy/state/heads.json`. |
| 1.3 | Auto-fix recovers | repeat 1.2 then `canopy doctor --fix` | The missing-state issue gets `auto_fixable: true` and is repaired. |
| 1.4 | Version handshake | `canopy --version` and `python -c "from canopy.mcp.server import version; print(version())"` | Both report the same `cli_version` / `mcp_version` / `schema_version`. |
| 1.5 | Skill install report | `canopy setup-agent --check --json` | Skill `installed: true`, `is_canopy_skill: true`, `up_to_date: true`. |

Status: `[ ]` `[ ]` `[ ]` `[ ]` `[ ]`

---

## 2. M5 — Issue providers (Linear + GitHub Issues)

### 2a. Linear backend (default — current canopy-test config)

| # | Check | Steps | Expected |
|---|---|---|---|
| 2.1 | List my Linear issues | `cd ~/projects/canopy-test && canopy issues --json` (MCP variant: `issue_list_my_issues`) | Returns ≥1 issue if any are assigned to you; else `[]`. Each has `id`, `identifier` (e.g. `SIN-7`), `title`, `state`. |
| 2.2 | Fetch a known Linear issue | `canopy issue SIN-5 --json` (MCP: `issue_get(alias="SIN-5")`) | Returns `{identifier: "SIN-5", title, state, url, ...}`. State maps to canonical (`todo` / `in_progress` / `done`). |
| 2.3 | Backward-compat alias | `mcp__canopy__linear_get_issue(alias="SIN-5")` | Same response as 2.2; deprecation note in logs. |
| 2.4 | Per-feature alias resolves | `canopy state SIN-7 --json \| head -20` | Resolves `SIN-7` → `sin-7-empty-state`; returns its state machine entry. |

Status: `[ ]` `[ ]` `[ ]` `[ ]`

### 2b. GitHub Issues backend (one-off swap)

| # | Check | Steps | Expected |
|---|---|---|---|
| 2.5 | Switch provider | Edit `canopy-test/canopy.toml`, add `[issue_provider]\nname = "github_issues"\n\n[issue_provider.github_issues]\nrepo = "ashmitb95/canopy-test-api"`. Then `canopy issues --json`. | Returns issues from the GitHub repo (or `[]` if none open). Provider switch with no canopy restart. |
| 2.6 | Fetch GitHub issue | Create or pick a GitHub issue: `gh issue create --repo ashmitb95/canopy-test-api --title "test" --body ""`. Then `canopy issue <num> --json`. | Returns the issue normalized to the same `Issue` shape (no Linear-specific fields leaked). |
| 2.7 | Restore Linear | Remove the `[issue_provider]` block from canopy.toml. `canopy issues --json` falls back to Linear. | No errors; Linear issues again. |

Status: `[ ]` `[ ]` `[ ]`

---

## 3. M2 — Augments (per-workspace customization)

| # | Check | Steps | Expected |
|---|---|---|---|
| 3.1 | Empty augments → default preflight | `canopy preflight --json` (in canopy-test root) | Existing pre-commit auto-detection runs; result has `applied_augment: false`. |
| 3.2 | Workspace `preflight_cmd` runs | Edit canopy.toml, add `[augments]\npreflight_cmd = "echo OK && exit 0"`. `canopy preflight --json`. | Output includes `applied_augment: true`, `passed: true`, `command: "echo OK && exit 0"`. |
| 3.3 | Per-repo override | Add `augments = { preflight_cmd = "echo TEST-API && exit 0" }` to the `test-api` `[[repos]]` block. `canopy preflight --json`. | `test-api` runs the override; `test-ui` uses workspace default. |
| 3.4 | Augment skill installs | `canopy setup-agent --skill augment-canopy --check` then `canopy setup-agent --skill augment-canopy` | Reports installed at `~/.claude/skills/augment-canopy/SKILL.md`. |
| 3.5 | Bad command surfaces in result | Set `preflight_cmd = "exit 1"`. Run preflight. | `passed: false`, `applied_augment: true`. No crash. |
| 3.6 | Cleanup | Remove the `[augments]` block + per-repo augments | preflight returns to auto-detect (`applied_augment: false`). |

Status: `[ ]` `[ ]` `[ ]` `[ ]` `[ ]` `[ ]`

---

## 4. M3 — Bot-comment tracking

**Setup (~10 min, one-time):** install CodeRabbit (or similar bot) on `canopy-test-api`. Open a small PR with a deliberate code-quality issue (unused import, magic number). Wait for the bot to comment. Note the comment ID from the GitHub URL.

| # | Check | Steps | Expected |
|---|---|---|---|
| 4.1 | Comment id surfaces | `canopy review <feature> --comments-only --json` | Each comment has an `id` field (M3 added; should be a non-zero integer). |
| 4.2 | Bot vs human split | `canopy state <feature-with-bot-pr> --json` | `summary.actionable_bot_count >= 1`, `summary.actionable_human_count == 0` (assuming no human reviewers). |
| 4.3 | New state surfaces | Same as 4.2 | `state == "awaiting_bot_resolution"`; `next_actions[0].action == "address_bot_comments"`. |
| 4.4 | `bot-status` rollup | `canopy bot-status --feature <f> --json` | Returns `{repos: {test-api: {pr_number, total: ≥1, resolved: 0, unresolved: ≥1, threads: [...]}}, all_resolved: false}`. Each thread has `id`, `author`, `path`, `body_preview`. |
| 4.5 | `--unresolved-only` filter | `canopy bot-status --feature <f> --unresolved-only --json` | Only unresolved threads listed. |
| 4.6 | `commit --address` (numeric id) | Make a small fix in the repo. `canopy commit --address <comment-id> -m "rename"` | Per-repo result `ok` for the matching repo. Top-level `addressed: {comment_id, repo, sha, recorded: true, ...}`. Commit message in git includes `Addresses bot comment: "<title>" (<url>)`. |
| 4.7 | Resolution persisted | `cat ~/projects/canopy-test/.canopy/state/bot_resolutions.json` | Has `{<id>: {feature, repo, commit_sha, ...}}`. |
| 4.8 | `commit --address` (URL form) | Same as 4.6 but pass full GitHub URL as the address | Same behavior; URL parsed to numeric id. |
| 4.9 | Resolved subtracts from count | `canopy state <feature> --json` after 4.6 | `actionable_bot_count` decreased by 1. State drops out of `awaiting_bot_resolution` if it was the last one. |
| 4.10 | Augment-narrowed bots | Add `[augments] review_bots = ["coderabbit"]` to canopy.toml. Re-run `bot-status`. | Same coverage if author is CodeRabbit; non-matching bot accounts (e.g. `dependabot`) drop into the human bucket. |
| 4.11 | Unknown id rejected | `canopy commit --address 999999 -m "x"` (id not in PR) | Errors with `BlockerError(code='not_a_bot_comment')`; no commit fires. |
| 4.12 | Approved + bot threads | If a reviewer approves the PR while bot comments remain: `canopy state` | State stays `approved`, `next_actions[0]` is `merge`, `next_actions[1]` is `address_bot_comments` (secondary CTA). |

Status: `[ ]` × 12

---

## 5. M4 — Historian (cross-session memory)

| # | Check | Steps | Expected |
|---|---|---|---|
| 5.1 | Empty memory on switch | `canopy switch sin-7-empty-state --json` (assuming no historian entries yet) | Response includes `memory: ""`. |
| 5.2 | Record a decision | Via MCP: `mcp__canopy__historian_decide(feature="sin-7-empty-state", decisions=[{"title": "use empty-state SVG from design system", "rationale": "matches existing 404 page"}])` | Returns `{action: "recorded", title: ...}`. File created at `~/projects/canopy-test/.canopy/memory/sin-7-empty-state.jsonl` + `.md`. |
| 5.3 | Decision dedup | Same call again | Returns `{action: "deduped"}`. Only one entry in the JSONL. |
| 5.4 | Pause | `mcp__canopy__historian_pause(feature="sin-7-empty-state", reason="blocked on design-system copy")` | Recorded; appears in Sessions section of the rendered .md. |
| 5.5 | Memory included on switch | `canopy switch sin-6-cache-stats` then `canopy switch sin-7-empty-state` | Second switch's response `memory` field contains the markdown with the decision + pause. |
| 5.6 | CLI inspection | `canopy historian show sin-7-empty-state` | Prints the rendered markdown — header, all 3 sections (resolutions/PR/sessions), placeholders for empty sections. |
| 5.7 | Auto-mirror from `commit --address` | After running 4.6, `canopy historian show <feature>` | "Resolutions log" section has the resolved comment (✓ glyph, sha, gist). |
| 5.8 | Auto-mirror from `review_comments` | After running 4.1, `canopy historian show <feature>` | Sessions section has `read comment <id>` entries; if classifier marked threads, also `classifier marked N thread(s) likely-resolved`. |
| 5.9 | Compact (within limit) | `canopy historian compact sin-7-empty-state --keep-sessions 5` | `action: "noop"` (only 1 session so far). |
| 5.10 | Compact (forces drop) | Force multiple sessions: `CANOPY_SESSION_ID=s-1 canopy historian show ...` won't help; instead, in MCP: call `historian_decide` with several sessions in JSONL by hand or wait until natural sessions accumulate. Then `canopy historian compact <f> --keep-sessions 2`. | Drops oldest session entries; preserves resolutions log + PR context. |
| 5.11 | `.gitignore` written | `cat ~/projects/canopy-test/.canopy/memory/.gitignore` | Contains `*` and `!.gitignore` so memory files don't get committed. |

Status: `[ ]` × 11

---

## 6. `canopy switch` — canonical-slot focus primitive

Switch is the primitive every other action depends on. It moves features between {canonical, warm, cold} states; the cap (`max_worktrees`, default 2) protects against unbounded warm-tree growth.

| # | Check | Steps | Expected |
|---|---|---|---|
| 6.1 | switch by feature name | `cd canopy-test && canopy switch sin-7-empty-state --json` | `feature: sin-7-empty-state`, `mode: active_rotation` (or `wind_down`); `per_repo_paths` populated; `memory` field present (M4). Previously canonical evacuates to warm. |
| 6.2 | switch by Linear ID alias | `canopy switch SIN-6 --json` | Resolves to `sin-6-cache-stats`; same response shape. |
| 6.3 | active_feature.json updated | `cat .canopy/state/active_feature.json` after 6.2 | `feature == "sin-6-cache-stats"`; `last_touched` map updated. |
| 6.4 | switch with --release-current (wind-down) | `canopy switch sin-7-empty-state --release-current --json` | Previously-canonical (sin-6) goes cold (no warm worktree, may have feature-tagged stash if dirty); `evacuation` field absent. |
| 6.5 | switch back uses warm | After 6.1/6.2 with active rotation: `canopy switch <previously-canonical>` | Fast (≤500 ms typical); reads from existing warm worktree. |
| 6.6 | switch fresh feature creates branches | `canopy switch SIN-9 --json` (assumes no `sin-9-*` lane exists) | Creates branches from default per repo; `branches_created` populated in response. |

Status: `[ ]` × 6

---

## 7. The 9-state machine — all transitions reachable

`feature_state` is the dashboard backend. Every state should be reachable through the right preconditions; this exercises each branch of `_decide_state`.

| # | State | How to reach | Check |
|---|---|---|---|
| 7.1 | `drifted` | Manual `git checkout main` in one feature repo | `canopy state <f>` returns `drifted`; primary action is `switch` (post-F-12 — was `realign` pre-fix). |
| 7.2 | `in_progress` | Switch to feature, edit a file, no preflight | `state == "in_progress"`; primary action `preflight`. |
| 7.3 | `ready_to_commit` | After 7.2: run `canopy preflight` (passes) | `state == "ready_to_commit"`; primary `commit`. |
| 7.4 | `ready_to_push` | After 7.3: `canopy commit -m "..."` | `state == "ready_to_push"`; primary `push`. |
| 7.5 | `awaiting_review` | After 7.4: `canopy push --set-upstream` + open PR | `state == "awaiting_review"`; primary `refresh`. |
| 7.6 | `approved` | Manually mark PR APPROVED on GitHub | `state == "approved"`; primary `merge`. |
| 7.7 | `awaiting_bot_resolution` | (M3) PR with only bot comments, no human action | covered by §4 — blocked on CodeRabbit. |
| 7.8 | `needs_work` | Reviewer requests changes OR ≥1 actionable human comment | `state == "needs_work"`; primary `address_review_comments`. |
| 7.9 | `no_prs` | New feature, clean tree, no PR yet | `state == "no_prs"`; primary `pr_create`. |

Status: `[ ]` × 9

---

## 8. `canopy commit` + `canopy push` lifecycle (Wave 2.3)

| # | Check | Steps | Expected |
|---|---|---|---|
| 8.1 | commit with no message blocks | `canopy commit` (no `-m`) | `BlockerError(code='empty_message')`; exit 1; nothing commits. |
| 8.2 | commit succeeds across all repos in lane | Switch to a multi-repo feature; edit one file in each; `canopy commit -m "test"` | Per-repo result `ok` for each; SHAs returned; `files_changed: 1` per repo. |
| 8.3 | commit blocks on wrong_branch | Manually checkout a different branch in one repo, then `canopy commit -m "x"` | `BlockerError(code='wrong_branch')`; per-repo `expected`/`actual` map; **no repo commits** (atomic pre-flight). |
| 8.4 | commit per-repo subset | `canopy commit --repo test-api -m "..."` | Only `test-api` commits; `test-ui` not in results. |
| 8.5 | commit with bad path filter | `canopy commit --paths nonexistent.txt -m "..."` | `failed` status — `git add nonexistent.txt` errors fatally; canopy surfaces the git error in `reason`. (Soft-failing would mask user typos; verified intentional.) |
| 8.6 | push with no upstream blocks | First push of a fresh branch: `canopy push` | `BlockerError(code='no_upstream')`; fix-action carries `--set-upstream`. |
| 8.7 | push with --set-upstream succeeds | `canopy push --set-upstream` | Per-repo result `ok`; remote branch created. |
| 8.8 | push when nothing to push | Re-run `canopy push` after 8.7 | `up_to_date` status per repo; no error. |

Status: `[ ]` × 8

---

## 9. Drift detection + recovery

The hook + `heads.json` give us cached drift detection; live `feature_state` is the source of truth. Both should agree, and `switch` should recover from any induced drift.

| # | Check | Steps | Expected |
|---|---|---|---|
| 9.1 | Live drift detection | Switch to a multi-repo feature; manually `git checkout main` in one repo. `canopy state <f>` | `state == "drifted"`; `repos.<repo>.is_drifted` or similar marker. |
| 9.2 | `canopy drift` cached path | After 9.1, `canopy drift --json` | Reports the same drift. (Cached path uses `heads.json` — should still see it after the post-checkout hook fires.) |
| 9.3 | switch recovers | `canopy switch <f>` after 9.1 | All repos back on the feature branch; `state == ...` (in_progress / no_prs / etc., not `drifted`). |
| 9.4 | drift survives doctor scan | `canopy doctor` while drifted | Reports `heads_stale` for the repo (live HEAD ≠ heads.json); `auto_fixable: true`. |

Status: `[ ]` × 4

---

## 10. Universal aliases — every read tool agrees on shape

Aliases were rewritten in PR #19 to be provider-aware. Verify the alias surface is consistent across CLI commands.

| # | Alias form | Expected behaviour across `state`, `comments`, `branch`, `issue` |
|---|---|---|
| 10.1 | Feature name (`sin-7-empty-state`) | All resolve to the same feature; same `feature` field. |
| 10.2 | Linear ID (`SIN-7`) | Resolves to `sin-7-empty-state` via `linear_issue` field. |
| 10.3 | `<repo>#<n>` for PR commands | `canopy pr test-api#1` and `canopy comments test-api#1` work. |
| 10.4 | PR URL | `canopy pr 'https://github.com/o/r/pull/1'` works. |
| 10.5 | Bare GH issue # (with provider swapped) | Per F-7 fix: `canopy issue 5` works when `[issue_provider] = github_issues`. |
| 10.6 | Unknown alias | Surfaces `BlockerError(code='unknown_alias')` with `expected.explicit_features` listing real lanes. |

Status: `[ ]` × 6

---

## 11. Feature-tagged stash family

Stash should be feature-aware: tagged on save, groupable on list, restorable on pop.

| # | Check | Steps | Expected |
|---|---|---|---|
| 11.1 | save with --feature tags the stash | Edit a file; `canopy stash save --feature <feature> -m "wip auth"` | Stash entry created; `git stash list` shows `[canopy <feature> @ <ts>] wip auth`. (Note: feature variants live behind the `--feature` flag, not as separate subcommands.) |
| 11.2 | list with --feature clusters by feature | `canopy stash list --feature <feature> --json` | Returns `{by_feature: {<feature>: [{repo, index, ref, message, feature, ts, user_message}]}, untagged: [...]}`. |
| 11.3 | pop with --feature restores | Switch to clean state; `canopy stash pop --feature <feature>` | Latest stash for that feature applied; working tree dirty again. |
| 11.4 | save without --feature is plain stash | `canopy stash save -m "plain"` | Stash created but appears under `untagged` in `list --feature` output. |
| 11.5 | drop removes a stash | `canopy stash drop --index 0` | Removed; `git stash list` confirms. |

Status: `[ ]` × 5

---

## 12. `canopy doctor --fix` (close M1's repair loop)

Run §1.1 already exercised the *detection* side. This section validates the *repair* side end-to-end against canopy-test's real drift (8 issues found in Run 1).

| # | Check | Steps | Expected |
|---|---|---|---|
| 12.1 | Auto-fixable issues exist | `canopy doctor --json` | `summary.errors > 0` OR `summary.warnings > 0` with `auto_fixable: true`. |
| 12.2 | `--fix` repairs heads_stale | `canopy doctor --fix --json` (no `--clean-vsix`) | `fixed[]` includes `heads_stale` entries with `success: true`. Re-run shows them gone. |
| 12.3 | `--fix` repairs worktree_missing | Same `--fix` run | `worktree_missing` entries either `success: true` (worktree recreated) or `success: false` with a clear `error`. |
| 12.4 | `--clean-vsix` opt-in | `canopy doctor --fix --clean-vsix --json` | Removes all but newest `singularityinc.canopy-*` extension dirs. (Verify with `ls ~/.vscode/extensions/`.) |
| 12.5 | `mcp_orphans` repair (F-3) | If any orphans present, `canopy doctor --fix --json` | `fixed[]` includes `mcp_orphans` with `success: true`; PIDs killed. |
| 12.6 | category filter | `canopy doctor --fix --fix-category heads --json` | Only `heads_stale` repaired; other auto-fixable issues stay. (Flag is `--fix-category <name>`, not `--fix=<name>`.) |

Status: `[ ]` × 6

---

## 13. End-to-end scenario (composite)

One realistic feature lifecycle that exercises every shipped milestone in sequence. Plan ~30 minutes.

```bash
# Fresh start: pick a feature that doesn't exist yet
cd ~/projects/canopy-test

# 1. Verify clean install (M1)
canopy doctor

# 2. Configure: add augments + (optionally) GitHub Issues (M2 + M5)
# Edit canopy.toml:
#   [augments]
#   preflight_cmd = "echo OK && exit 0"
#   review_bots = ["coderabbit"]

# 3. Pick up a Linear issue → switch (M5 + canonical-slot model)
canopy switch SIN-8   # promotes sin-8-stale-count to canonical
# Response: includes memory: "" on first switch (M4)

# 4. Make a change in test-api
echo "# stale count fix" >> canopy-test-api/src/example.py

# 5. Preflight runs the augment (M2)
canopy preflight   # → "applied_augment: true"

# 6. Commit (Wave 2.3)
canopy commit -m "fix: stale count edge"

# 7. Record a decision (M4)
# Via MCP: historian_decide(feature="sin-8-stale-count",
#   decisions=[{"title": "compute stale count from cache TTL",
#               "rationale": "avoids extra DB call on hot path"}])

# 8. Push (Wave 2.3)
canopy push --set-upstream

# 9. Open PR via gh; wait for CodeRabbit
gh pr create --repo ashmitb95/canopy-test-api --title "..." --body ""

# 10. After bot comments arrive: state machine surfaces awaiting_bot_resolution (M3)
canopy state SIN-8

# 11. Address bot comment (M3 + M4 mirror)
canopy commit --address <id> -m "rename per coderabbit"

# 12. Switch away then back — verify memory carries the narrative (M4)
canopy switch sin-7-empty-state
canopy switch SIN-8
# Response.memory shows: decision, the resolved comment, the recorded session

# 13. Doctor still clean (M1)
canopy doctor
```

**Pass criteria:** every step completes without unexpected errors; the state machine transitions match the 9-state diagram in [concepts.md](concepts.md); `historian show SIN-8` at the end has a non-trivial Resolutions log + Sessions narrative.

---

## 14. Known unverifiable / deferred

These are intentionally not testable in v1 — note them but skip:

| Capability | Why skipped now | Lands when |
|---|---|---|
| Auto-capture of generic Bash/Edit events into historian | PostToolUse hook (autopilot) deferred | Autopilot hook bundle ships |
| Stop-hook tail-parse of `<historian-decisions>` | Stop hook (autopilot) deferred | Autopilot hook bundle ships |
| LLM compaction in `historian_compact` | Mechanical-only in v1 by design | Future LLM pass; storage shape forward-compatible |
| `canopy ship` end-to-end (commit + push + PR) | M8 not shipped | After Phil's `pr_target` + M8 |
| Per-repo PR target | M8 / Phil's branch | After Phil's PR |
| Local-package symlinking on switch | Phil's branch | After Phil's PR |
| Extension dashboard (action drawer) | M11 + Phil's extension rewrite | After both land |
| Sidebar single-tree | M7 / Phil's extension rewrite | After Phil's rewrite |

---

## 15. After running this plan

1. **Record results** — fill in checkboxes in this file and commit (or paste the diff in a session note).
2. **Triage failures** — each `[✗]` becomes either a bug fix (file an issue), a docs gap (clarify in the relevant SKILL.md / concepts.md), or a known limitation (move into §7).
3. **Repeat per release** — re-run §0–§5 before each version bump; full §6 e2e at major milestones.

The first full pass is the high-value one — it turns "we shipped a lot of unit-tested code" into "we shipped a working product."
