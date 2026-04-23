# MCP Integration

Canopy is both an MCP **server** (every CLI operation is exposed as a tool) and an MCP **client** (external integrations like Linear and GitHub work by spawning their MCP servers — no direct API calls).

## Server

```bash
canopy-mcp   # starts the server over stdio
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

### Tools

| Tool | Description |
|---|---|
| `workspace_status` | Full workspace status across all repos |
| `workspace_context` | Detect canopy context from a directory path |
| `workspace_config` | Read or write workspace settings in canopy.toml |
| `feature_create` | Create a new feature lane across repos |
| `feature_list` | List all active feature lanes with repo states |
| `feature_status` | Detailed status for a feature lane |
| `feature_switch` | Switch to a feature lane across repos (alias-aware) |
| `feature_diff` | Aggregate diff for a feature lane across repos |
| `feature_changes` | Per-repo M/A/D/? change lists for a feature |
| `feature_merge_readiness` | Check if a feature is ready to merge |
| `feature_paths` | Get working directory paths for each repo in a feature |
| `feature_done` | Clean up a feature — remove worktrees, delete branches, archive |
| `worktree_create` | Create worktrees for a feature, optionally linked to a Linear issue |
| `worktree_info` | Live worktree status across the workspace |
| `checkout` | Checkout a branch across repos |
| `preflight` | Context-aware pre-commit quality gate — stages + runs hooks, does not commit |
| `log` | Interleaved commit log across repos, sorted by date |
| `sync` | Pull default branch, rebase feature branches |
| `branch_list` | List branches across repos |
| `branch_delete` | Delete a branch across repos |
| `branch_rename` | Rename a branch across repos |
| `stash_save` | Stash uncommitted changes across repos |
| `stash_pop` | Pop stash across repos |
| `stash_list` | List stash entries across repos |
| `stash_drop` | Drop a stash entry across repos |
| `review_status` | Check if PRs exist for a feature |
| `review_comments` | Fetch unresolved PR review comments for a feature |
| `review_prep` | Run pre-commit hooks and stage changes for a feature |
| `workspace_reinit` | Rescan repos and regenerate `canopy.toml` |
| `linear_my_issues` | Fetch assigned Linear issues via the configured Linear MCP |

## Client

Rather than adding direct API integrations (Linear SDK, GitHub SDK, etc.), canopy spawns external MCP servers as subprocesses and calls their tools via the standard MCP protocol. This means:

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
