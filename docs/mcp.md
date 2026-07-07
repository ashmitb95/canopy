# MCP

Canopy is both an MCP **server** (the agent drives canopy through it) and an MCP **client** (external integrations like Linear and GitHub spawn their own MCP servers; canopy never talks to those APIs directly).

The 4.0 line — *the great distillation* — splits canopy into **two surfaces**:

- **The agent contract (this document): 15 MCP tools.** The agent sees only what it needs to work safely and stay oriented — path-safety, registry, focus, safe git ops, recovery. It never names a directory; it names semantic context (`feature`, `repo`, alias) and canopy resolves paths internally. Its context budget goes to comprehension, not orchestration.
- **The human / dashboard management surface: CLI `--json`.** PR triage, review-comment classification, bot rollups, ship, historian, resume briefs, conflict detection, Linear/GitHub reads — the "management" work — is **not** on the agent surface. It lives in `canopy/management/` and is reached by a human (or the dashboard) via `canopy <cmd> --json`. See [commands.md](commands.md).

Pre-4.0, canopy exposed dozens of MCP tools and the agent spent context orchestrating PR management instead of understanding code. Nothing was deleted — management moved *off* the agent surface. The agent sees less so it can understand more.

## Server

```bash
canopy-mcp                    # entry point — starts the server over stdio
python -m canopy.mcp.server   # equivalent
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

## The 15 agent tools

The complete agent surface. Every tool is alias-aware where it accepts a feature input (feature name, Linear ID, `<repo>#<n>`, PR URL, `<repo>:<branch>`, or slot id). Grouped by role in the daily loop.

### Meta

| Tool | Purpose |
|---|---|
| `version` | Report canopy versions (`cli`/`mcp`/`schema`) for the `doctor` staleness handshake. |

### Registry

| Tool | Purpose |
|---|---|
| `context` | **The registry — feature ↔ repo ↔ branch ↔ path ↔ state in a single read.** Tier 1 (default) is local + instant. Set `remote=True` only when the task depends on remote state (addressing PR comments, checking CI) — it adds the live PR + CI + origin-divergence overlay at network cost. Supersedes the old `workspace_status`/`workspace_context`/`feature_list`/`feature_status`/`slots`. |
| `start` | Begin new work on a feature — lazy, zero repos until you `join`. |
| `join` | Join a repo to the active feature (creates + registers its branch). |

### Focus / slots

| Tool | Purpose |
|---|---|
| `switch` | Promote a feature into the canonical slot — the only place to *run* full-stack. If the target is already warm, uses a fast stash → checkout → pop path per repo; if cold, the outgoing feature's slot is reused. See [concepts.md §4](concepts.md#4-the-slot-model). |
| `reclaim` | Free warm slots whose PR merged (clean-only; dirty slots are surfaced as advisories, never touched). Slots return to the free pool for reuse. |

### Safe git ops

| Tool | Purpose |
|---|---|
| `run` | Run a shell command in a canopy-managed repo with directory resolution — pass `repo` (and optional `feature`) and canopy resolves the cwd. This is also how the agent reaches raw git plumbing path-safely (`run "git …"`). |
| `commit` | Commit across every in-scope repo in a feature lane with a single message. Defaults to the canonical feature; pre-flight verifies each repo is on its expected branch, else raises `BlockerError(code='wrong_branch')`. Commit-only in 4.0 (the pre-4.0 `--address` thread-resolution path was stripped). |
| `push` | Push the feature branch in every in-scope repo. |
| `preflight` | Context-aware pre-commit quality gate. Records the result to `.canopy/state/preflight.json`. |

### Recovery

| Tool | Purpose |
|---|---|
| `doctor` | Diagnose workspace + install integrity across 21 typed diagnostic codes (11 categories); optionally repair (`fix=True`). Returns `{issues, summary, fixed, skipped, ...}`. **The recovery entry point** — when any other call returns an unexpected error, call `doctor` first to see whether state is corrupted. |
| `drift` | Compare recorded HEAD state (`.canopy/state/heads.json`) vs feature-lane expectations. Fast, hook-driven cached path. |

### WIP + workable slots

| Tool | Purpose |
|---|---|
| `stash_save_feature` | Stash dirty changes (including untracked) with a feature tag. |
| `stash_pop_feature` | Pop the most recent feature-tagged stash per repo. |
| `worktree_bootstrap` | Bootstrap a feature's worktrees to workable — env-file copy, `install_cmd`, IDE `.code-workspace` generation. |

## Where the management tools went

The pre-4.0 review/triage/ship/historian/bots/threads/Linear-reads tools are **no longer MCP tools**. They were not deleted — they moved to `canopy/management/` and are reached by humans and dashboards via `canopy <cmd> --json` (see [commands.md](commands.md)). The distillation is on the **agent (MCP) surface only**; the CLI kept every one of these commands, each with `--json`.

- **Moved to `canopy/management/` (CLI `--json`, no MCP):** `review_status` / `review_comments` / `review_prep`, `pr_checks`, `draft_replies`, `github_get_pr` / `_comments` / `_branch`, `bot_comments_status`, `reply_to_thread`, `resolve_thread`, the `historian_*` set, `feature_memory`, `feature_resume`, `ship`, `conflicts`, `triage`, the Linear/issue reads, `feature_link_linear`, `feature_state`, `feature_diff`, `feature_changes`, `feature_merge_readiness`, `workspace_context`, `workspace_status`.
- **Commented off the MCP surface (reversible — one uncomment away; code intact in `actions/`):** `slots`, `feature_list` / `_status` / `_paths` / `_create` / `_done`, `workspace_config` / `_reinit`, `slot_load` / `_clear` / `_swap`, `migrate_slots`, and the git-plumbing `checkout` / `log` / `sync` / `branch_*` / raw `stash_*` / `worktree_info` / `worktree_create`. Rationale: git plumbing is reachable path-safely via `run "git …"`, and the feature/slot lifecycle reads are subsumed by `context`.

If a doc lists the agent's tools, it lists the 15 above — not these.

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

The client module (`canopy.mcp.client`) wraps the MCP SDK's `stdio_client` + `ClientSession`. A sync wrapper handles event-loop management for CLI use.

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

First call opens the browser to the OAuth authorize URL; canopy spins up a one-shot HTTP server on `localhost:33418` to capture the redirect. Tokens cache at `~/.canopy/mcp-tokens/<server>.{client,tokens}.json`. Subsequent calls reuse the cached token silently, auto-refreshing as long as the refresh token is valid.

> **Heads up — OAuth needs a TTY.** The first-call browser flow requires a TTY-attached process (Claude Code, your shell, the canopy CLI). If you invoke an MCP method *headlessly* and the cached token is missing or expired, the OAuth handshake will hang waiting for a redirect that can never arrive. For tests, exercise providers directly via their classes with `call_tool` mocked at the module boundary, or rely on a pre-authorised session.

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

If no `github` MCP server is configured, canopy falls back to the user's local `gh` CLI for GitHub operations (`integrations/github.py`). Same return shapes either way; calling code doesn't branch.

If neither is available, canopy raises `BlockerError(code='github_not_configured')` with a platform-aware install hint:

```
github_not_configured
  Install + auth gh CLI:  brew install gh && gh auth login          (macOS)
                          winget install --id GitHub.cli && gh auth login   (Windows)
                          (platform-aware install hint per OS)
  Or configure github MCP in .canopy/mcps.json
```

(GitHub reads themselves are now management-side / CLI `--json`; the fallback infra is shared.)

## Skill (using-canopy)

The MCP server makes the 15 tools available; the [`using-canopy`](../src/canopy/agent_setup/skills/using-canopy/SKILL.md) skill teaches the agent *when* to prefer them. Without the skill, agents default to raw `Bash + git + gh` (training data).

Installed by `canopy init` (or standalone via `canopy setup-agent`) at `~/.claude/skills/using-canopy/SKILL.md`. Loads in any new Claude Code session targeting a workspace where canopy MCP is registered.

See [agents.md](agents.md) for the full integration story.

## Architectural rules

- **Same JSON shape across surfaces.** CLI, MCP, and any GUI share one JSON contract per operation. `--json` on the CLI *is* the dashboard contract; the MCP tool returns the same shape.
- **Actions return structured errors.** `BlockerError(code, what, expected, actual, fix_actions, details)`. The CLI renders via `cli/render.py`; MCP returns `to_dict()`. Same shape, two consumers.
- **The MCP server is a thin wrapper.** `canopy.mcp.server` holds no business logic — it lives in `canopy.actions.*`, `canopy.features.*`, `canopy.git.*`. Adding a tool = registering an existing function under `@mcp.tool()`.
- **Agent-core imports nothing from `canopy.management`.** `actions/`, `features/`, and `agent/` must never import the management surface. This boundary is enforced statically by `tests/test_import_boundary.py` (a source scan that catches lazy/function-local imports too).
- **Canopy never imports external APIs directly.** Linear, GitHub, etc. all flow through MCP (or the `gh` CLI fallback for GitHub).
- **Token storage is opt-in per server.** `oauth: true` enables `~/.canopy/mcp-tokens/`; stdio servers carry credentials in `env`.
