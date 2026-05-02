# MCP

Canopy is both an MCP **server** (every operation exposed as a tool — agents drive canopy through it) and an MCP **client** (external integrations like Linear and GitHub spawn their MCP servers; canopy never talks to those APIs directly).

## Server

```bash
canopy-mcp   # starts the server over stdio
```

Register in any MCP-compatible client. `canopy init` writes this entry into the workspace's `.mcp.json` automatically:

```json
{
  "mcpServers": {
    "canopy": {
      "command": "canopy-mcp",
      "args": [],
      "env": { "CANOPY_ROOT": "/path/to/workspace" }
    }
  }
}
```

`CANOPY_ROOT` scopes the server to one workspace. To use canopy in multiple workspaces simultaneously, register separate entries with different `CANOPY_ROOT` values (or scope MCP per-project via `.mcp.json` at each workspace root).

### Tools (43)

Grouped by topic. Every tool is alias-aware where it accepts a feature input.

#### Meta

| Tool | Description |
|---|---|
| `version` | `{cli_version, mcp_version, schema_version}` for the doctor handshake. The extension calls this once at startup; the doctor uses it to flag CLI/MCP version drift. |
| `doctor` | Diagnose state-file integrity + install staleness; optionally repair. 16 categories, single tool. **The recovery entry point** — when any other call returns an unexpected error, agents should call `doctor` first to see whether state is corrupted. Returns `{issues, summary, fixed, skipped, ...}`. |

#### Workspace

| Tool | Description |
|---|---|
| `workspace_status` | Full workspace status across all repos |
| `workspace_context` | Detect canopy context from a directory path |
| `workspace_config` | Read or write workspace settings |
| `workspace_reinit` | Rescan repos and regenerate `canopy.toml` |

#### Feature

| Tool | Description |
|---|---|
| `feature_create` | Create a new feature lane across repos |
| `feature_list` | List active feature lanes |
| `feature_status` | Detailed status for a feature lane |
| `feature_diff` | Aggregate diff for a feature lane |
| `feature_changes` | Per-repo file changes for a feature |
| `feature_merge_readiness` | Pre-merge sanity check |
| `feature_paths` | Working directory paths per repo |
| `feature_done` | Clean up worktrees + branches + archive |
| `feature_link_linear` | Attach a Linear issue to a feature |
| `feature_state` | **Dashboard backend.** Returns `{state, summary, next_actions, warnings}`. State ∈ `{drifted, needs_work, in_progress, ready_to_commit, ready_to_push, awaiting_review, approved, no_prs}`. See [concepts.md](concepts.md#3-the-8-state-machine). |

#### Action (Wave 2)

| Tool | Description |
|---|---|
| `triage` | Prioritized list of features needing attention. Cross-repo PR fetch, grouped by feature, sorted by review state. |
| `switch` | **The focus primitive (Wave 2.9).** Promote a feature to the canonical slot. Active rotation (default) evacuates the previously-canonical feature to a warm worktree; `release_current=True` (wind-down) sends it to cold with a feature-tagged stash. Cap-reached blocker surfaces explicit fix actions. See [docs/concepts.md §4](concepts.md#4-the-canonical-slot-model). |
| `drift` | Cached alignment view from `.canopy/state/heads.json`. Fast, hook-driven. |

#### Read primitives (alias-aware)

| Tool | Description |
|---|---|
| `linear_get_issue` | Fetch a Linear issue. Accepts ID (`SIN-412`) or feature alias (resolves via lane's `linear_issue`). |
| `github_get_pr` | PR data per repo. Accepts feature alias, `<repo>#<n>`, or PR URL. |
| `github_get_branch` | Branch HEAD/divergence/upstream per repo. Accepts feature or `<repo>:<branch>`. |
| `github_get_pr_comments` | Temporally classified review comments. Same alias forms as `github_get_pr`. |
| `linear_my_issues` | List user's open Linear issues. |

#### Run / preflight

| Tool | Description |
|---|---|
| `run` | Run a shell command in a canopy-managed repo. Pass `repo` (and optional `feature`); canopy resolves the cwd. |
| `preflight` | Run pre-commit hooks per repo. Records result to `.canopy/state/preflight.json` for `feature_state`. |
| `review_status` / `review_comments` / `review_prep` | Older review composites. Prefer `feature_state` + `github_get_pr_comments`. |

#### Stash (feature-aware)

| Tool | Description |
|---|---|
| `stash_save_feature` | Stash with feature tag (incl. untracked). |
| `stash_list_grouped` | List grouped by feature tag. |
| `stash_pop_feature` | Pop most recent matching tagged stash per repo. |
| `stash_save` / `stash_pop` / `stash_list` / `stash_drop` | Plain (non-feature-tagged) stash ops. |

#### Worktree / branch / log

| Tool | Description |
|---|---|
| `worktree_create` | Create worktrees for a feature (optionally linked to a Linear issue) |
| `worktree_info` | Live worktree state |
| `branch_list` / `branch_delete` / `branch_rename` | Branch ops across repos |
| `log` | Interleaved commit log across repos |
| `checkout` | Checkout a branch across repos |
| `sync` | Pull default + rebase feature branches |

## Client

Canopy spawns external MCP servers on demand. Two transports.

### stdio (subprocess)

For local servers (npm, python, etc.):

```json
// .canopy/mcps.json or .mcp.json
{
  "github": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
    "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_..." }
  }
}
```

The client module (`canopy.mcp.client`) wraps the MCP SDK's `stdio_client` + `ClientSession`. Sync wrapper handles event loop management for CLI use.

### HTTP + OAuth (browser flow)

For hosted servers like Linear's official MCP — no API key needed:

```json
{
  "linear": {
    "type": "http",
    "url": "https://mcp.linear.app/mcp",
    "oauth": true
  }
}
```

First call opens the browser to the OAuth authorize URL; canopy spins up a one-shot HTTP server on `localhost:33418` to capture the redirect. Tokens cache at `~/.canopy/mcp-tokens/<server>.{client,tokens}.json`. Subsequent calls reuse the cached token silently.

For HTTP servers that use header auth instead of OAuth:

```json
{
  "some-server": {
    "type": "http",
    "url": "https://example.com/mcp",
    "headers": { "Authorization": "Bearer ..." }
  }
}
```

### gh CLI fallback for GitHub

If no `github` MCP server is configured, canopy falls back to the user's local `gh` CLI for GitHub operations. Same return shapes either way; calling code doesn't branch.

If neither is available:

```
github_not_configured
  Install + auth gh CLI:  brew install gh && gh auth login   (macOS)
                          (platform-aware install hint per OS)
  Or configure github MCP in .canopy/mcps.json
```

## Skill (using-canopy)

The MCP server makes tools available; the [`using-canopy`](../src/canopy/agent_setup/skill.md) skill teaches the agent *when* to prefer them. Without the skill, agents default to raw `Bash + git + gh` (training data).

Installed by `canopy init` (or standalone via `canopy setup-agent`) at `~/.claude/skills/using-canopy/SKILL.md`. Loads in any new Claude Code session targeting a workspace where canopy MCP is registered.

See [agents.md](agents.md) for the full integration story.

## Architectural rules

- Canopy never imports external APIs directly. Linear, GitHub, etc. all flow through MCP (or `gh` CLI fallback for GitHub).
- The MCP server (`canopy.mcp.server`) is a thin wrapper. Business logic lives in `canopy.actions.*`, `canopy.features.*`, `canopy.git.*`. Adding a tool = registering an existing function under `@mcp.tool()`.
- Token storage is opt-in per server (`oauth: true` enables `~/.canopy/mcp-tokens/`); stdio servers carry credentials in `env`.
