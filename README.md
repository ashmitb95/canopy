# Canopy

Workspace-first development orchestrator. Coordinates Git across multiple repositories as a single logical unit.

## The Problem

Modern products span multiple repos — a React frontend, Python API, shared types, infrastructure. Developers working on a single feature make coordinated changes across repos, but every tool treats each repo as an island. Branch creation, status checking, diffing, and syncing are all manual, per-repo operations.

## What Canopy Does

Canopy introduces **workspaces** (a parent folder containing related repos) and **feature lanes** (a coordination primitive that spans repos). A feature lane named `auth-flow` maps to a real Git branch of the same name in each participating repo.

```
my-product/
├── canopy.toml          ← workspace definition
├── api/                 ← Python backend (git repo)
├── ui/                  ← React frontend (git repo)
└── .canopy/
    └── features.json    ← feature lane metadata
```

## Quick Start

```bash
# Install
cd canopy/
pip install -e .

# Initialize a workspace (auto-detects repos)
cd ~/my-product/
canopy init

# Check status across all repos
canopy status

# Create a feature lane (creates branches in all repos)
canopy feature create auth-flow

# Switch to it
canopy feature switch auth-flow

# See aggregate diff across repos
canopy feature diff auth-flow

# Detailed status with merge readiness
canopy feature status auth-flow

# Pull + rebase all repos
canopy sync
```

## Commands

| Command | Description |
|---|---|
| `canopy init` | Auto-detect repos, generate `canopy.toml` |
| `canopy status` | Cross-repo status (branches, divergence, dirty files) |
| `canopy feature create <name>` | Create matching branches across repos |
| `canopy feature list` | List active feature lanes |
| `canopy feature switch <name>` | Checkout feature branch in all repos |
| `canopy feature diff <name>` | Aggregate diff with type overlap detection |
| `canopy feature status <name>` | Detailed status + merge readiness check |
| `canopy sync` | Pull default branch + rebase features across repos |

All commands support `--json` for machine-readable output.

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

`canopy init` generates this automatically by scanning subdirectories for Git repos.

## Key Design Decisions

**Real Git branches only.** Feature lanes map directly to Git branches. No proprietary abstractions. Any Git tool can see and work with Canopy-created branches.

**Additive, not exclusive.** Canopy works alongside Fork, GitKraken, the Git CLI, or any other tool. It never locks you in.

**CLI-first.** The CLI is the core. A Tauri desktop app is planned as a visual layer on top, communicating with the CLI via JSON-over-stdio.

## Project Structure

```
canopy/
├── src/canopy/
│   ├── cli/main.py              # argparse entry point
│   ├── workspace/
│   │   ├── config.py            # canopy.toml parser
│   │   ├── discovery.py         # repo auto-detection
│   │   └── workspace.py         # Workspace orchestration class
│   ├── git/
│   │   ├── repo.py              # single-repo Git wrappers
│   │   └── multi.py             # cross-repo Git operations
│   └── features/
│       └── coordinator.py       # feature lane lifecycle
└── tests/                       # 50 tests
```

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Roadmap

- **Phase 0** (done): CLI core — workspace model, feature lanes, cross-repo ops
- **Phase 1**: Tauri app shell + feature lane dashboard
- **Phase 2**: Diff views (staged/unstaged, hunk staging) + basic commit tree
- **Phase 3**: Worktree intelligence + knowledge graph integration

## License

MIT
