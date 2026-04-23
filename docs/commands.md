# Commands

Every command supports `--json` for machine-readable output. Commands that accept a feature name also accept an alias — see [aliases](./workspace.md#alias-resolution).

## Worktrees

| Command | Description |
|---|---|
| `canopy worktree <name>` | Create linked worktrees for a feature across all repos |
| `canopy worktree <name> <issue>` | Same, with a Linear issue link (fetched via MCP) |
| `canopy worktree` | Live dashboard — shows branch, dirty state, ahead/behind per worktree |

## Core

| Command | Description |
|---|---|
| `canopy init` | Scan subdirectories, detect Git repos and worktrees, generate `canopy.toml` |
| `canopy status` | Per-repo branch, dirty count, divergence from default branch |
| `canopy preflight` | Context-aware `git add -A` + run pre-commit hooks — does not commit |
| `canopy context` | Debug: show detected context type, feature, repos, paths |

## Feature Lanes

| Command | Description |
|---|---|
| `canopy feature create <name>` | Create branches (no worktrees) across repos |
| `canopy feature list` | List all lanes with per-repo state |
| `canopy feature switch <name>` | Checkout branch in each repo — worktree-aware, alias-aware |
| `canopy feature diff <name>` | Aggregate diff vs default branch + cross-repo type overlap detection |
| `canopy feature status <name>` | Detailed per-repo state + merge readiness check |

## IDE Integration

| Command | Description |
|---|---|
| `canopy code <feature\|.>` | Generate `.code-workspace` and open VS Code (alias-aware) |
| `canopy cursor <feature\|.>` | Generate `.code-workspace` and open Cursor (alias-aware) |
| `canopy fork <feature\|.>` | Open each repo in Fork.app (alias-aware) |

## Review

| Command | Description |
|---|---|
| `canopy review <feature>` | Review readiness — PR status, unresolved comments, pre-commit checks (alias-aware) |

## Workspace Management

| Command | Description |
|---|---|
| `canopy list` | Compact feature overview — name, Linear link, per-repo branch/dirty/ahead-behind |
| `canopy switch <name>` | Checkout feature across all repos — shows branch, dirty count, ahead/behind, PR links |
| `canopy done <feature>` | Clean up completed feature — remove worktrees, delete branches, archive |
| `canopy config [key] [value]` | Read/write workspace settings (e.g. `max_worktrees`) |

## Cross-Repo Git

| Command | Description |
|---|---|
| `canopy checkout <branch>` | Checkout across all repos |
| `canopy log` | Interleaved chronological log across repos |
| `canopy sync` | Pull default branch, rebase feature branches |
| `canopy branch list\|delete\|rename` | Branch management across repos |
| `canopy stash save\|pop\|list\|drop` | Stash lifecycle across repos |
