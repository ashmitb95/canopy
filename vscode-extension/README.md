# Canopy for VSCode

Worktree-first workspace manager for multi-repo development. Coordinates Git worktrees across multiple repositories and surfaces them in a single, unified VSCode sidebar.

## Features

- **Activity bar entry** with four sections: Features, Worktrees, Changes (per repo), and Review Readiness.
- **Feature dashboard webview** showing branch state across all repos, Linear/GitHub status, recent commits, and cross-repo file overlap warnings.
- **Linear-aware "Create Feature" quick pick** that auto-suggests lane names from your open Linear issues.
- **Status bar** items for the active feature, repo count, and aggregate ahead/behind counts.
- **Live refresh** via file watchers on `.canopy/features.json` and worktree HEADs.

## Requirements

- The `canopy-mcp` Python entry point must be installed and on your `PATH` (or specify the full path in settings).
- A directory containing a `canopy.toml` workspace definition.

Install Canopy itself:

```bash
pip install canopy
```

## Settings

| Setting | Default | Description |
| --- | --- | --- |
| `canopy.canopyMcpPath` | `canopy-mcp` | Path to the `canopy-mcp` executable. |
| `canopy.refreshIntervalSeconds` | `30` | How often to poll Canopy for refreshed state. `0` disables periodic refresh. |

## How it works

The extension is a thin TypeScript shell over the existing `canopy-mcp` MCP server. On activation it spawns one `canopy-mcp` process per workspace and routes every UI action through the 30+ MCP tools that already power the Canopy CLI. No proprietary protocol — just MCP over stdio.

## License

MIT
