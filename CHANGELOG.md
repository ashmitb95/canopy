# Canopy CLI / MCP — Changelog

Tracks the Python side (CLI + MCP server). The VSCode extension has its own [vscode-extension/CHANGELOG.md](vscode-extension/CHANGELOG.md).

Versions follow semver. Pre-1.0 — minor bumps may add features or break behavior; the README is the source-of-truth contract.

## 0.5.0

Catches the `__version__` constant up to ~6 months of shipped milestones (0.1.0 → 0.5.0). The handshake the doctor's `cli_stale` / `mcp_stale` checks rely on is only useful when the source-of-truth version actually moves — this release fixes that.

### New since 0.1.0

- **Wave 2.3 — `commit` + `push`** (PR #2 + #3): feature-scoped multi-repo commit and push with `wrong_branch` / `no_upstream` blockers and per-repo result classification.
- **M0 — Provider injection architecture** (PR #7): `docs/architecture/providers.md` design doc for the issue-provider contract.
- **M1 — `canopy doctor`** (PR #8): single recovery primitive with 16 diagnostic categories (state-file integrity + install / version / mcp / skill / vsix). `--fix` for auto-repairable; severity tiers; structured JSON.
- **M5 — Issue-provider scaffold** (PR #9): `IssueProvider` Protocol + registry under `canopy.providers.*`. Linear refactored into the contract; new `GitHubIssuesProvider` via `gh` CLI. `[issue_provider]` block in canopy.toml; `issue_get` / `issue_list_my_issues` MCP tools (deprecated `linear_*` aliases retained).
- **M2 — Augments** (PR #10): per-workspace `[augments]` block in canopy.toml + per-repo overrides. `preflight_cmd` is the first consumer; `review_bots` and `test_cmd` reserved. Multi-skill installer (`canopy setup-agent --skill augment-canopy`); `augment-canopy` skill teaches the agent how to mutate canopy.toml safely.
- **M3 — Bot-comment tracking** (PR #12): per-comment resolution log at `.canopy/state/bot_resolutions.json`; `canopy commit --address <comment-id>` auto-suffixes the message + records the resolution; `canopy bot-status` rollup; new `awaiting_bot_resolution` state in the state machine; `actionable_count` split into human + bot counts.
- **M4 — Historian** (PR #14): per-feature persistent memory at `.canopy/memory/<feature>.md`. Auto-read on `canopy switch` (response carries `memory: <markdown>`); 5 MCP tools (`historian_decide` / `historian_pause` / `historian_defer_comment` / `feature_memory` / `historian_compact`); 2 CLI commands (`canopy historian show` / `compact`); auto-mirror from `commit --address` and `github_get_pr_comments`.

### Counts

- MCP tools: 41 → 54
- Test suite: ~400 → 624 passing
- State machine: 8 states → 9 states (added `awaiting_bot_resolution`)
- Bundled skills: 1 (`using-canopy`) → 2 (+ opt-in `augment-canopy`)

## 0.1.0

Initial release. Wave 1 + Wave 2.1/2.2: workspace discovery, feature lanes, post-checkout hook, drift detection, switch/triage/feature_state actions, MCP server, agent setup.
