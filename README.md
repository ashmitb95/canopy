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
canopy worktree auth-flow

# Or link it to a Linear issue (fetches title via MCP)
canopy worktree payment-flow ENG-123

# Open in your IDE
canopy code auth-flow        # VS Code (multi-root workspace)
canopy cursor auth-flow      # Cursor
canopy fork auth-flow        # Fork (separate windows per repo)

# Work in your IDE... then commit from the feature directory
cd .canopy/worktrees/auth-flow
canopy stage "feat: add auth module"
#   api: a3f2b1c
#   ui: 7e8d4f2

# Check live worktree status
canopy worktree
#   Feature worktrees (2):
#   ──────────────────────────────────────────────────
#   auth-flow
#     api [auth-flow] (+2)
#     ui [auth-flow] (1 dirty)
#   ──────────────────────────────────────────────────
#   payment-flow  [ENG-123 — Add payment processing]
#     api [payment-flow]
#     ui [payment-flow]
```

## Commands

### Worktrees (primary workflow)

| Command | Description |
|---|---|
| `canopy worktree <name>` | Create feature with worktrees across all repos |
| `canopy worktree <name> <issue>` | Create + link to Linear issue (via MCP) |
| `canopy worktree` | Live status of all active worktrees |

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
| `canopy feature create --worktree <name>` | Create worktrees (same as `canopy worktree <name>`) |
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

All commands support `--json` for machine-readable output.

## Linear Integration

Canopy links features to Linear issues via MCP — no direct API dependency. Configure a Linear MCP server in `.canopy/mcps.json`:

```json
{
  "linear": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-linear"],
    "env": { "LINEAR_API_KEY": "lin_api_..." }
  }
}
```

Then `canopy worktree payment-flow ENG-123` spawns the Linear MCP, fetches the issue title and URL, creates the worktrees, and stores the link in `features.json`. If Linear MCP isn't configured, the issue ID is stored without fetching details.

## MCP Server

Canopy exposes all operations as an MCP server (23 tools) for AI agents:

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

Tools include: `workspace_status`, `worktree_create`, `worktree_info`, `feature_create`, `feature_status`, `stage`, `log`, `checkout`, `commit`, `branch_list`, `stash_save`, and more.

## MCP Client

Canopy is also an MCP **client** — it can spawn external MCP servers to fetch data. This powers the Linear integration and is extensible to any MCP server. Configured in `.canopy/mcps.json`:

```json
{
  "linear": { "command": "npx", "args": [...], "env": {...} },
  "github": { "command": "...", "args": [...] }
}
```

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

**MCP-client too.** Canopy spawns external MCP servers (Linear, GitHub, etc.) to fetch data. No direct API dependencies — everything goes through MCP.

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
├── integrations/
│   └── linear.py            # Linear issue fetching via MCP
└── mcp/
    ├── server.py            # MCP server (23 tools, stdio transport)
    └── client.py            # MCP client (call external MCP servers)

tests/                       # 130 tests, ~2s
```

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT
