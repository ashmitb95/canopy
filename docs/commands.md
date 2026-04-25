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
| `canopy state <feature>` | The 8-state machine for one feature, plus the suggested `next_actions`. Same JSON the dashboard renders. |
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
| `canopy issue <alias>` | Linear issue by ID (`ENG-412`) or feature alias (lookup via lane's `linear_issue`). |
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
| `canopy switch <feature> [--create-worktrees] [--auto-stash]` | Activate a feature as the current workspace context. If feature has worktrees → mark them active. If main-tree only → call realign internally. If neither + `--create-worktrees` → create worktrees on the fly. After switch, `canopy state` / `canopy run <repo> <cmd>` (without `--feature`) default to this feature. |
| `canopy realign <feature> [--auto-stash]` | Bring all repos in the feature lane onto the feature's branch. Pure drift-fixer for main-tree features (does NOT activate as context — use `switch` for that). `--auto-stash` tags + stashes dirty trees first via P12. |
| `canopy checkout <branch>` | Plain checkout across all repos — no feature context, no per-repo branch resolution. Use `realign` for feature-scoped switching. |
| `canopy run <repo> <command> [--feature]` | Run a shell command in a canopy-managed repo with cwd resolved internally. The "agent never `cd`s" tool — also useful from a CLI in a deeply nested directory. |
| `canopy code\|cursor\|fork <feature\|.>` | Open the feature in VS Code / Cursor / Fork.app (alias-aware; generates `.code-workspace` for the IDE ones). |
| `canopy sync` | Pull default branch + rebase feature branches across repos. |

## Verify

| Command | What it does |
|---|---|
| `canopy preflight [<feature>]` | Run per-repo pre-commit checks. With `<feature>`, runs against the feature lane and records the result to `.canopy/state/preflight.json` (which feeds `canopy state`'s `ready_to_commit` detection). Without `<feature>`, runs against the current cwd's context. |

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

## Debug

| Command | What it does |
|---|---|
| `canopy context` | Show detected canopy context for the current dir (which feature, repo, branch). Powers `preflight`'s context detection. |

## Common patterns

The daily loop:

```bash
canopy triage              # what to work on
canopy state <feature>     # get oriented + see next_actions
canopy realign <feature>   # if drifted (one fix command)
canopy comments <feature>  # actionable threads only
# ... edit code ...
canopy preflight <feature> # records result for feature_state
canopy state <feature>     # confirm transition (in_progress → ready_to_commit)
```

Stash + switch flow:

```bash
canopy stash save -m "WIP" --feature current-feature
canopy realign other-feature
# work on other-feature
canopy realign current-feature --auto-stash   # restores prior context
canopy stash pop --feature current-feature
```

Investigate without changing state:

```bash
canopy state <feature> --json | jq .summary
canopy comments <feature> --json | jq '.repos[].actionable_threads'
canopy branch info <feature>
canopy pr <feature>
```
