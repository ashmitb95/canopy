# Agents

How AI coding agents (Claude Code primarily; others by analogy) integrate with canopy.

## What ships

Three pieces, all installed in one step by `canopy init`:

1. **Canopy MCP server** (`canopy-mcp` binary) — 42 tools exposing every canopy operation. Registered in `<workspace>/.mcp.json`.
2. **`using-canopy` skill** at `~/.claude/skills/using-canopy/SKILL.md` — tells the agent *when* to prefer canopy MCP over raw bash.
3. **Per-workspace MCP config** in `<workspace>/.mcp.json` with `CANOPY_ROOT` set so the server scopes to the right workspace.

The MCP server makes the tools *available*; the skill makes the agent *prefer* them. Without the skill, the agent defaults to `Bash + git + gh` because that's what its training data shows.

## Install

Default path — runs as part of `canopy init`:

```bash
canopy init                  # discovers repos + writes canopy.toml
                             # + installs hooks + the skill + MCP config
                             # use --no-agent to skip the AI bits
```

Or standalone (re-run, repair, switch on later):

```bash
canopy setup-agent           # do both (skill + MCP)
canopy setup-agent --check   # status only, no changes
canopy setup-agent --skill-only
canopy setup-agent --mcp-only
canopy setup-agent --reinstall  # overwrite existing files
```

After install, restart Claude Code (or open a new session in the workspace). Tools appear as `mcp__canopy__triage`, `mcp__canopy__feature_state`, etc.

Verify:

```bash
canopy setup-agent --check
```

## Tool selection guide

The skill encodes this matrix; the agent reads it on session start. Mirror here for the human reader:

| What you want | Canopy tool | Don't use |
|---|---|---|
| What feature should I work on? | `mcp__canopy__triage` | per-repo `gh pr list` + manual grouping |
| Show me everything about a feature | `mcp__canopy__feature_state` | composing many reads |
| Switch / fix branches across repos | `mcp__canopy__realign` | `cd repo && git checkout` |
| Check HEAD alignment | `mcp__canopy__drift` | `git branch --show-current` per repo |
| PR review comments (temporally filtered) | `mcp__canopy__github_get_pr_comments` | `gh api .../comments` + custom filter |
| PR data (title, decision, draft) | `mcp__canopy__github_get_pr` | `gh pr view --json` per repo |
| Branch HEAD / divergence / upstream | `mcp__canopy__github_get_branch` | `cd && git status -b` |
| Linear issue | `mcp__canopy__linear_get_issue` | direct API |
| Run shell command in a specific repo | `mcp__canopy__run` | `cd /path && cmd` (path mistake risk) |
| Stash for a feature | `mcp__canopy__stash_save_feature` | raw `git stash push` |

## The daily loop

```
1. triage()                 → pick a feature from the prioritized list
2. feature_state(feature)   → get current state + next_actions
3. follow next_actions[0]   → primary CTA (canopy decided what to do next)
4. feature_state again      → confirm state advanced
5. repeat
```

Demo (output from a real test workspace, MCP-only — no bash):

```
STEP 1: triage
  • doc-1001-paired   priority=review_required
      test-api  PR#1  actionable=1
      test-ui   PR#1  actionable=1

STEP 2: feature_state("doc-1001-paired")
  state: ready_to_commit
  next:
    PRIMARY  commit({"feature": "doc-1001-paired"})

STEP 3: github_get_pr_comments("doc-1001-paired")
  total actionable: 2
  [test-api] src/app.py:18 (reviewer) — add a docstring with example response
  [test-ui]  src/UnarchiveButton.tsx:4 (reviewer) — prefer a discriminated union

STEP 4 (manual git switch elsewhere → drift)

STEP 5: feature_state("doc-1001-paired")
  state: drifted
  primary fix: realign({"feature": "doc-1001-paired"})

STEP 6: realign("doc-1001-paired")
  aligned: True
  test-ui: status=checkout_ok before=main after=doc-1001-paired

STEP 7: feature_state confirms ready_to_commit
```

`next_actions` is canopy's recommendation. Trust it unless you have a specific reason not to. Same data the [VSCode dashboard](https://marketplace.visualstudio.com/items?itemName=SingularityInc.canopy) renders as the primary button.

## Reading errors

Canopy errors come back as structured `BlockerError` / `FailedError`:

```json
{
  "status": "blocked",
  "code": "drift_detected",
  "what": "branches don't match feature lane 'doc-3029'",
  "expected": {...},
  "actual":   {...},
  "fix_actions": [
    {"action": "realign", "args": {"feature": "doc-3029"},
     "safe": true, "preview": "checkout doc-3029 in ui (clean)"}
  ]
}
```

`fix_actions` is ordered most-recommended first. Each entry has `safe: true|false`:
- `safe: true` → call directly to recover.
- `safe: false` → surface to the human first (might lose work or affect remote state).

When you see a `BlockerError`, read `fix_actions[0]` and decide whether to follow it. Don't ignore + retry the original call.

## External MCP servers

Canopy also acts as an MCP **client** — it spawns external MCP servers (Linear, GitHub) on demand. Two transports supported:

### stdio (subprocess)

For local npm/python servers:

```json
// .canopy/mcps.json or .mcp.json
{
  "github": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
    "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_..."}
  }
}
```

### HTTP + OAuth (browser flow)

For hosted servers like Linear's official MCP at `mcp.linear.app`:

```json
{
  "linear": {
    "type": "http",
    "url": "https://mcp.linear.app/mcp",
    "oauth": true
  }
}
```

First call opens the browser for OAuth; the token caches at `~/.canopy/mcp-tokens/linear.{client,tokens}.json` for subsequent calls. No API key required.

For GitHub specifically, canopy falls back to `gh` CLI when no MCP server is configured. Same return shapes either way. If neither is available, `BlockerError(code='github_not_configured')` includes platform-aware install hints.

## Beyond Claude Code

The `using-canopy` skill is a Claude-Code-specific convention (`~/.claude/skills/`). The MCP server itself works with any MCP-aware client (Cursor, Windsurf, custom integrations). For non-Claude clients, replicate the skill's content as a system prompt or rules file in your client's convention.

## Troubleshooting

```bash
canopy setup-agent --check     # is the skill installed? is MCP registered?
canopy hooks status            # are drift hooks installed in each repo?
canopy drift                   # what does canopy think vs reality?
```

If MCP tools don't appear in your agent session: restart the client (MCP servers are loaded once per session).

If `mcp__canopy__triage` returns `github_not_configured`: either install + auth `gh` (`brew install gh && gh auth login`), or add a `github` MCP server entry to `.canopy/mcps.json`.

If `mcp__canopy__linear_get_issue` opens a browser tab unexpectedly: that's the OAuth flow; complete the auth, the token caches and subsequent calls are silent.
