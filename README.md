# Canopy

A worktree-first workspace manager that makes multi-repo feature development feel like a monorepo, without actually being one.

## The Problem

Modern products span multiple repos — a React frontend, Python API, shared types, infrastructure. Working on a single feature means coordinating branches, stashing, switching, and committing across all of them. Git worktrees solve the context-switching problem perfectly, but nobody uses them because the UX is terrible.

## What Canopy Does

Canopy manages **worktrees as first-class project units**. Create a feature, get isolated directories for every repo, open them in your IDE with one command, commit across all of them at once. Your main branches stay untouched — no stashing, no context switching.

```
my-product/
├── canopy.toml              ← workspace definition
├── api/                     ← Python backend (on main)
├── ui/                      ← React frontend (on main)
└── .canopy/
    ├── features.json        ← feature lane metadata
    └── worktrees/
        ├── auth-flow/       ← feature worktrees
        │   ├── api/         ← api on auth-flow branch
        │   └── ui/          ← ui on auth-flow branch
        └── payment-flow/    ← another feature, in parallel
            ├── api/
            └── ui/
```

## Quick Start

```bash
pip install -e .

# Initialize a workspace (auto-detects repos)
cd ~/my-product/
canopy init

# Create a feature with worktrees — each repo gets its own directory
canopy feature create --worktree auth-flow

# Open in your IDE
canopy code auth-flow        # VS Code (multi-root workspace)
canopy cursor auth-flow      # Cursor
canopy fork auth-flow        # Fork (separate windows per repo)

# Work in your IDE... then commit from the feature directory
cd .canopy/worktrees/auth-flow
canopy stage "feat: add auth module"
#   api: a3f2b1c
#   ui: 7e8d4f2

# Start another feature in parallel — no conflicts
canopy feature create --worktree payment-flow
canopy code payment-flow
```

## Commands

### Core workflow

| Command | Description |
|---|---|
| `canopy init` | Auto-detect repos, generate `canopy.toml` |
| `canopy status` | Cross-repo status (branches, divergence, dirty files) |
| `canopy stage <message>` | Context-aware add + commit (knows which feature you're in) |
| `canopy context` | Show detected context for current directory |

### Feature lanes

| Command | Description |
|---|---|
| `canopy feature create <name>` | Create branches across repos |
| `canopy feature create --worktree <name>` | Create worktrees (recommended) |
| `canopy feature list` | List active feature lanes |
| `canopy feature switch <name>` | Checkout feature (worktree-aware) |
| `canopy feature diff <name>` | Aggregate diff with type overlap detection |
| `canopy feature status <name>` | Detailed status + merge readiness check |

### IDE integration

| Command | Description |
|---|---|
| `canopy code <feature\|.>` | Open VS Code with feature repos |
| `canopy cursor <feature\|.>` | Open Cursor with feature repos |
| `canopy fork <feature\|.>` | Open Fork.app (separate window per repo) |

### Git operations (cross-repo)

| Command | Description |
|---|---|
| `canopy checkout <branch>` | Checkout across repos |
| `canopy commit -m <msg>` | Commit staged changes across repos |
| `canopy log` | Interleaved chronological log across repos |
| `canopy sync` | Pull default branch + rebase features |
| `canopy branch list\|delete\|rename` | Branch management across repos |
| `canopy stash save\|pop\|list\|drop` | Stash lifecycle across repos |
| `canopy worktree` | Show worktree info per repo |

All commands support `--json` for machine-readable output.

## MCP Server

Canopy exposes all operations as an MCP server (22 tools) for AI agents:

```bash
# Run the MCP server
canopy-mcp
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

Tools include: `workspace_status`, `feature_create`, `feature_status`, `stage`, `log`, `checkout`, `commit`, `branch_list`, `stash_save`, `worktree_info`, and more.

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

`canopy init` generates this automatically by scanning subdirectories for Git repos. Worktrees are detected and tagged — Canopy understands which directories are linked worktrees of the same repo.

## Design Decisions

**Worktree-first.** Features get their own directories. No stashing, no context switching. Open a feature in your IDE and it's just a normal project.

**Real Git only.** Feature lanes map to real Git branches. Worktrees are real Git worktrees. Any Git tool works alongside Canopy.

**IDE as the interface.** Canopy doesn't try to be a Git GUI. It orchestrates worktrees and opens your existing tools (VS Code, Cursor, Fork) in the right context.

**MCP-native.** Every CLI command is also an MCP tool. AI agents can operate your workspace through the same interface you use.

## Project Structure

```
src/canopy/
├── cli/main.py              # argparse entry point, all commands
├── workspace/
│   ├── config.py            # canopy.toml parser
│   ├── discovery.py         # repo auto-detection (worktree-aware)
│   ├── context.py           # context detection (where am I?)
│   └── workspace.py         # Workspace class, RepoState
├── git/
│   ├── repo.py              # ALL git subprocess calls (single-repo)
│   └── multi.py             # cross-repo operations
├── features/
│   └── coordinator.py       # feature lane lifecycle (worktree-smart)
└── mcp/
    └── server.py            # MCP server (22 tools, stdio transport)

tests/                       # 104 tests, ~1.5s
```

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT
