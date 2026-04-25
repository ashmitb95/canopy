# Agents

How AI coding agents (Claude Code primarily; others by analogy) integrate with canopy.

## What ships

Three pieces, all installed in one step by `canopy init`:

1. **Canopy MCP server** (`canopy-mcp` binary) — 41 tools exposing every canopy operation. Registered in `<workspace>/.mcp.json`.
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
| Switch a feature into main (the focus primitive) | `mcp__canopy__switch` | `cd repo && git checkout`, or guessing paths |
| Hibernate the current focus + start something new | `mcp__canopy__switch(feature, release_current=True)` | manual stash + checkout dance |
| Check HEAD alignment | `mcp__canopy__drift` | `git branch --show-current` per repo |
| PR review comments (temporally filtered) | `mcp__canopy__github_get_pr_comments` | `gh api .../comments` + custom filter |
| PR data (title, decision, draft) | `mcp__canopy__github_get_pr` | `gh pr view --json` per repo |
| Branch HEAD / divergence / upstream | `mcp__canopy__github_get_branch` | `cd && git status -b` |
| Linear issue | `mcp__canopy__linear_get_issue` | direct API |
| Run shell command in a specific repo | `mcp__canopy__run` | `cd /path && cmd` (path mistake risk) |
| Stash for a feature | `mcp__canopy__stash_save_feature` | raw `git stash push` |

### Vocabulary note: hibernate ⇄ release_current

The user-facing word for "send the current focus to branch-only with a feature-tagged stash" is **hibernate**. The dashboard button says it. The CLI flag will eventually say it. But the actual MCP parameter today is **`release_current=True`** (kept as the API name for backwards compat).

When you describe what you're about to do to the user, prefer the user-facing word:

  - ✓ "I'll **hibernate** SIN-12 so SIN-15 can take main."
  - ✗ "I'll set release_current=true on SIN-12."

Same operation. Different surface vocab. A future canopy release may add `hibernate=true` as an alias for `release_current=true` — until then, when calling the tool, use `release_current=True`.

A feature in the resulting state is **hibernating** (synonyms in the wild: "branch only", "released to cold", "wound down" — all the same thing).

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
  canonical_feature: SIN-12-search
  • SIN-12-search        is_canonical=true   physical_state=canonical
      backend  PR#7  actionable=1
      frontend PR#3  actionable=1
  • SIN-13-empty-state   is_canonical=false  physical_state=warm
      frontend PR#4  actionable=0
  • SIN-14-stale-count   is_canonical=false  physical_state=cold

STEP 2: feature_state("SIN-12-search")
  state: ready_to_commit
  next:
    PRIMARY  commit({"feature": "SIN-12-search"})

STEP 3: github_get_pr_comments("SIN-12-search")
  total actionable: 2
  [backend]  src/app.py:18 (reviewer) — add a docstring with example response
  [frontend] src/EmptyState.tsx:4 (reviewer) — prefer a discriminated union

STEP 4: agent decides to pivot to SIN-13-empty-state (currently warm)
  switch({"feature": "SIN-13-empty-state"})
    mode=active_rotation
    previously_canonical=SIN-12-search   (evacuated to warm worktree)
    per_repo_paths.frontend=/.../canopy-test/frontend  (now on SIN-13)

STEP 5: feature_state("SIN-13-empty-state") confirms in_progress
```

`next_actions` is canopy's recommendation. Trust it unless you have a specific reason not to. Same data the [VSCode dashboard](https://marketplace.visualstudio.com/items?itemName=SingularityInc.canopy) renders as the primary button.

## Reading errors

Canopy errors come back as structured `BlockerError` / `FailedError`:

```json
{
  "status": "blocked",
  "code": "worktree_cap_reached",
  "what": "adding 'SIN-12-search' as warm would exceed warm_slot_cap=2",
  "expected": {"warm_slot_cap": 2},
  "actual":   {"warm_now": ["SIN-13-empty-state", "SIN-14-stale-count"]},
  "fix_actions": [
    {"action": "switch",
     "args": {"feature": "SIN-15-cache", "release_current": true},
     "safe": false,
     "preview": "wind-down mode: SIN-12-search goes cold (with stash), no eviction needed"},
    {"action": "switch",
     "args": {"feature": "SIN-15-cache", "evict": "SIN-14-stale-count"},
     "safe": false,
     "preview": "evict LRU warm worktree 'SIN-14-stale-count' to cold"},
    {"action": "workspace_config",
     "args": {"max_worktrees": 3},
     "safe": true,
     "preview": "raise warm_slot_cap to 3"}
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
