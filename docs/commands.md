# Commands

Every command supports `--json`. Commands that accept a feature name accept any [universal alias](concepts.md#universal-aliases) (feature name, Linear ID, `<repo>#<n>`, PR URL, `<repo>:<branch>`).

Organized by **workflow stage** — top to bottom matches a typical day.

## Setup

| Command | What it does |
|---|---|
| `canopy init [path]` | Discover repos, write `canopy.toml`, install drift hooks, register the `using-canopy` skill, add canopy MCP to `.mcp.json`. Use `--no-agent` to skip the skill + MCP bits. |
| `canopy setup-agent` | Install (or refresh) the agent integration only — skill + MCP. `--check` reports status. `--reinstall` forces overwrite. `--skill-only` / `--mcp-only` for partial installs. |
| `canopy hooks install\|uninstall\|status` | Manage the post-checkout hooks per repo. Hooks are what feed `.canopy/state/heads.json`. |
| `canopy config [key] [value]` | Read/write workspace settings (e.g. `max_worktrees`). |

## Discover

| Command | What it does |
|---|---|
| `canopy triage [--author @me]` | Prioritized list of features needing attention. Groups open PRs across repos by feature, sorts by review state (`changes_requested` > `review_required_with_bot_comments` > `review_required` > `approved`). Use this every morning. |
| `canopy state <feature>` | The 9-state machine for one feature, plus the suggested `next_actions`. Same JSON the dashboard renders. |
| `canopy drift [<feature>]` | Per-feature alignment from `.canopy/state/heads.json` (the post-checkout hook's data). Fast, hook-driven. Doesn't touch git directly. |
| `canopy list` | Compact feature overview — names, Linear links, per-repo branch/dirty/ahead-behind. |
| `canopy status` | Per-repo branch + dirty + divergence from default branch. |
| `canopy feature list` | Same as `list` (legacy spelling). |
| `canopy feature status <name>` | Detailed per-repo state + merge-readiness check. |
| `canopy worktree` | Live worktree dashboard — branch, dirty state, ahead/behind per linked worktree. |
| `canopy log [--feature <f>]` | Interleaved chronological log across repos. |

## Read

Read primitives — alias-aware fetches against Linear and GitHub. Use these instead of shelling `gh api` or `gh pr view`.

| Command | What it does |
|---|---|
| `canopy issue <alias>` | Linear issue by ID (`SIN-412`) or feature alias (lookup via lane's `linear_issue`). |
| `canopy pr <alias>` | PR data per repo. Alias forms: feature, `<repo>#<n>`, PR URL. |
| `canopy branch info <alias>` | Branch HEAD, upstream, ahead/behind per repo. Alias forms: feature, `<repo>:<branch>`. |
| `canopy comments <alias>` | Temporally classified PR review comments — `actionable_threads` vs `likely_resolved_threads` vs resolved count. Alias: feature, `<repo>#<n>`, PR URL. |
| `canopy review <feature>` | Combined: PR status + unresolved comments + pre-commit checks. Older composite — prefer `state` + `comments` separately. |
| `canopy feature diff <name>` | Aggregate diff vs default branch + cross-repo type overlap detection. |
| `canopy feature changes <name>` | Per-file change summary across the feature lane. |

## Work

Write actions and execution.

| Command | What it does |
|---|---|
| `canopy switch <feature> [--release-current] [--no-evict] [--evict <f>]` | **The focus primitive (Wave 2.9).** Promote a feature to the canonical slot. Default (active rotation): previously-canonical evacuates to a warm worktree (full stash → checkout → pop). `--release-current` (wind-down): previous goes cold with a feature-tagged stash. Cap-reached blocker surfaces explicit fix actions (wind-down, evict by name, raise cap). See [docs/concepts.md §4](concepts.md#4-the-canonical-slot-model). |
| `canopy checkout <branch>` | Plain checkout across all repos — no feature context, no per-repo branch resolution. Use `switch` for feature-scoped focus changes. |
| `canopy run <repo> <command> [--feature]` | Run a shell command in a canopy-managed repo with cwd resolved internally. The "agent never `cd`s" tool — also useful from a CLI in a deeply nested directory. |
| `canopy code\|cursor\|fork <feature\|.>` | Open the feature in VS Code / Cursor / Fork.app (alias-aware; generates `.code-workspace` for the IDE ones). |
| `canopy sync` | Pull default branch + rebase feature branches across repos. |
| `canopy commit -m <msg> [--feature <f>] [--repo <r,...>] [--paths <p ...>] [--no-hooks] [--amend] [--address <id>]` | **Wave 2.3 + M3.** Commit across every repo in the canonical (or named) feature with a single message. Pre-flight refuses with `BlockerError(code='wrong_branch')` if any in-scope repo has drifted; per-repo hook failures don't cancel the others (status: `hooks_failed`). `--address <comment-id>` (numeric id or GitHub URL) auto-suffixes the message with the bot comment's title + URL and records the resolution in `.canopy/state/bot_resolutions.json`. Non-bot comments raise `BlockerError(code='not_a_bot_comment')`. |
| `canopy bot-status [--feature <f>] [--unresolved-only]` | **M3.** Per-feature rollup of bot review comments — total / resolved / unresolved per repo + an `all_resolved` flag. Bot vs human classification respects `[augments] review_bots` in canopy.toml. |
| `canopy historian show [<feature>]` | **M4.** Print the rendered memory file for a feature (3 sections: resolutions log, PR context, sessions). Returns empty when no memory has been recorded yet. |
| `canopy historian compact [<feature>] [--keep-sessions <n>]` | **M4.** Trim the Sessions section to the most-recent N (default 5). Resolutions log + PR context are preserved regardless. v1 is mechanical (no LLM); future iterations will summarize. |
| `canopy push [--feature <f>] [--repo <r,...>] [--set-upstream] [--force-with-lease] [--dry-run]` | **Wave 2.3.** Push the feature branch in every in-scope repo. Pre-flight raises `BlockerError(code='no_upstream')` if any repo lacks an upstream and `--set-upstream` was not passed; the fix-action carries the same args + `--set-upstream` so an agent retries mechanically. Per-repo statuses: `ok`, `up_to_date`, `rejected`, `failed`. |

## Verify

| Command | What it does |
|---|---|
| `canopy preflight [<feature>]` | Run per-repo pre-commit checks. With `<feature>`, runs against the feature lane and records the result to `.canopy/state/preflight.json` (which feeds `canopy state`'s `ready_to_commit` detection). Without `<feature>`, runs against the current cwd's context. **Use as a dry-run before `canopy commit`** — preflight stages and runs hooks but never commits. |

## Stash (feature-aware)

| Command | What it does |
|---|---|
| `canopy stash save -m <msg> [--feature <f>]` | Stash dirty changes (incl. untracked when `--feature` is used). Tagged stash messages: `[canopy <feature> @ <ts>] <msg>`. |
| `canopy stash list [--feature <f>]` | Stashes across repos. With `--feature`, groups by feature tag. Without, flat list per repo. |
| `canopy stash pop [--feature <f>] [<index>]` | Pop. With `--feature`, pops the most recent matching tagged stash per repo. |
| `canopy stash drop [<index>]` | Drop a stash by index. |

## Worktree

| Command | What it does |
|---|---|
| `canopy worktree <name> [issue]` | Create linked worktrees for a feature in every repo, optionally linking a Linear issue. Worktrees go to `.canopy/worktrees/<feature>/<repo>/`. |
| `canopy worktree` | Live dashboard (read-only, see "Discover"). |

## Branch

| Command | What it does |
|---|---|
| `canopy branch list` | Branches per repo. |
| `canopy branch delete <name> [--force]` | Delete across repos. |
| `canopy branch rename <old> <new>` | Rename across repos. |
| `canopy branch info <alias>` | Branch state per repo (alias-aware; see "Read"). |

## Cleanup

| Command | What it does |
|---|---|
| `canopy done <feature> [--force]` | Clean up a completed feature — remove worktrees, delete branches (if merged), archive lane in `features.json`. `--force` overrides the dirty-tree refusal. |

## Recover

| Command | What it does |
|---|---|
| `canopy doctor [-v] [--feature <f>]` | Diagnose 16 categories of state-file drift + install staleness. Reports `errors`/`warnings`/`info` with structured `code`, `expected`, `actual`, and per-issue `fix_action`. **Run this first** when any other canopy operation returns an unexpected error — most "something is off" cases trace to one of these categories. `--json` returns the full report shape `{issues, summary, fixed, skipped}`. |
| `canopy doctor --fix` | Repair every `auto_fixable=true` issue. Examples: rewrite `heads.json` from live git, drop orphan worktree dirs via `git worktree remove --force`, reinstall a missing post-checkout hook, re-resolve broken `active_feature.json` paths, write a missing `.mcp.json` entry, reinstall the `using-canopy` skill. |
| `canopy doctor --fix-category <c>` | Repair just one category (`heads`, `active_feature`, `worktrees`, `hooks`, `preflight`, `features`, `branches`, `cli`, `mcp`, `skill`, `vsix`). Implies `--fix`. |
| `canopy doctor --clean-vsix` | Required gate for the destructive `vsix_duplicates` repair (removes all but the newest `singularityinc.canopy-*` install dir). Other repairs are unaffected. |
| `canopy --version` | Print the installed CLI version. |

### Diagnostic codes

State-integrity (the workspace's own bookkeeping):

| Code | Severity | Detection | Auto-fix |
|---|---|---|---|
| `heads_stale` | warn | `heads.json` out of sync with `git rev-parse HEAD` | rewrite from live git |
| `active_feature_orphan` | error | `active_feature.json` points at unknown feature | clear the file |
| `active_feature_path_missing` | error | `per_repo_paths` reference non-existent dirs | re-resolve from `features.json` |
| `worktree_orphan` | warn | `.canopy/worktrees/<f>/<r>/` not referenced by any feature | `git worktree remove --force` |
| `worktree_missing` | error | feature × repo `worktree_paths` entry has no dir on disk | drop the entry |
| `hook_missing` | error | repo lacks canopy's post-checkout hook | reinstall (chains existing user hook) |
| `hook_chained_unsafe` | warn | chained user hook present but not executable | `chmod +x` |
| `preflight_stale` | info | recorded `head_sha_per_repo` no longer matches live HEAD | drop the entry |
| `features_unknown_repo` | error | `features.json` references repo not in `canopy.toml` | manual (decide whether to restore the repo or `done` the feature) |
| `branches_missing` | error | feature's recorded branch doesn't exist locally | manual (restore branch or `done` feature) |

Install-staleness (canopy's installation around the workspace):

| Code | Severity | Detection | Auto-fix |
|---|---|---|---|
| `cli_stale` | warn | `canopy --version` < running `__version__` | manual reinstall |
| `mcp_stale` | error | `canopy-mcp --version` < running `__version__` | manual reinstall |
| `mcp_missing_in_workspace` | error | `.mcp.json` lacks canopy entry, or its `CANOPY_ROOT` is wrong | `install_mcp(reinstall=True)` |
| `skill_missing` | warn | no `~/.claude/skills/using-canopy/SKILL.md` | `install_skill()` |
| `skill_stale` | warn | installed skill drifted from bundled source | `install_skill(reinstall=True)` |
| `vsix_duplicates` | info | multiple `singularityinc.canopy-*` extension dirs | requires `--clean-vsix` |

## Debug

| Command | What it does |
|---|---|
| `canopy context` | Show detected canopy context for the current dir (which feature, repo, branch). Powers `preflight`'s context detection. |

## Common patterns

The daily loop:

```bash
canopy triage              # what to work on
canopy state <feature>     # get oriented + see next_actions
canopy switch <feature>    # promote to canonical (handles drift via active rotation)
canopy comments <feature>  # actionable threads only
# ... edit code ...
canopy preflight           # stage + run hooks (dry-run; no commit)
canopy commit -m "..."     # commit across the canonical feature
canopy push                # publish (add --set-upstream on first push)
canopy state <feature>     # confirm transition
```

Switching focus mid-flight (canonical-slot model):

```bash
# Active rotation: previous focus evacuates to a warm worktree, instant to switch back
canopy switch other-feature
# ... work on other-feature ...
canopy switch current-feature   # warm worktree promotes back to canonical

# Wind-down: previous focus goes cold (feature-tagged stash if dirty)
canopy switch new-feature --release-current
```

Investigate without changing state:

```bash
canopy state <feature> --json | jq .summary
canopy comments <feature> --json | jq '.repos[].actionable_threads'
canopy branch info <feature>
canopy pr <feature>
```
