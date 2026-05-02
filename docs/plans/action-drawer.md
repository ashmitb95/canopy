# Action Drawer — Per-Feature Dashboard Rebuild to Mockup Spec

## Mental model

The current per-feature dashboard (post-Wave 7 phase I) is a single-column webview with four cards: Branches, Linear, Review, Recent commits. The mockup at `vscode-extension/mockups/action-drawer.html` calls for something fundamentally different: a **3-column dashboard** with a 360px right rail (the "action drawer") containing a state summary table and 5 grouped action sections (~16 actions total).

This plan rebuilds the dashboard to match the mockup. It's not a polish pass — the layout, the content surface, and the action set all change.

**This plan assumes prerequisite backends are done:**
- Wave 2.3 (`commit` + `push`) — see `2026-04-26-canopy-wave-2-3-commit-push.md`
- Wave 4 (`draft_replies`) — see `2026-04-26-canopy-wave-4-draft-replies.md`
- Wave 2.4 (`ship`) — see `2026-04-26-canopy-wave-2-4-ship.md` (optional but unlocks the "Ship feature" capstone action)

If a backend isn't ready when this plan executes, that action button gets dropped from the drawer for the initial release — `git grep "WAVE-2-3-DEP" src/canopy/` etc. to find tagged blocks.

---

## Layout spec (from mockup)

```
┌────────────────────────────────────────────────────────────────────────┐
│ BRIDGE  compass · workspace ~/projects/canopy · lamps · theme toggle   │
├──────────────────────────────────────┬─────────────────────────────────┤
│                                      │                                 │
│   CENTER PANE                        │   RIGHT RAIL (360px)            │
│                                      │                                 │
│   Breadcrumb · Dashboard · SIN-12    │   ┌───────────────────────────┐ │
│                                      │   │ AVAILABLE ACTIONS         │ │
│   ● SIN-12-search                    │   │ sin-12-search             │ │
│   "Add /search endpoint…"            │   ├───────────────────────────┤ │
│   [in main] [needs work] SIN-12 ↗    │   │ STATE     │ in_progress   │ │
│   last touched 12m ago               │   │ SLOT      │ canonical     │ │
│                                      │   │ DIRTY     │ 3 files       │ │
│   ┌────────────┐ ┌────────────┐      │   │ UNPUSHED  │ 2 commits     │ │
│   │ backend    │ │ frontend   │      │   │ PRs       │ 2 open        │ │
│   │ branch:    │ │ branch:    │      │   │ ACTIONABLE│ 3 threads     │ │
│   │ SIN-12-…   │ │ SIN-12-…   │      │   │ PREFLIGHT │ ✓ green       │ │
│   │ 3 dirty    │ │ 1 dirty    │      │   ├───────────────────────────┤ │
│   │ 2 actionbl │ │ 1 actionbl │      │   │ REVIEW                    │ │
│   │ PR #142 ↗  │ │ PR #58 ↗   │      │   │  ▶ Address comments…  ★   │ │
│   └────────────┘ └────────────┘      │   │  ▶ Draft replies          │ │
│                                      │   │  ▶ Defer all              │ │
│   ACTIONABLE THREADS (3)             │   ├───────────────────────────┤ │
│   ┌──────────────────────────────┐   │   │ WRITE                     │ │
│   │ backend · src/api/search.py  │   │   │  ▶ Run preflight          │ │
│   │ alice · 2h ago               │   │   │  ▶ Commit + push          │ │
│   │ "rename foo to bar"          │   │   │  ▶ Stash dirty work       │ │
│   │ [Jump] [Reply] [Done] [Defer]│   │   ├───────────────────────────┤ │
│   └──────────────────────────────┘   │   │ SLOT                      │ │
│   ... 2 more threads                  │   │  ▶ Move to a worktree     │ │
│                                      │   │  ▶ Hibernate              │ │
│                                      │   │  ▶ Add docs to lane       │ │
│                                      │   │  ▶ Remove repo from lane  │ │
│                                      │   ├───────────────────────────┤ │
│                                      │   │ INSPECT                   │ │
│                                      │   │  ▶ Open in IDE            │ │
│                                      │   │  ▶ View full diff vs main │ │
│                                      │   │  ▶ Show resolved threads  │ │
│                                      │   ├───────────────────────────┤ │
│                                      │   │ CONFIGURE                 │ │
│                                      │   │  ▶ Re-link Linear issue   │ │
│                                      │   │  ▶ Done — archive lane ⚠  │ │
│                                      │   └───────────────────────────┘ │
└──────────────────────────────────────┴─────────────────────────────────┘
```

**Grid:** `grid-template-columns: 1fr 360px`. Right rail fixed width, scrollable. Center pane scrollable independently. Both share the bridge header.

**Theme:** navy (primary) + minimal (alt). Colors per the existing `themes/types.ts` token set (extended with `--bot`, `--on-station`, `--hot` if not present).

---

## Action wiring matrix

Every action div in the drawer posts a typed message to the extension; the extension calls the corresponding MCP tool. Most map 1:1.

| Group | Action label | postMessage type | MCP call | Notes |
|---|---|---|---|---|
| Review | Address comments in Claude *(★ recommended when actionable > 0)* | `addressInClaude` | `linear_get_issue` + `review_comments` → build prompt → launch Claude Code via existing `launchClaudeWorkflow` URI | Already partial; finalize the prompt template |
| Review | Draft replies for addressed threads | `draftReplies` | `draft_replies(feature)` (Wave 4) | Open results in a quick-pick or modal; user posts via `gh pr comment` (manual for v1) |
| Review | Defer all | `deferAll` | (none — local state) | Write `{<feature>: deferred_until}` to `.canopy/state/deferred.json`; dashboard hides the threads section for 24h |
| Write | Run preflight | `runPreflight` | `preflight()` | Already wired in current dashboard |
| Write | Commit + push | `commitAndPush` | `commit(message)` then `push()` (both Wave 2.3) | Quick-pick first asks for commit message; on success show toast |
| Write | Stash dirty work | `stashDirty` | `stash_save_feature(feature)` | Already wired in canopyClient as `client.stashSaveFeature` |
| Slot | Move to a worktree | `moveToWorktree` | `switch(feature)` (active rotation default) | When canonical is X, "switch to Y" creates Y's worktree if needed; reuse existing |
| Slot | Hibernate (branch only) | `hibernate` | `switch(<some-other-feature>, release_current=true)` | Caller picks which feature becomes canonical; if no obvious choice, prompt |
| Slot | Add docs to lane | `addDocsToLane` | `worktree_create(feature, repo='docs')` | Requires `docs` to be a known repo in workspace |
| Slot | Remove repo from lane | `removeRepoFromLane` | `feature_remove_repo(feature, repo)` | **No backend exists.** Tag with `WAVE-FUTURE-DEP`; hide button if tool not registered. |
| Inspect | Open in IDE | `openInIde` | `feature_paths(feature)` then `vscode.openFolder` per path | Reuse the existing `canopy.openInIde` command |
| Inspect | View full diff vs main | `viewDiff` | `feature_diff(feature)` | Already wired; render in a new webview panel |
| Inspect | Show likely-resolved threads | `showResolvedThreads` | `review_comments(feature, include_resolved=true)` | Toggle in-place; today's `review_filter` already classifies; expose the secondary list |
| Configure | Re-link Linear issue | `relinkLinear` | `linear_my_issues(50)` → user picks → `feature_link_linear(feature, issue)` | Same flow as today's "Pick from my Linear issues" but allow change-not-just-add |
| Configure | Done — archive lane | `featureDone` | `feature_done(feature)` | Existing; add a confirmation modal because of red highlight |

---

## Files to touch

### New

- `vscode-extension/src/webview/dashboard/` — split the existing single-file dashboard into a folder. Each section becomes its own renderer:
  - `index.ts` — exports `DashboardPanel` (the panel class itself; cache + lifecycle stays here)
  - `shell.ts` — base HTML + CSS (extracted from current `baseHtml`)
  - `bridge.ts` — bridge header renderer
  - `header.ts` — feature title + badges (refactored from current `renderHeader`)
  - `repoCards.ts` — center pane repo grid (NEW)
  - `threads.ts` — center pane threads list (NEW)
  - `drawer.ts` — right rail renderer: summary table + 5 action groups (NEW; bulk of new code)
  - `skeletons.ts` — extracted skeleton helpers
- `vscode-extension/src/webview/dashboard/themes.css` — extracted CSS, with both navy + minimal token sets

### Modified / replaced

- `vscode-extension/src/webview/dashboardPanel.ts` — slim to a re-export of `./dashboard/index.ts` (or delete and update extension.ts imports). Keeps the public surface stable for `extension.ts`.
- `vscode-extension/src/canopyClient.ts` — add the few missing client methods:
  - `commit(message, opts)` — wraps `commit` MCP tool (Wave 2.3)
  - `push(opts)` — wraps `push` MCP tool (Wave 2.3)
  - `draftReplies(feature)` — wraps `draft_replies` (Wave 4)
  - `featureRemoveRepo(feature, repo)` — wraps `feature_remove_repo` (FUTURE; behind a try/catch + hide-button-on-missing-tool fallback)
- `vscode-extension/src/types.ts` — add the new return types for the new client methods.
- `vscode-extension/package.json` — bump version (probably `0.5.0` for layout-rewrite scope).
- `vscode-extension/src/extension.ts` — no changes if `DashboardPanel` re-exports cleanly; otherwise update import path.

---

## Tasks (rough sequence)

### T1 — Restructure: dashboard folder + extract existing renderers

Move the current dashboardPanel.ts content into the new folder structure. Each existing function becomes its own file with the same exported signature. Verify the dashboard still renders identically afterwards (no behavior change yet).

Commits at this stage: structural only, behavior unchanged.

### T2 — Bridge header + 3-column shell

Build `bridge.ts` (compass icon, workspace path, theme toggle, status lamps). Update `shell.ts` to use the new `grid-template-columns: 1fr 360px` layout. Stub `drawer.ts` and `threads.ts` as empty divs so the layout can be inspected before content fills in.

Visual check: dashboard now has the bridge header + a 360px right column placeholder.

### T3 — Repo grid in center pane

Build `repoCards.ts`. For each repo in `lane.repo_states`, render a card showing: branch name, dirty count, actionable count (from `review_comments` joined to repo), PR link, path. Replace the current "Branches" card with this grid.

Data sources: existing `lane` (already cached in DashboardPanel), `comments` (already cached). New computation: per-repo `actionable_count = comments.repos[repo].comments.length`.

### T4 — Threads list in center pane

Build `threads.ts`. Render unresolved comments as cards: repo tag, file:line link (clickable → `vscode.open`), author, age, body, 4 action buttons (Jump / Reply / Done / Defer). For v1, "Reply" / "Done" / "Defer" are stubs that show a toast — wired up to backends in T8 alongside drawer actions.

Use the existing `comments` data already in cache. Sort by repo, then by age.

### T5 — Right rail: summary table

Build the 7-row state summary in `drawer.ts`. Data sources:
- STATE: `feature_state(feature).state` (use existing client.featureState)
- SLOT: derived from worktree presence (canonical = no worktree path; warm = has worktree)
- DIRTY: sum of `lane.repo_states[*].changed_file_count`
- UNPUSHED: sum of `lane.repo_states[*].ahead`
- PRs: count of `status.repos[*].pr` non-null
- ACTIONABLE: sum of `comments.repos[*].comments.length`
- PREFLIGHT: from `lastPreflight` if set, else "—"

All values render from cached data — no extra fetches.

### T6 — Right rail: action groups (static layout)

Build the 5 action groups in `drawer.ts` as static HTML — every action is a clickable div with `data-action="<message-type>"`. No wiring yet — clicking does nothing. Recommended action (★) gets the `recommended` class.

Visual check at this point: drawer renders with all actions visible, all clickable but no-op.

### T7 — Action wiring (per matrix above)

For each row in the action wiring matrix, add the corresponding `case "<message-type>":` to `DashboardPanel.onDidReceiveMessage`. Most are 1-2 lines (delegate to existing client method + invalidate cache + refresh).

The interesting handlers:
- **commitAndPush** — show input box for message, then sequential `commit(msg)` → `push()`, surface combined per-repo summary in a toast.
- **draftReplies** — call `draft_replies`, render results in a quick-pick that lets the user copy each draft to clipboard. (Posting via `gh` is out of scope for v1.)
- **deferAll** — write to `.canopy/state/deferred.json`; refresh hides the threads section if `deferred_until > now`.
- **showResolvedThreads** — toggle a class on the threads section that reveals the secondary `likely_resolved` list. Data already in `comments` cache.

Each action that mutates state calls `forceRefresh()` on the panel afterwards (existing method) so the summary table reflects the change.

### T8 — Recommended-action logic

Surface the ★ on the Review group's first action when `actionable_count > 0`. Add similar logic for "Run preflight" when `dirty_count > 0` and no recent preflight, and "Commit + push" when `dirty_count == 0 && unpushed > 0`. Only one ★ at a time — the most-blocking action wins.

### T9 — Theme parity

Extract the navy palette into `themes.css` as CSS variables. Add the minimal palette as a `[data-theme="minimal"]` selector. Reuse the existing theme-name reader (`readThemeName()` from cockpitPanel.ts).

### T10 — Build, package, install, smoke test

Run through the action checklist manually. Each action should either: succeed and refresh the summary, or fail with a useful toast. No silent failures.

### T11 — Docs

Update `vscode-extension/README.md` (if present) with the new dashboard screenshot. Update `~/.claude/skills/using-canopy/SKILL.md` if any new tools were added (commit / push / draft_replies / etc.).

---

## Performance + caching

The cache + progressive rendering work from Wave 7 phase I stays. Specifically:
- Per-feature cache (`Map<feature, CacheEntry>`) survives panel close.
- Three refresh modes: `refresh()`, `forceRefresh()`, `revalidate()` — semantics unchanged.
- Section-by-section postMessage updates as fetches resolve.
- The new sections (repo cards, threads, drawer) all source from existing cached data, so they don't add fetches — they just render more of what's already there.

What does change:
- The summary table needs `feature_state(feature).state` which isn't cached today. Add it as a 6th cached field on `CacheEntry` and a 6th fetch in `refresh()`.
- The "actionable count" per repo is a derived value computed from `comments` — compute on render, no caching needed.

---

## Edge cases to remember

- **No feature in canonical slot.** The "Hibernate" and "Move to a worktree" actions need a target — surface as disabled (with tooltip) when slot context is missing.
- **GitHub MCP not configured.** The threads list shows "Review unavailable — configure GitHub MCP in `.canopy/mcps.json`" (matches today's behavior). Drawer's Review group greys out.
- **Linear not linked.** Re-link Linear button stays enabled (it's the entry point); other Linear-dependent actions stay neutral.
- **Single-repo features.** Repo grid collapses to one card. Drawer "Remove repo from lane" disables (can't remove the only repo).
- **First-time `Commit + push` with no upstream.** The Wave 2.3 plan covers `BlockerError(code='no_upstream')` with a fix-action that retries with `--set-upstream`. The drawer's handler reads the BlockerError, prompts the user "Set upstream and retry?", and re-issues with `--set-upstream` on yes.
- **Themes mid-session.** Theme toggle in the bridge re-renders the entire shell (no partial CSS swap). Cheap because cache hits keep all data warm.

---

## Out of scope

- **Posting drafted replies** to GitHub. v1 surfaces drafts; user pastes. Add a "Post all" button in a Wave 4.1 once `draft_replies` is in active use.
- **Cap-reached modal** for Slot actions. Already exists in `cockpitPanel.ts` (Wave 2.9 phase D); re-use that modal renderer when "Move to a worktree" hits the cap. Don't rebuild.
- **Conflict-resolution UX** during sync/rebase. The action drawer fires `commit/push/sync`; resolving conflicts happens in the editor as today. Future plan if friction warrants.
- **Customizable action set.** Actions are hard-coded per the mockup. No per-user reordering / hiding in v1.

---

## Rollout

Bump extension to `0.5.0`. The new dashboard is a visible UX change — list it as the headline in the changelog. The previous single-column dashboard's behavior is fully preserved by the new center pane, plus the right rail is additive — so no user feature regresses.

If the new layout doesn't fit a user's window (very narrow editor), the 360px drawer drops below the center pane via `@media (max-width: 1024px)` (single-column stack). Test this responsive case before declaring done.
