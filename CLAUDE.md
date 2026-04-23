# Canopy — Claude Code Context

## What This Project Is

Canopy is a worktree-first workspace manager for multi-repo development. It coordinates Git worktrees across multiple repositories, opens them in your IDE, and exposes everything as an MCP server for AI agents. Feature lanes map to real Git branches and worktrees — no proprietary abstractions.

## Architecture

```
src/canopy/
├── cli/main.py              # argparse entry point, all commands
├── workspace/
│   ├── config.py            # canopy.toml parser (RepoConfig, WorkspaceConfig)
│   ├── discovery.py         # auto-detect repos + worktrees, generate toml
│   ├── context.py           # context detection (feature_dir, repo_worktree, repo, workspace_root)
│   └── workspace.py         # Workspace class, RepoState dataclass
├── git/
│   ├── repo.py              # ALL git subprocess calls go here (single-repo)
│   └── multi.py             # cross-repo operations (calls repo.py)
├── features/
│   └── coordinator.py       # FeatureLane, FeatureCoordinator (worktree-smart lifecycle)
├── integrations/
│   └── linear.py            # Linear issue fetching via MCP client
└── mcp/
    ├── server.py            # MCP server — 23 tools, stdio transport
    └── client.py            # MCP client — call external MCP servers (Linear, etc.)
```

## Key Conventions

- **git.repo is the only module that shells out to git.** Everything else calls git.repo functions. This makes the git layer replaceable.
- **All CLI commands support `--json`.** This is the contract between the CLI, the MCP server, and any future GUI.
- **Feature lanes use real Git branches and worktrees.** No virtual branches. A feature lane named "auth-flow" creates actual `auth-flow` branches and optionally real worktrees.
- **Feature metadata lives in `.canopy/features.json`** in the workspace root.
- **Worktrees live in `.canopy/worktrees/<feature>/<repo>/`** when created with `--worktree`.
- **canopy.toml is the workspace definition.** Source of truth for which repos are in the workspace.
- **Context detection** (`workspace/context.py`) walks up from cwd to determine feature, repo, and branch — powers `canopy stage` and other context-aware commands.
- **MCP client** (`mcp/client.py`) enables canopy to call external MCP servers. Config lives in `.canopy/mcps.json`. Currently powers Linear integration.
- **Integrations** (`integrations/`) are always MCP-based — canopy never calls external APIs directly. It spawns the relevant MCP server, calls a tool, and uses the result.
- **Linear integration** (`integrations/linear.py`) fetches issue data via a configured Linear MCP server. `FeatureLane` stores `linear_issue`, `linear_title`, `linear_url` in `features.json`.

## Build & Test

```bash
pip install -e ".[dev]"
pytest tests/ -v          # 130 tests, ~2s
```

## Test Fixtures

Tests use real temporary Git repos created in pytest fixtures (see `tests/conftest.py`):
- `workspace_dir` — bare workspace with api/ and ui/ repos on main
- `workspace_with_feature` — workspace with `auth-flow` branches and commits in both repos
- `canopy_toml` — workspace with a canopy.toml already written

## Important Implementation Details

- **Python 3.10+ compat:** Uses `tomli` on 3.10, `tomllib` on 3.11+. See config.py import.
- **Porcelain parsing:** `git status --porcelain` output has significant leading spaces. The parser in `repo.py` uses raw stdout (not `.strip()`) to preserve them.
- **Feature discovery:** `Workspace.active_features()` detects branches that exist in 2+ repos, even without `canopy feature create`.
- **Overlap detection:** `git.multi.find_type_overlaps()` matches files by basename across repos.
- **Worktree detection:** `discovery.py` recognizes `.git` files (not just directories) to identify linked worktrees. `RepoConfig.is_worktree` and `worktree_main` track the relationship.
- **Context detection:** `context.py` parses the `.canopy/worktrees/<feature>/<repo>/` path structure to determine what feature/repo you're working in.
- **MCP server:** Uses `mcp` Python SDK with FastMCP. 23 tools exposed via stdio transport. `CANOPY_ROOT` env var sets the workspace path.

## MCP Server

The MCP server at `mcp/server.py` exposes every canopy operation as a tool:

```
workspace_status, workspace_context,
feature_create, feature_list, feature_status, feature_switch, feature_diff, feature_merge_readiness, feature_paths,
checkout, commit, stage, log,
branch_list, branch_delete, branch_rename,
stash_save, stash_pop, stash_list, stash_drop,
worktree_info, worktree_create, sync
```

Run with: `canopy-mcp` (entry point) or `python -m canopy.mcp.server`.

## MCP Client

Canopy is also an MCP client — it spawns external MCP servers to fetch data. This is how all integrations work (no direct API calls).

Config lives in `.canopy/mcps.json`:

```json
{
  "linear": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-linear"],
    "env": {"LINEAR_API_KEY": "lin_api_..."}
  }
}
```

The client module (`mcp/client.py`) uses the `mcp` SDK's `ClientSession` + `stdio_client` to spawn the server process, call tools, and return results. Synchronous wrapper handles event loop management for CLI use.
