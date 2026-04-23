<p align="center">
  <img src="docs/canopy-banner.svg" alt="Canopy" width="600">
</p>

<p align="center">
  <strong>Multi-repo worktree manager with MCP server for AI agents</strong>
</p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white">
  <img alt="Tests" src="https://img.shields.io/badge/tests-159%20passing-brightgreen?style=flat-square">
  <img alt="MCP Tools" src="https://img.shields.io/badge/MCP%20tools-26-purple?style=flat-square">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-gray?style=flat-square">
</p>

---

Canopy coordinates Git worktrees across multiple repositories. It creates isolated working directories for each feature, opens them in your IDE, commits across repos atomically, and exposes every operation as both a CLI command and an MCP tool — so AI agents can operate your workspace through the same interface you use.

No proprietary abstractions. Feature lanes map to real Git branches and real Git worktrees.

## Why

Working on a feature that spans multiple repos means coordinating branches, stashing, switching, and committing across all of them. Git worktrees solve the context-switching problem, but the UX for managing them across multiple repos doesn't exist. Canopy provides it: one command to create worktrees in every repo, one command to open them in your IDE, one command to commit across all of them.

## How It Looks

<details open>
<summary><strong><code>canopy worktree</code></strong> — live worktree dashboard</summary>
<br>
<p align="center">
  <img src="docs/cli-worktree.svg" alt="canopy worktree" width="600">
</p>
</details>

<details>
<summary><strong><code>canopy worktree payment-flow ENG-123</code></strong> — create with Linear link</summary>
<br>
<p align="center">
  <img src="docs/cli-worktree-create.svg" alt="canopy worktree create" width="600">
</p>
</details>

<details>
<summary><strong><code>canopy status</code></strong> — cross-repo status</summary>
<br>
<p align="center">
  <img src="docs/cli-status.svg" alt="canopy status" width="600">
</p>
</details>

<details>
<summary><strong><code>canopy init --force</code></strong> — workspace init</summary>
<br>
<p align="center">
  <img src="docs/cli-init.svg" alt="canopy init" width="600">
</p>
</details>

<details>
<summary><strong><code>canopy stage "feat: add auth module"</code></strong> — context-aware commit</summary>
<br>
<p align="center">
  <img src="docs/cli-stage.svg" alt="canopy stage" width="600">
</p>
</details>

## Installation

```bash
git clone https://github.com/ashmitb/canopy.git
cd canopy

python3 -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate

pip install -e .
```

To make `canopy` available globally without activating the venv:

```bash
# Add to ~/.zshrc or ~/.bashrc
export PATH="$HOME/projects/canopy/.venv/bin:$PATH"
```

## Quick Start

```bash
cd ~/my-product/
canopy init                             # scan for repos, generate canopy.toml

canopy worktree auth-flow               # create worktrees in every repo
canopy worktree payment-flow ENG-123    # ...or link to a Linear issue

canopy code auth-flow                   # open in VS Code (multi-root workspace)
canopy cursor auth-flow                 # open in Cursor
canopy fork auth-flow                   # open in Fork.app

cd .canopy/worktrees/auth-flow
canopy stage "feat: add auth module"    # stage + commit across all repos
```

## Workspace Layout

```
my-product/
├── canopy.toml              ← workspace definition (which repos, roles, languages)
├── api/                     ← main working tree (on main)
├── ui/                      ← main working tree (on main)
└── .canopy/
    ├── features.json        ← feature lane metadata + Linear issue links
    ├── mcps.json            ← external MCP server configs (Linear, etc.)
    └── worktrees/
        ├── auth-flow/       ← isolated feature environment
        │   ├── api/         ← linked worktree on auth-flow branch
        │   └── ui/          ← linked worktree on auth-flow branch
        └── payment-flow/
            ├── api/
            └── ui/
```

## Commands

### Worktrees

| Command | Description |
|---|---|
| `canopy worktree <name>` | Create linked worktrees for a feature across all repos |
| `canopy worktree <name> <issue>` | Same, with a Linear issue link (fetched via MCP) |
| `canopy worktree` | Live dashboard — shows branch, dirty state, ahead/behind per worktree |

### Core

| Command | Description |
|---|---|
| `canopy init` | Scan subdirectories, detect Git repos and worktrees, generate `canopy.toml` |
| `canopy status` | Per-repo branch, dirty count, divergence from default branch |
| `canopy stage <msg>` | Context-aware `git add -A && git commit` — detects feature from cwd |
| `canopy context` | Debug: show detected context type, feature, repos, paths |

### Feature Lanes

| Command | Description |
|---|---|
| `canopy feature create <name>` | Create branches (no worktrees) across repos |
| `canopy feature list` | List all lanes with per-repo state |
| `canopy feature switch <name>` | Checkout branch in each repo (worktree-aware — won't fail if branch is in a worktree) |
| `canopy feature diff <name>` | Aggregate diff vs default branch + cross-repo type overlap detection |
| `canopy feature status <name>` | Detailed per-repo state + merge readiness check |

### IDE Integration

| Command | Description |
|---|---|
| `canopy code <feature\|.>` | Generate `.code-workspace` and open VS Code |
| `canopy cursor <feature\|.>` | Generate `.code-workspace` and open Cursor |
| `canopy fork <feature\|.>` | Open each repo in Fork.app (separate tabs) |

### Review

| Command | Description |
|---|---|
| `canopy review <feature>` | Review readiness — PR status, unresolved comments, pre-commit checks |

### Cross-Repo Git

| Command | Description |
|---|---|
| `canopy checkout <branch>` | Checkout across all repos |
| `canopy commit -m <msg>` | Commit staged changes in repos that have them |
| `canopy log` | Interleaved chronological log across repos |
| `canopy sync` | Pull default branch, rebase feature branches |
| `canopy branch list\|delete\|rename` | Branch management across repos |
| `canopy stash save\|pop\|list\|drop` | Stash lifecycle across repos |

Every command supports `--json` for machine-readable output. Human output uses [rich](https://github.com/Textualize/rich) for colored text, spinners, and status indicators; `--json` bypasses all of it.

## MCP Server

Canopy is an MCP server. Every CLI operation is exposed as a tool (26 total) over stdio transport, so AI agents can operate your workspace programmatically.

```bash
canopy-mcp   # starts the server
```

Register in Claude Code, Cursor, or any MCP-compatible client:

```json
{
  "mcpServers": {
    "canopy": {
      "command": "canopy-mcp",
      "env": { "CANOPY_ROOT": "/path/to/workspace" }
    }
  }
}
```

**Tools exposed:** `workspace_status`, `workspace_context`, `worktree_create`, `worktree_info`, `feature_create`, `feature_list`, `feature_status`, `feature_switch`, `feature_diff`, `feature_merge_readiness`, `feature_paths`, `checkout`, `commit`, `stage`, `log`, `branch_list`, `branch_delete`, `branch_rename`, `stash_save`, `stash_pop`, `stash_list`, `stash_drop`, `sync`, `review_status`, `review_comments`, `review_prep`.

## MCP Client

Canopy is also an MCP **client**. Rather than adding direct API integrations (Linear SDK, GitHub SDK, etc.), canopy spawns external MCP servers as subprocesses and calls their tools via the standard MCP protocol. This means:

- Zero external API dependencies in the canopy codebase
- Any MCP server can be plugged in via config
- Integrations work through the same protocol AI agents use

Configuration lives in `.canopy/mcps.json`:

```json
{
  "linear": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-linear"],
    "env": { "LINEAR_API_KEY": "lin_api_..." }
  }
}
```

The client module (`mcp/client.py`) uses the `mcp` SDK's `ClientSession` + `stdio_client` to spawn the server, call tools, and return results. A synchronous wrapper handles event loop management for CLI use.

Currently powers:
- **Linear integration** — `canopy worktree <name> ENG-123` spawns the Linear MCP, fetches the issue title/URL, and stores the link in `features.json`.
- **GitHub integration** — `canopy review <feature>` spawns the GitHub MCP to find the PR for a branch and fetch unresolved review comments.

## Context Detection

`canopy stage` and other context-aware commands work by detecting where you are in the filesystem:

| Context | Detection | Scope |
|---|---|---|
| `feature_dir` | Inside `.canopy/worktrees/<feature>/` | All repos in the feature |
| `repo_worktree` | Inside `.canopy/worktrees/<feature>/<repo>/` | Single repo |
| `repo` | Inside a workspace repo directory | Single repo (feature = current branch if non-default) |
| `workspace_root` | At the `canopy.toml` level | All repos |

This is implemented in `workspace/context.py` and powers `canopy stage`, `canopy context`, and the MCP `stage` tool.

## Architecture

```
src/canopy/
├── cli/
│   ├── main.py              # argparse CLI — thin layer, no business logic
│   └── ui.py                # rich terminal output (theme, spinners, colors)
├── workspace/
│   ├── config.py            # canopy.toml parser (RepoConfig, WorkspaceConfig)
│   ├── discovery.py         # auto-detect repos + worktrees, generate toml
│   ├── context.py           # context detection from cwd
│   └── workspace.py         # Workspace class, RepoState dataclass
├── git/
│   ├── repo.py              # ALL git subprocess calls (single-repo only)
│   └── multi.py             # cross-repo operations (calls repo.py)
├── features/
│   └── coordinator.py       # feature lane lifecycle, worktree creation, live scanning
├── integrations/
│   ├── linear.py            # Linear issue fetching (via mcp/client.py)
│   ├── github.py            # GitHub PR + review comments (via mcp/client.py)
│   └── precommit.py         # detect and run pre-commit hooks (framework or git hooks)
└── mcp/
    ├── server.py            # MCP server — 26 tools, stdio transport
    └── client.py            # MCP client — spawn + call external MCP servers
```

**Key boundary:** `git/repo.py` is the only module that calls `subprocess.run(["git", ...])`. Everything else goes through it. This makes the git layer replaceable and testable.

**Key boundary:** `mcp/server.py` and `cli/main.py` are thin wrappers. Business logic lives in `features/coordinator.py`, `git/multi.py`, and `workspace/`.

**Key boundary:** All external integrations go through `mcp/client.py`. No direct API calls anywhere in the codebase.

## canopy.toml

```toml
[workspace]
name = "my-product"

[[repos]]
name = "api"
path = "./api"
role = "backend"
lang = "python"

[[repos]]
name = "ui"
path = "./ui"
role = "frontend"
lang = "typescript"
```

Generated by `canopy init`. Worktrees are detected automatically — canopy distinguishes `.git` directories (normal repos) from `.git` files (linked worktrees) and tags them with `is_worktree` and `worktree_main`.

## Development

```bash
cd ~/projects/canopy
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v             # 159 tests, ~2s, all use real temporary Git repos
```

Tests create real Git repositories in temporary directories — no mocks. This catches actual git behavior differences across platforms.

## License

MIT
