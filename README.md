<p align="center">
  <img src="docs/canopy-banner.svg" alt="canopy — multi-repo work, one focused command" width="600">
</p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white">
  <img alt="Tests" src="https://img.shields.io/badge/tests-436%20passing-brightgreen?style=flat-square">
  <img alt="MCP Tools" src="https://img.shields.io/badge/MCP%20tools-43-purple?style=flat-square">
  <a href="https://marketplace.visualstudio.com/items?itemName=SingularityInc.canopy"><img alt="VSCode Extension" src="https://img.shields.io/badge/VSCode-extension-blue?style=flat-square&logo=visualstudiocode"></a>
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-gray?style=flat-square">
</p>

---

## What it solves

If you work across multiple repos, you've felt this:

- You switch one repo's branch, forget the other; the next push goes to the wrong place.
- You're juggling 2–3 features at once; switching loses your in-progress work — or buries it in a stash you'll forget.
- Your AI agent shells `cd /wrong/repo && command` because shell state doesn't persist between its tool calls.
- PR review comments pile up across repos and the agent burns context re-deriving "is this still actionable?"

Canopy gives your AI agent the same typed multi-repo surface you have at the CLI — switch, commit, push, triage, review, all of it. Same JSON, same primitives, same drift safety. The detail table is below — first, the verb that does the lifting.

<p align="center">
  <img src="docs/cli-switch.svg" alt="canopy switch sin-7-empty-state" width="720">
</p>

**`canopy switch <feature>`** promotes a feature into the canonical slot — checks it out in your main directory across every repo it touches, parks the previously-focused feature to a warm worktree, preserves dirty work via stash. Multi-repo focus, one verb, no `cd`.

Everything else canopy does is in service of that command: pre-flight checks before commit, status across repos, PR triage, agent integration. **One command at the center; the rest are accessories.**

## Why it's load-bearing

Multi-repo work breaks in specific, predictable ways. `canopy switch` and its accessories close each:

| Failure mode | Canopy's fix |
|---|---|
| You switch one repo's branch, forget the other; next push goes to the wrong place. | `canopy switch <feature>` is atomic across every participating repo. Drift in the meantime is detected in real time by a post-checkout hook and surfaced via `canopy drift` / `canopy state`. |
| You're juggling 2–3 features at once; switching loses your in-progress work or buries it in a stash you forget. | `canopy switch` runs in **active rotation** by default — the previously-focused feature evacuates to a warm worktree (dirty work follows via stash → pop). Switching back is instant. |
| You start using `git worktree add` to keep features parallel. By feature 4 you have a scatter of `~/work/auth-feature-api/` / `~/scratch/api-newauth/` dirs with no naming convention. Cleanup means remembering paths to `git worktree remove`, then `git branch -D` per repo. | Canopy enforces `.canopy/worktrees/<feature>/<repo>/` — predictable layout, one place to look. `canopy list` shows every feature with its worktree paths. `canopy done <feature>` removes every worktree and deletes every branch across all repos in one verb. |
| You're on `dev` in main with two warm feature worktrees parked alongside. You want to commit, run preflight, or push on a feature without `cd`-ing into its worktree directory. Raw git makes you switch your shell's `cwd` first. | `canopy commit --feature <X>` / `canopy preflight --feature <X>` / `canopy push --feature <X>` operate against the warm worktree directly — your `cwd` doesn't move. Or `canopy switch <X>` to promote the warm feature into the canonical slot first (dev evacuates to its own worktree, dirty work follows via stash → pop). |
| Your AI agent shells `cd /wrong/repo && command` because shell state doesn't persist between tool calls. | Every canopy tool takes `feature` / `repo` as parameters; path resolution lives inside canopy. The agent has no surface area for the mistake. |
| Your agent re-derives PR state on every run because nothing it learned in the previous turn persists. It re-parses `gh pr list`, re-walks `git status` per repo, re-classifies threads — burning context on bookkeeping. | `mcp__canopy__triage` and `mcp__canopy__feature_state` return cached structured data: PR numbers, review state, dirty counts, per-repo paths. Agent reads, doesn't re-derive. Same JSON across runs. |
| Drift happens silently *between* the agent's tool calls — it ran `git checkout X` in one repo, the next call assumes alignment, things go sideways. | Per-repo post-checkout hooks write `.canopy/state/heads.json` atomically (fcntl-locked). `mcp__canopy__drift` reads cached state in <50ms. The agent sees the misalignment that happened between calls — even when it didn't cause it. |
| You and your agent see different views of workspace state. You're looking at `canopy status`; the agent's reading some other JSON it cached three turns ago. Decisions diverge. | The CLI and MCP server are thin wrappers over the same actions. `canopy state X` and `mcp__canopy__feature_state(feature='X')` return identical bytes. Single source of truth, two surfaces. |
| PR review comments pile up across repos; the agent burns context re-deriving "is this still actionable?". | `canopy review <feature>` returns threads pre-classified as `actionable` vs `likely_resolved`. The temporal classifier filters out comments addressed in subsequent commits. |

<p align="center">
  <img src="docs/cli-drift.svg" alt="canopy drift" width="720">
</p>

## The agent contract

Other multi-repo helpers — raw `git worktree add`, monorepo-specific bash wrappers, per-team scripts that wrap them — are built for humans at a terminal. Agents can't use them safely: shell state evaporates between tool calls, paths get constructed wrong, errors come back as stderr text the agent has to interpret.

Canopy exposes **43 typed MCP tools**. Each takes `feature` / `repo` as parameters, returns JSON, fails with a structured `BlockerError(code, what, expected, actual, fix_actions)`. The agent never specifies a path, never parses stderr, never re-derives state.

```python
# Brittle — agent constructs the path, parses stderr, hopes for the best:
bash("cd /Users/me/projects/canopy-test/.canopy/worktrees/sin-7/test-api && git status")

# Path-safe — canopy owns resolution and returns structured data:
mcp__canopy__feature_status(feature="sin-7-empty-state")
# → {repos: {test-api: {abs_path: "...", current_branch: "...", changed_file_count: 1, ahead: 1, ...}}}
```

This is the headline difference between canopy and the alternatives. Other tools manage worktrees; canopy gives an agent a *contract* — typed inputs, structured outputs, recoverable errors — that makes multi-repo work safe to delegate.

## Install

Requires Python 3.10+.

```bash
pipx install git+https://github.com/ashmitb95/canopy.git
cd ~/your-multi-repo-workspace
canopy init
```

If you don't have pipx: `brew install pipx && pipx ensurepath`.

`canopy init` discovers your git repos, writes `canopy.toml`, installs drift-detection git hooks, and registers itself with Claude Code (skill + MCP). Skip the agent bits with `--no-agent`.

<p align="center">
  <img src="docs/cli-init.svg" alt="canopy init" width="720">
</p>

## What you do every day

```bash
canopy switch <feature>     # focus — promote to the canonical slot
canopy status               # where am I across repos?
canopy preflight            # run per-repo hooks before committing
canopy commit -m "..."      # commit across repos at once
canopy push                 # push across repos at once
canopy review <feature>     # actionable PR threads only
canopy triage               # what should I work on next?
```

Every CLI command has an `mcp__canopy__*` equivalent for the agent side, returning the same JSON.

<p align="center">
  <img src="docs/cli-status.svg" alt="canopy status" width="720">
</p>

## Switch in detail

`canopy switch` operates in two modes:

- **Active rotation (default).** The previously-focused feature evacuates to a warm worktree at `.canopy/worktrees/<feature>/<repo>/`, with stash → checkout → pop. Switching back is one command and instant.
- **Wind-down (`--release-current`).** The previously-focused feature goes cold (just the branch + a feature-tagged stash for any dirty work). Use when you're parking it or done with it.

```bash
canopy switch sin-7-empty-state                       # active rotation
canopy switch sin-7-empty-state --release-current     # wind-down
```

`max_worktrees` (default 2) caps how many warm worktrees co-exist alongside the canonical slot. When the cap fires, `switch` returns a structured `BlockerError` with explicit fix actions — evict LRU to cold, switch in wind-down mode, finish a feature, or raise the cap. No silent eviction.

## Triage and review

After you switch, canopy tells you what's worth your attention:

<p align="center">
  <img src="docs/cli-triage.svg" alt="canopy triage" width="720">
</p>

`canopy triage` enumerates active features by review-state priority. `canopy review <feature>` shows actionable PR threads only.

`canopy state <feature>` returns one of 8 states (`drifted`, `needs_work`, `in_progress`, `ready_to_commit`, `ready_to_push`, `awaiting_review`, `approved`, `no_prs`) plus a `next_actions` array. The agent reads the array; you read the colored output. Same JSON.

<p align="center">
  <img src="docs/cli-state.svg" alt="canopy state" width="720">
</p>

## Commit and push without thinking about repos

`canopy commit -m "msg"` and `canopy push` operate against the canonical feature by default — no `--feature` argument, no `cd`. They fan out across every repo in the feature's lane and return a per-repo summary. If hooks fail in one repo, the others still commit; you re-run after fixing.

<p align="center">
  <img src="docs/cli-commit.svg" alt="canopy commit" width="720">
</p>

## For your AI agent

Canopy ships with a [`using-canopy`](src/canopy/agent_setup/skill.md) skill (installed by `canopy init`) and an MCP server with 43 tools. The skill teaches the agent: *use canopy MCP for path-safe multi-repo ops*. After install, an agent will:

- Call `mcp__canopy__triage` instead of parsing `gh pr list` output across repos. Each result carries `is_canonical` + `physical_state` + per-repo `path` so the agent knows whether to switch first or just operate.
- Call `mcp__canopy__switch(feature='SIN-42')` instead of `cd repo && git checkout` per repo. The previously-focused feature evacuates to a warm worktree, preserving work-in-progress.
- Call `mcp__canopy__run(repo='backend', command='pytest tests/')` instead of `cd /path && pytest`.
- Read `mcp__canopy__feature_state(feature).next_actions` to know what to do next.

Linear MCP works via OAuth (browser flow once, no API key). GitHub works via `gh` CLI fallback when MCP isn't configured. See [docs/agents.md](docs/agents.md) for the full integration story.

## For humans

Same operations are also available via a [VSCode extension](https://marketplace.visualstudio.com/items?itemName=SingularityInc.canopy) — features, drift, PR triage, review readiness in one native panel, with the same state machine the agent sees.

## Docs

- [Concepts](docs/concepts.md) — the action framework, agent context contract, 8-state machine
- [Agents](docs/agents.md) — skill, `setup-agent`, integration recipes
- [Commands](docs/commands.md) — full CLI reference, organized by workflow stage
- [MCP](docs/mcp.md) — server tool list, client transports (stdio + HTTP/OAuth), gh fallback
- [Workspace](docs/workspace.md) — `canopy.toml`, `features.json`, state files, mcp.json
- [Architecture](docs/architecture.md) — module boundaries and design rules

## Develop

```bash
git clone https://github.com/ashmitb95/canopy.git ~/projects/canopy
cd ~/projects/canopy
pip install -e ".[dev]"
pytest tests/ -v             # 436 tests, ~80s, all use real temporary Git repos
```

## License

MIT
