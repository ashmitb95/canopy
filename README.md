<p align="center">
  <img src="docs/canopy-banner.svg" alt="canopy — typed multi-repo work for AI coding agents" width="600">
</p>

<p align="center">
  <em>The context contract between an AI coding agent and a multi-repo workspace.</em>
</p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white">
  <img alt="Tests" src="https://img.shields.io/badge/tests-987%20passing-brightgreen?style=flat-square">
  <img alt="MCP Tools" src="https://img.shields.io/badge/MCP%20tools-15-purple?style=flat-square">
  <a href="https://marketplace.visualstudio.com/items?itemName=SingularityInc.canopy"><img alt="VSCode Extension" src="https://img.shields.io/badge/VSCode-extension-blue?style=flat-square&logo=visualstudiocode"></a>
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-gray?style=flat-square">
</p>

---

Canopy is built for workspaces with **multiple repos that share a feature lifecycle** — backend + frontend, api + mobile, a monolith plus its services. That setting breaks coding agents in specific, fixable ways: shell state doesn't survive between tool calls, paths get constructed wrong, drift accumulates silently between repos, and PR-review orchestration pulls the agent across repo boundaries faster than its context can keep up.

## Two surfaces

Canopy 4.0 — *the great distillation* — splits into **two surfaces**, and that split is the whole point.

**1. The agent contract — 15 MCP tools.** The agent sees only what it needs to work safely and stay oriented: **path-safety + registry + focus + safe-git-ops + recovery.** It never names a directory — it names semantic context (`feature`, `repo`, alias) and canopy resolves paths internally, so the agent literally cannot `cd` to the wrong repo or commit from the parent dir. Claude Code enforcement hooks keep git honest at the wire. The agent's context budget goes to **comprehension, not orchestration.**

**2. The human / dashboard management surface — CLI `--json`.** PR triage, review-comment classification, bot rollups, ship, historian, resume briefs, conflict detection, Linear/GitHub reads — the management work — is *not* on the agent surface. It lives in `canopy/management/` and is reached by the human (or the dashboard/GUI) via `canopy <cmd> --json`. Same JSON shape across CLI, MCP, and any GUI.

> Pre-4.0 canopy exposed 67+ MCP tools to the agent, and the agent spent context orchestrating PR management instead of understanding code. 4.0 distills the agent surface to the 15 tools of the core loop and moves management to where a human or dashboard consumes it. **Nothing was deleted** — management moved off the agent surface. Every `canopy triage / review / ship / resume / conflicts / bot-status / historian` command still works as a CLI command with `--json`. The agent sees less so it can understand more.

## Quickstart

Requires Python 3.10+.

```bash
pip install canopy-cli
cd ~/your-multi-repo-workspace
canopy init          # discover repos → write canopy.toml → install drift hooks
canopy setup-agent   # wire the MCP server + install the `using-canopy` skill
```

`canopy setup-agent` writes the canopy MCP server into Claude Code and installs the `using-canopy` skill at `~/.claude/skills/using-canopy/SKILL.md` so the agent knows when to reach for canopy. Add `--hooks` to install the Claude Code enforcement hooks (the git gate + session brief) into `<workspace>/.claude/settings.json`, and `--skill augment-canopy` for the opt-in `canopy.toml [augments]` tuning skill.

<p align="center">
  <img src="docs/cli-init.svg" alt="canopy init" width="720">
</p>

## The agent's daily loop

The 15 tools cover the whole loop — orient, work, recover — without the agent ever typing a path:

```
context()                       # the single-read workspace map: orient
start("auth-flow")              # lazily begin a feature; join("ui") to register a repo
switch("auth-flow")             # promote it into trunk — the only place code runs
run("api", "pytest -q")         # path-safe shell exec; canopy resolves the cwd
commit(message="…")             # feature-scoped, multi-repo commit
push()                          # push across every repo in the feature's lane
doctor()                        # 21-code integrity check + repair when something feels off
```

Everything the agent names is semantic (`feature`, `repo`, alias); canopy owns the paths. When a precondition fails, the tool returns a structured `BlockerError(code, what, expected, actual, fix_actions)` — each fix carrying `safe: bool` — so the agent recovers from a typed payload instead of parsing stderr.

## The 15 agent tools

| Group | Tools | Purpose |
|---|---|---|
| **Meta** | `version` | Version handshake for `doctor` staleness checks. |
| **Registry** | `context`, `start`, `join` | The single-read workspace map (feature ↔ repo ↔ branch ↔ path ↔ state, local + remote PR/CI tier); lazy feature start; register a repo into the active feature. |
| **Focus / slots** | `switch`, `reclaim` | Promote a feature into trunk (the run target); free a warm slot whose PR merged. |
| **Safe git ops** | `run`, `commit`, `push`, `preflight` | Path-safe shell exec; feature-scoped multi-repo commit; push across the lane; pre-commit gate. |
| **Recovery** | `doctor`, `drift` | 21-code integrity check + repair; branch-drift detection across repos. |
| **WIP + workable slots** | `stash_save_feature`, `stash_pop_feature`, `worktree_bootstrap` | Feature-tagged stash save/pop; bootstrap a warm slot (env / deps / hooks / IDE). |

`context` is *the* registry read — it supersedes the old `workspace_status` / `workspace_context` / `feature_list` / `feature_status` / `slots` tools with a local (instant) tier and a remote (PR/CI overlay) tier. Full reference: [docs/mcp.md](docs/mcp.md).

## Enforcement hooks

Path-safety isn't only a convention — it's enforced. Canopy ships Claude Code hooks (installed via `canopy setup-agent --hooks`):

- **PreToolUse git gate** — resolves the *effective* directory of any git command (through `cd`-chains, `git -C`, heredocs) and blocks mutations from the wrong path or wrong branch. This is the enforcement half of "the agent can't `cd` wrong."
- **SessionStart brief** — orients the agent at the start of a session so it doesn't re-derive the workspace from scratch.

## The slot model

Trunk (canonical) is the **only** place to run full-stack code. Warm slots at `.canopy/worktrees/worktree-N/<repo>/` are the workbench for PR-review changes. **Intent decides whether you switch:** review changes happen *in* the worktree with no switch; `switch X` moves X into trunk only when you need to *run* it. `reclaim` frees a warm slot when its PR merges. The cap is `[workspace] slots = N` in canopy.toml (default 2); hitting it returns a `worktree_cap_reached` BlockerError with explicit fixes — no silent eviction. Full design: [docs/concepts.md §4](docs/concepts.md#4-the-slot-model).

## For humans — the management surface

The CLI kept **every** command, and each supports `--json` (the dashboard contract). The management work the agent no longer sees is here:

```bash
canopy triage               # cross-feature PR priority view
canopy review <feature>     # review-comment status / classification
canopy ship <feature>       # open/update PRs with cross-repo body links
canopy resume <feature>     # session-start brief — what changed since last visit
canopy conflicts            # cross-feature file/line overlap
canopy bot-status <feature> # per-PR bot-comment rollup
canopy doctor               # diagnose drift / staleness
```

<p align="center">
  <img src="docs/cli-state.svg" alt="canopy state" width="720">
</p>

The CLI and the MCP server are thin wrappers over the same actions, so `canopy <cmd> --json` and the corresponding MCP tool return identical bytes. There's also a [VSCode extension](https://marketplace.visualstudio.com/items?itemName=SingularityInc.canopy) (source at [`ashmitb95/canopy-dashboard`](https://github.com/ashmitb95/canopy-dashboard)) reading the same state. Full CLI reference: [docs/commands.md](docs/commands.md).

## Docs

- [Concepts](docs/concepts.md) — the two surfaces, action framework, agent context contract, universal aliases, the slot model, the resume brief
- [Agents](docs/agents.md) — setup-agent, enforcement hooks, the daily loop over the 15 tools, reading BlockerErrors, recovery
- [MCP](docs/mcp.md) — the 15 agent tools, client transports (stdio + HTTP/OAuth), gh CLI fallback
- [Commands](docs/commands.md) — full CLI reference (core + management), each with `--json`
- [Workspace](docs/workspace.md) — `canopy.toml`, `features.json`, state files
- [Architecture](docs/architecture.md) — module boundaries, the agent-core ↔ management import boundary, state files
- [Providers](docs/architecture/providers.md) — issue-provider abstraction (Linear, GitHub Issues)

## Develop

```bash
git clone https://github.com/ashmitb95/canopy.git ~/projects/canopy
cd ~/projects/canopy
pip install -e ".[dev]"
pytest tests/ -v             # 987 tests, all use real temporary Git repos
```

## License

MIT
