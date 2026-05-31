# Canopy CLI / MCP — Changelog

Tracks the Python side (CLI + MCP server). The VSCode extension has its own [vscode-extension/CHANGELOG.md](vscode-extension/CHANGELOG.md).

Versions follow semver. Pre-1.0 — minor bumps may add features or break behavior; the README is the source-of-truth contract.

## 3.1.1 — 2026-05-31

### Fixed
- `canopy-mcp --help` / `-h` now prints usage and exits instead of starting the
  stdio server and crashing on an empty stdin read. The MCP entry point is not
  meant to be invoked interactively; the help text says so and points at
  `canopy setup-agent`.

## 3.1.0 — 2026-05-30 (Plan 2 — Feature Resume)

### Added
- `canopy resume <alias>` (+ `mcp__canopy__feature_resume`): switch-aware
  compound action. One call: alias → switch-if-needed → refresh GitHub + Linear →
  compute structured brief with `intent_hints` for the most likely next actions.
  See `docs/concepts.md#returning-to-a-feature`.
- `canopy resolve <thread_id>` (+ `mcp__canopy__resolve_thread`): close a
  GitHub review thread + log to `.canopy/state/thread_resolutions.json` for
  attribution in the resume brief.
- `canopy reply <thread_id> [--body | --body-file | stdin]`
  (+ `mcp__canopy__reply_to_thread`): post a reply to a GH review thread.
  `--resolve` (or `resolve_after=True`) closes the thread after posting.
- `canopy commit --address <id> --resolve-thread`: optionally close the GH
  review thread after the local commit. Augment
  `auto_resolve_threads_on_address = true` in canopy.toml makes this the
  default for the workspace. `--no-resolve-thread` overrides the augment
  per-invocation.
- New state files: `.canopy/state/visits.json` (per-feature last-visit anchor
  `{feature: {last_visit, previous_visit}}`); `.canopy/state/thread_resolutions.json`
  (canopy-driven GH thread closures `{thread_id: {resolved_by_canopy_at,
  feature, via_command, via_commit_sha}}`).
- `actions/last_visit.py` — get/mark/reset the per-feature visit anchor.
- `actions/resume.py` — `feature_resume` compound action + `resume_summary`
  (counts-only view embedded in `switch` return).
- `actions/thread_actions.py` — `resolve_thread` + `reply_to_thread` wrappers
  + local resolution log writer.
- `actions/thread_resolutions.py` — load/record/filter_since for the
  thread-resolutions log.
- GraphQL thread API in `integrations/github.py`: `list_review_threads`,
  `resolve_thread`, `unresolve_thread`, `reply_to_thread`. Every comment from
  `get_review_comments` now carries a `thread_id` field (GraphQL-sourced when
  available, `""` on REST fallback) and `author_type` from GraphQL `__typename`.
- Bundled `using-canopy` skill now teaches `feature_resume` as the
  session-start primitive and documents the "Closing out review threads"
  workflow.

### Changed
- `switch(feature)` bumps `last_visit` on every successful switch and embeds
  `since_last_visit_summary` in its return value — a counts-only view
  (commits, threads, GH resolutions, draft replies) so the agent sees
  "something changed" without a full `feature_resume` round-trip. Sets
  `degraded: true` if GitHub is unreachable.
- `get_review_comments` prefers GraphQL when available (single round-trip for
  thread IDs + `author_type`); falls back to REST with `thread_id=""`.

### Notes
- `feature_resume` refreshes GitHub + Linear on every call — the brief is
  never cached at the canopy layer.
- Plan 1's slot model is the prerequisite. If upgrading from pre-3.0, run
  `canopy migrate-slots` first.

## 3.0.0 — 2026-05-28 (Wave 3.0)

**Breaking — slot model.** Worktree directories are now generic numbered slots (`worktree-1`, `worktree-2`, ...) instead of feature-named. `max_worktrees` renamed to `slots` (default 2). State unified in `.canopy/state/slots.json`; `active_feature.json` deleted. Run `canopy migrate-slots` once per workspace.

### Added
- `canopy slots` / `mcp__canopy__slots` — inspect canonical + warm slot occupancy. `slots --rich` returns the full dashboard shape (branch, dirty, ahead/behind, PR, CI, bots, linear, last commit, feature_state per slot+canonical).
- `canopy slot load <feature> [<slot-N>]` — warm a cold feature into a slot without changing canonical. Optional `--replace` evicts the occupant first.
- `canopy slot clear <slot-N>` — evict a slot's occupant to cold with feature-tagged stash.
- `canopy slot swap <slot-A> <slot-B>` — exchange the occupants of two slots (identical-scope features only in v1).
- `canopy switch <feature> --evict-to <slot-N>` — pin the destination slot for the outgoing canonical.
- `canopy switch --to-slot <slot-N>` — promote whatever feature occupies that slot.
- `canopy migrate-slots` / `mcp__canopy__migrate_slots` — one-shot pre-3.0 → 3.0 migration (with dry-run preflight and rollback safety).
- Slot id (`worktree-N`) is a universal alias form — any tool that takes a feature alias also accepts it.
- Doctor categories: `slot_dir_orphan`, `slot_entry_orphan`, `slot_branch_mismatch`, `slot_detached_head` (info severity for the bisect/detached case).
- Fast-path swap: when Y is already warm, `switch(Y)` is 5 git ops per repo + 1 JSON write. Closes issue #3.
- Transaction safety: `slots.json.in_flight` marker recorded on partial multi-repo switch/swap failures so subsequent operations refuse to compound the damage.

### Changed
- `canopy.toml`: `[workspace] max_worktrees = N` → `[workspace] slots = N`. Default 2 (was 0 = unlimited).
- Worktree layout: `.canopy/worktrees/<feature>/<repo>/` → `.canopy/worktrees/worktree-N/<repo>/`.
- MCP tools `worktree_create`, `worktree_info`, `workspace_status` return slot-keyed shapes. `slots` MCP tool defaults to `rich=True`.
- `slot_load` now requires the feature to be registered (`feature create` first) — no more silent "treat as all repos" fallback for unregistered names.

### Removed
- `actions/active_feature.py` (folded into `actions/slots.py`).
- `actions/realign.py` (deprecated since 2.9).
- Pre-2.9 lazy migration path inside `switch` (replaced by explicit `canopy migrate-slots` + a `pre_migration` BlockerError that points at it).

## 0.7.0

Five new top-level commands + a CI-aware state machine.

- **`canopy ship`** takes a feature from "code is committed" to "PR is open across every repo." Per-repo recipe: ensure-pushed → ensure-PR-exists → cross-repo body refresh so each PR description links to its siblings. Idempotent (`up_to_date` on re-run); refuses to silently recreate closed PRs; surfaces force-push divergence as `diverged`. Exposed as `mcp__canopy__ship`.
- **`canopy draft-replies <alias>`** walks each unresolved review comment's anchor sha through `git log -- <path>`. Addressed comments get a template-based draft (`Done — <subject>. (<sha>)` / `Addressed in <sha>: <subject>.` / `Addressed across N commits — <list>.`) with high/medium/low confidence based on commit count + keyword overlap. No LLM. Exposed as `mcp__canopy__draft_replies`.
- **CI status integration.** `feature_state.repos[*].pr.ci_status` carries a rolled-up CI verdict from `gh pr checks`. The state machine gains `awaiting_ci` (approved + pending CI), and approved + failing CI now flips to `needs_work` instead of misleadingly reporting `approved`. New `canopy pr-checks <alias>` + `mcp__canopy__pr_checks` for the raw check list.
- **`canopy worktree-bootstrap <feature>`** runs three optional steps per repo: copy `env_files` from main checkout into the worktree, run `install_cmd` (e.g. `uv sync` / `pnpm install`), and write `.canopy/workspaces/<feature>.code-workspace` when `[workspace] ide = "vscode"`. New per-repo `env_files` / `install_cmd` / `ide_settings` keys in canopy.toml; per-workspace `bootstrap_default` opt-in.
- **`canopy conflicts`** pairwise intersects each active feature's changed-files per repo. `--lines` opts into a deeper `git diff --unified=0` parse for line-range overlap (downgrades to `medium` when files overlap but lines don't); generated/lockfile-style files auto-drop to `medium` with an "auto-mergeable" suggestion. Exposed as `mcp__canopy__conflicts`.

MCP tools 54 → 59. Tests 651 → 712. Comment-shape adds `commit_id` so the file-history walk in draft-replies can anchor properly.

## 0.5.0

Catches the `__version__` constant up to ~6 months of shipped work. The handshake the doctor's staleness checks rely on is only useful when this number actually moves — this release fixes that drift.

- **`canopy commit` + `canopy push`** — feature-scoped multi-repo commit and push with `wrong_branch` / `no_upstream` blockers and per-repo result classification.
- **Provider-injection architecture** — `docs/architecture/providers.md` design doc for the issue-provider contract.
- **`canopy doctor`** — single recovery primitive with 16 diagnostic categories (state-file integrity + install / version / mcp / skill / vsix). `--fix` for auto-repairable; severity tiers; structured JSON.
- **Issue providers** — `IssueProvider` Protocol + registry under `canopy.providers.*`. Linear refactored into the contract; `GitHubIssuesProvider` via `gh` CLI. `[issue_provider]` block in canopy.toml; `issue_get` / `issue_list_my_issues` MCP tools (deprecated `linear_*` aliases retained).
- **Augments** — per-workspace `[augments]` block in canopy.toml + per-repo overrides. `preflight_cmd` is the first consumer; `review_bots` and `test_cmd` reserved. Multi-skill installer; `augment-canopy` skill teaches the agent how to mutate canopy.toml safely.
- **Bot-comment tracking** — per-comment resolution log at `.canopy/state/bot_resolutions.json`; `canopy commit --address <comment-id>` auto-suffixes the message and records the resolution; `canopy bot-status` rollup; new `awaiting_bot_resolution` state.
- **Historian** — per-feature persistent memory at `.canopy/memory/<feature>.md`. Auto-read on `canopy switch` (response carries `memory: <markdown>`); 5 MCP tools (`historian_decide` / `historian_pause` / `historian_defer_comment` / `feature_memory` / `historian_compact`); 2 CLI commands (`canopy historian show` / `compact`); auto-mirror from `commit --address` and `github_get_pr_comments`.

MCP tools 41 → 54. Tests ~400 → 624. State machine 8 → 9 (added `awaiting_bot_resolution`). Bundled skills 1 → 2 (`using-canopy` + opt-in `augment-canopy`).

## 0.1.0

Initial release: workspace discovery, feature lanes, post-checkout hook, drift detection, `switch` / `triage` / `feature_state` actions, MCP server, agent setup.
