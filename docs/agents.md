# Agents

How an AI coding agent (Claude Code primarily; other MCP clients by analogy) works with canopy 4.0.

Canopy 4.0 splits into **two surfaces** (see [concepts.md](concepts.md)):

- **The agent contract** — a **15-tool MCP server** plus **enforcement hooks**. The agent sees only what it needs to work safely and stay oriented: path-safety, the registry, focus, safe git ops, recovery. It never names a directory — it names semantic context (`feature`, `repo`, alias) and canopy resolves paths internally.
- **The management surface** — PR triage, review-comment classification, bot rollups, ship, historian, resume briefs, conflict detection, Linear/GitHub reads. This is **human/dashboard** work, reached via `canopy <cmd> --json` (see [commands.md](commands.md)). **It is not on the agent's MCP surface.**

The rule to internalize: *the agent sees less so it can understand more.* Its context budget goes to comprehension, not orchestration. This doc is about the agent surface.

## What ships

Three pieces, installed by `canopy setup-agent`:

1. **The canopy MCP server** (`canopy-mcp` binary) — **15 tools** (below). Registered in `<workspace>/.mcp.json`.
2. **Enforcement hooks** — a PreToolUse git gate + a SessionStart brief, written into `<workspace>/.claude/settings.json`. These are the enforcement half of "the agent can't `cd` to the wrong place."
3. **The `using-canopy` skill** at `~/.claude/skills/using-canopy/SKILL.md` — tells the agent *when* to prefer canopy MCP over raw bash/git/gh. (Opt-in `augment-canopy` for per-workspace tuning.)

The MCP server makes the tools *available*; the hooks make wrong-path work *impossible*; the skill makes the agent *prefer* the right tool. Without the skill, an agent defaults to `Bash + git + gh` because that's what its training data shows.

### The 15 agent tools

| Group | Tools | Purpose |
|---|---|---|
| **Meta** | `version` | version handshake for `doctor` staleness checks |
| **Registry** | `context`, `start`, `join` | the single-read workspace map; lazily start a feature; register a repo into the active feature |
| **Focus / slots** | `switch`, `reclaim` | promote a feature into trunk (the run target); free a warm slot whose PR merged |
| **Safe git ops** | `run`, `commit`, `push`, `preflight` | path-safe shell exec; feature-scoped multi-repo commit; push; pre-commit gate |
| **Recovery** | `doctor`, `drift` | integrity check + repair; branch-drift detection |
| **WIP + workable slots** | `stash_save_feature`, `stash_pop_feature`, `worktree_bootstrap` | feature-tagged stash save/pop; make a warm slot workable (env/deps/hooks/IDE) |

`context` is **the** registry read — feature ↔ repo ↔ branch ↔ path ↔ state — with a **local tier** (instant) and a **remote tier** (PR/CI overlay, opt-in). It supersedes the pre-4.0 `workspace_status` / `workspace_context` / `feature_list` / `feature_status` / `slots` reads.

> **What is NOT an agent tool.** The management operations — `triage`, `review`, `ship`, `resume`, `conflicts`, `bot-status`, historian, PR/issue/comment reads, thread resolve/reply — are **not** MCP tools. They live in `canopy/management/` and are reached by the human or dashboard via `canopy <cmd> --json`. Do not wire the agent to call them; they don't exist on the MCP surface. If you find yourself wanting `feature_resume` or `github_get_pr_comments`, use `context` (with the remote overlay) and the reads it returns instead.

### Bundled skills

| Name | Default? | Purpose |
|---|---|---|
| `using-canopy` | ✅ always | Prefer canopy MCP tools over raw git/gh; work in the slot model; recover via `canopy doctor`. |
| `augment-canopy` | opt-in | Per-workspace customization — tune the `[augments]` block in canopy.toml (preflight command, bot-author list, etc.). Install with `canopy setup-agent --skill augment-canopy`. See [workspace.md](workspace.md). |

## Install

```bash
canopy setup-agent                 # install skill + MCP config
canopy setup-agent --hooks         # also install the enforcement hooks
canopy setup-agent --check         # status only, no changes
```

What each flag does:

| Flag | Effect |
|---|---|
| (none) | install the `using-canopy` skill **and** the `.mcp.json` canopy entry |
| `--hooks` | additionally merge the PreToolUse gate + SessionStart brief into `<workspace>/.claude/settings.json` |
| `--skill NAME` | install an extra bundled skill (e.g. `augment-canopy`); repeatable |
| `--skill-only` / `--mcp-only` | install just one of the two default pieces |
| `--reinstall` | overwrite existing files even if foreign or current |
| `--check` | report what's installed (skill, MCP, hooks) without changing anything |

`canopy init` installs the skill + MCP config as part of workspace setup (and the per-repo drift post-checkout hooks). The Claude Code **enforcement** hooks are opt-in via `setup-agent --hooks`.

After install, **restart Claude Code** (or open a new session in the workspace) — MCP servers and hooks load once per session. Tools then appear as `mcp__canopy__context`, `mcp__canopy__switch`, etc.

Verify:

```bash
canopy setup-agent --check     # skill / MCP / hooks status
```

## The enforcement layer

Two Claude Code hooks, installed into `<workspace>/.claude/settings.json` by `setup-agent --hooks`. Together they make "the agent can't `cd` to the wrong repo or commit from the parent dir" true by construction, not by convention.

### PreToolUse git gate (`canopy-hook-gate`)

Registered against the `Bash` tool. Before any Bash command runs, the gate:

1. **Fast-paths** anything with no `git` word (allow immediately) and any command where `CANOPY_HOOKS_DISABLED=1`.
2. **Splits the command into top-level segments** (quote-, subshell-, and heredoc-aware) and tracks the **effective directory** across the chain — following `cd`, `git -C`, and absolute/relative paths. The evidence base: the agent's cwd never leaves the workspace parent; repo work happens via `cd <repo> && git …` chains, so the gate must judge each segment's *resolved* directory, not the shell's cwd.
3. **Only judges git *mutation* segments** — `commit`, `push`, `merge`, `rebase`, `reset`, `cherry-pick`, `add`, `rm`, `mv`, `am`, `revert`, and mutating `stash` sub-verbs. Reads (`git status`, `git log`, `stash list`) pass. `checkout` / `switch` are **deliberately not gated** — they are the recovery action for a wrong-branch state, so blocking them would trap the agent.

It denies a mutation in four cases, each returning exit code `2` with a reason fed back to the model:

| Code | When | The reason names the fix |
|---|---|---|
| `outside_repo` | the effective dir isn't inside any workspace repo (or slot worktree) | "re-run from inside the target repo … or use `canopy run`" |
| `trunk_branch_drift` | committing/pushing in trunk while it's on a feature branch that isn't the canonical feature | "run `canopy switch <feature>`" |
| `slot_branch_drift` | committing/pushing in a warm slot that's on the wrong branch for its occupant | "`git checkout <expected>` … or `canopy doctor`" |
| `push_unknown_branch` | pushing a src refspec that doesn't exist in this repo (with a hint if it exists in a sibling repo — "wrong repo?") | "check the branch for THIS repo with `canopy context`" |

**Fail-open contract:** any parse failure, unresolvable path (`$vars`, `~`, `cd -`), exotic flag (`--git-dir`), or internal error ⇒ **allow**. The gate blocks *only* when it is sure the mutation targets the wrong place. It has no side effects — it reads `slots.json` + `features.json` + live git.

When the agent sees a message starting with `canopy: blocked`, the correct response is to **read the reason and follow it** (usually `cd <repo> && …` or `canopy switch <feature>`) — never retry the same command or route around it with a different path.

### SessionStart brief (`canopy-hook-context`)

A compact block (~10 lines) injected into every new session's context, *before* the agent reads a single file. It shows:

- the workspace name and the **canonical feature**;
- **per-repo current branch + dirty/clean** (or "missing on disk");
- **warm slot occupancy** (`slot worktree-1 → <feature>`);
- any advisories (`⚠ …`);
- a standing instruction: *"Before any work: confirm the branch above matches this chat's ticket. If not, run `canopy switch <feature>` FIRST."*

The mismatch (this chat is about feature X, but trunk is on feature Y) must be visible before the first edit — that is what the brief buys.

## The daily loop (the 15 tools)

```
1. context()                 → orient: the workspace map (local, instant)
   context(remote=True)      → add the PR/CI overlay when the task needs it
2. start(<alias>) / join(<repo>)   → scope new work (lazy; join registers the repo)
3. ... edit source with Read/Edit/Bash as normal ...
4. commit(message=...)       → feature-scoped, one message across the repos
   push(set_upstream=True)   → first push; the no_upstream blocker tells you when
5. preflight                 → run pre-commit hooks / test gate before shipping
```

- **Orient with `context`.** It's your single read for feature ↔ repo ↔ branch ↔ path ↔ state, local and instant — use it freely. Add `remote=True` **only** when the task depends on remote state (addressing PR comments, checking CI, reviewing). Local code work does not need the overlay.
- **Scope work with `start` / `join`.** `start <alias>` begins new work lazily (no repos touched until you join). `join <repo>` creates the branch *and* registers the repo so the enforcement gate recognizes it — a raw `git checkout -b` does **not** register, and `context` will advise you to `join`.
- **Commit / push through canopy.** `commit` commits the feature across its repos with one message and returns the wrong-branch / hooks-failed cases classified. `push` pushes them; on the first push the `no_upstream` blocker carries the retry args with `set_upstream=True`.
- **Gate with `preflight`.** Runs the pre-commit hooks (honoring `[augments].preflight_cmd`) before you ship.
- **Recover with `doctor` / `drift`.** See below.

### Worktree vs trunk — intent decides whether you `switch`

Canopy's two-tier slot model ([concepts.md §4](concepts.md#4-the-slot-model)) draws a hard line: **trunk (canonical) is the only place to RUN full-stack code**; warm slots (`.canopy/worktrees/worktree-N/<repo>/`) are the **workbench** for PR-review changes.

- **To make review changes** on a feature (address PR comments, small edits): work **in its warm slot**. `context` gives you the path; the enforcement gate allows commits/pushes there. **Do not `switch`** — switching is for running.
- **To RUN a feature** full-stack (boot the app, integration test): `switch(<feature>)` promotes it into trunk, the only place with the full environment.
- If `context` shows a slot's deps as `installing` or `failed`, wait or run `worktree_bootstrap` before linting/testing there.

`switch` moves the previously-canonical feature into a warm slot by default (fast to switch back). `switch(release_current=True)` instead winds it down to **cold** (branch only, with a feature-tagged stash) — no warm worktree. When the warm-slot cap (`slots = N`, default 2) would be exceeded, `switch` auto-evicts the LRU warm feature or returns a `worktree_cap_reached` BlockerError with fix-actions (`--evict`, `--evict-to`, raise the cap). **`reclaim`** frees warm slots whose PRs have merged (clean ones only).

## Session start / returning to a feature

The agent orients with **`context`** — not with a resume tool. The rich resume brief (what changed since your last visit, intent hints, refreshed GH/Linear state) is now a **human/CLI tool: `canopy resume --json`**, on the management surface. It is **not** an MCP tool, so the agent does not call it.

At session start:

1. The SessionStart brief already told you the canonical feature and per-repo branches.
2. If the chat is about a feature that isn't canonical and you need to **run** it, `switch(<alias>)`. If you're only making review changes, work in its warm slot — often no `switch` is needed because the slot is already correct.
3. Call `context()` for the full map; add `remote=True` if you're about to touch PR comments or CI.

Do not invent or call removed MCP tools (`feature_resume`, `github_get_pr_comments`, `feature_state`, `triage`, …). Orient via `context` and the reads it carries.

## Reading errors

Canopy actions return structured `BlockerError` / `FailedError`:

```json
{
  "status": "blocked",
  "code": "drift_detected",
  "what": "branches don't match the feature lane",
  "expected": {"...": "..."},
  "actual":   {"...": "..."},
  "fix_actions": [
    {"action": "switch", "args": {"feature": "SIN-12-search"},
     "safe": true, "preview": "restore the feature's branches across repos"}
  ]
}
```

`fix_actions` is ordered most-recommended first. Each entry has `safe: true|false`:

- `safe: true` → call it directly to recover.
- `safe: false` → surface it to the human first (it might lose work or affect remote state).

When you see a `BlockerError`, read `fix_actions[0]` and decide whether to follow it. **Don't ignore it and retry the original call.**

### Recovery: when canopy itself looks broken

If a canopy call returns an *unexpected* error — a `KeyError` from a state read, "feature not found" for one you just created, a path that should exist but doesn't — call **`doctor`** first. It runs a 21-code integrity check across state-file drift and install-staleness (including slot-state checks: `slot_dir_orphan`, `slot_entry_orphan`, `slot_branch_mismatch`, `slot_detached_head`, …), returning each issue with `code`, `severity`, `expected`, `actual`, and an `auto_fixable` flag.

1. `doctor()` → read the issues. If `summary.errors == 0`, it's not a state problem; investigate the original error normally.
2. Errors present and mostly `auto_fixable: true` → `doctor(fix=True)`. Report `fixed` / `skipped` to the human.
3. `auto_fixable: false` (e.g. `features_unknown_repo`, `branches_missing`, `cli_stale`) → surface the `fix_action` text; the human needs to decide (delete the feature? restore the repo? reinstall the binary?).

The `version` tool reports `{cli_version, mcp_version, schema_version}` for the same handshake — useful when an agent suspects the CLI binary on PATH is older than the MCP it's talking to.

## External MCP servers

Canopy also acts as an MCP **client** — the management surface spawns external MCP servers (Linear, GitHub) on demand for its reads. Two transports:

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

First call opens the browser for OAuth; the token caches at `~/.canopy/mcp-tokens/linear.{client,tokens}.json` for subsequent silent calls. No API key required.

For GitHub specifically, canopy falls back to the `gh` CLI when no `github` MCP server is configured — same return shapes either way. If neither is available, `BlockerError(code='github_not_configured')` includes platform-aware install hints.

## Beyond Claude Code

The `using-canopy` skill and the enforcement hooks are Claude-Code conventions (`~/.claude/skills/`, `.claude/settings.json`). The **MCP server itself works with any MCP-aware client** (Cursor, Windsurf, custom integrations). For non-Claude clients, replicate the skill's guidance as a system prompt or rules file in your client's convention — but note the hook-based enforcement won't apply, so path discipline falls back to the agent following the skill.

## Troubleshooting

```bash
canopy setup-agent --check     # is the skill installed? MCP registered? hooks configured?
canopy hooks status            # are the per-repo drift post-checkout hooks installed?
canopy drift                   # what does canopy think vs reality?
```

- **MCP tools don't appear in the session** → restart the client; MCP servers load once per session.
- **The enforcement gate isn't firing** → confirm `setup-agent --hooks` ran (`--check` shows `hooks ✓ installed`), then restart Claude Code. To disable it for one command, set `CANOPY_HOOKS_DISABLED=1`.
- **`context(remote=True)` returns `github_not_configured`** → install + auth `gh` (`brew install gh && gh auth login`), or add a `github` MCP server entry to `.canopy/mcps.json`.
- **A Linear read opens a browser tab unexpectedly** → that's the OAuth flow; complete the auth, the token caches, subsequent calls are silent.
