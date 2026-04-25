<p align="center">
  <img src="docs/canopy-banner.svg" alt="Canopy" width="600">
</p>

<p align="center">
  <strong>Context contract for AI agents · drift-proof CLI enabler for you</strong>
</p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white">
  <img alt="Tests" src="https://img.shields.io/badge/tests-401%20passing-brightgreen?style=flat-square">
  <img alt="MCP Tools" src="https://img.shields.io/badge/MCP%20tools-41-purple?style=flat-square">
  <a href="https://marketplace.visualstudio.com/items?itemName=SingularityInc.canopy"><img alt="VSCode Extension" src="https://img.shields.io/badge/VSCode-extension-blue?style=flat-square&logo=visualstudiocode"></a>
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-gray?style=flat-square">
</p>

---

Canopy gives you and your AI agent a **mistake-proof grip on multi-repo workflows**. Every operation takes semantic context (a feature name, a repo name) and resolves paths internally — the agent literally can't run a command in the wrong directory because it never specifies a directory. Drift across repos is detected in real time. PR review comments get temporally classified (actionable vs likely-resolved) so context budget goes to comprehension, not orchestration. **`canopy switch`** promotes the feature you're focused on into the canonical slot (the main repo checkout), parking previous focus to a warm worktree — instant rotation across 2-3 features without losing context.

Same operations, two surfaces:
- **CLI** — `canopy triage`, `canopy state`, `canopy switch` — for you at a terminal.
- **MCP server + skill** — `mcp__canopy__*` — for any AI agent. Ships with a [`using-canopy`](src/canopy/agent_setup/skill.md) skill that teaches Claude Code (and others) when to prefer canopy over raw bash.

## Why

Multi-repo work breaks in four specific ways. Canopy fixes each:

| Failure mode | Canopy's fix |
|---|---|
| You switch one repo's branch, forget the other; next push goes to the wrong place | `canopy switch <feature>` promotes that feature to the main checkout in every participating repo, atomically. Drift in the meantime is detected by a post-checkout hook + surfaced via `canopy drift` / `canopy state`. |
| You're juggling 2-3 features at once; switching loses your in-progress work or buries it in a stash you'll forget | `canopy switch` runs in **active rotation** mode by default — the previously-focused feature evacuates to a warm worktree (its dirty work follows via stash → pop). Switching back is instant. Use `--release-current` for wind-down (cold storage with a feature-tagged stash). |
| Your agent shells `cd /wrong/repo && command` because shell state doesn't persist between tool calls | Every canopy tool takes `feature` / `repo` as parameters. Path resolution lives in canopy. The agent has no surface area for the mistake. |
| PR review comments pile up across repos with no unified view; agent burns context re-deriving "is this still actionable" | `canopy triage` enumerates open PRs, groups by feature, prioritizes by review state. `canopy comments <feature>` returns threads pre-classified as `actionable_threads` vs `likely_resolved_threads`. |
| Pre-commit checks differ per repo; the agent doesn't know which to run | `canopy preflight <feature>` runs the right checks per repo. Result is recorded so `canopy state` knows whether you're `in_progress` or `ready_to_commit`. |

## How It Looks

<p align="center">
  <img src="docs/cli-state.svg" alt="canopy state" width="600">
</p>

<details>
<summary>More CLI screenshots</summary>
<br>
<p align="center">
  <img src="docs/cli-triage.svg" alt="canopy triage" width="600"><br>
  <img src="docs/cli-drift.svg" alt="canopy drift" width="600"><br>
  <img src="docs/cli-status.svg" alt="canopy status" width="600">
</p>

<sub>(`cli-switch.svg` and refreshed CLI captures pending — see [issue #4](https://github.com/ashmitb95/canopy/issues/4) for the visual refresh against the canonical-slot model.)</sub>
</details>

## Install

Requires Python 3.10+.

```bash
pipx install git+https://github.com/ashmitb95/canopy.git
```

If you don't have pipx: `brew install pipx && pipx ensurepath`.

## First-run

```bash
cd ~/your-multi-repo-workspace
canopy init
```

`canopy init` does five things in one shot:

1. Discovers Git repos and writes `canopy.toml`
2. Installs `post-checkout` hooks per repo (drift detection)
3. Installs the [`using-canopy`](src/canopy/agent_setup/skill.md) skill at `~/.claude/skills/using-canopy/SKILL.md`
4. Registers `canopy-mcp` in the workspace's `.mcp.json`
5. Reports what changed

Restart Claude Code (or your MCP client) and you're ready. Skip the agent bits with `--no-agent`.

## The daily loop

```bash
canopy triage                  # what should I work on first?
canopy switch <feature>        # promote it to the canonical slot (main checkout)
canopy state <feature>         # where am I, what's next?
canopy comments <feature>      # actionable review threads only — not likely-resolved noise
canopy preflight <feature>     # run the per-repo checks
```

`canopy switch` is the focus primitive — it moves the named feature into the canonical slot in every repo, and decides where the previously-focused feature goes:
- **Default (active rotation):** previous focus evacuates to a warm worktree at `.canopy/worktrees/<feature>/<repo>/` (with stash → checkout → pop). Switching back is instant.
- **`--release-current` (wind-down):** previous focus goes cold (just the branch + a feature-tagged stash for any dirty work). Use when you're parking it / done with it.

`canopy state` returns one of 8 states (`drifted`, `needs_work`, `in_progress`, `ready_to_commit`, `ready_to_push`, `awaiting_review`, `approved`, `no_prs`) plus a `next_actions` array. The agent reads the array; you read the colored output. Same JSON.

## For AI agents

Canopy ships with a [`using-canopy`](src/canopy/agent_setup/skill.md) skill (installed by `canopy init`) and an MCP server with 41 tools. The skill teaches the agent: *use canopy MCP for path-safe multi-repo ops*. After install, an agent in a workspace where canopy is configured will:

- Call `mcp__canopy__triage` instead of parsing `gh pr list` output across repos. Each result carries `is_canonical` + `physical_state` + per-repo `path` so the agent knows whether to switch first or just operate.
- Call `mcp__canopy__switch(feature='SIN-42')` instead of `cd repo && git checkout` per repo (and the previously-focused feature evacuates to a warm worktree, preserving its work-in-progress).
- Call `mcp__canopy__run(repo='backend', command='pytest tests/')` instead of `cd /path && pytest`.
- Read `mcp__canopy__feature_state(feature).next_actions` to know what to do next.

Linear MCP works via OAuth (browser flow once, no API key). GitHub works via `gh` CLI fallback when MCP isn't configured. See [docs/agents.md](docs/agents.md) for the full integration story.

## For humans

Same operations as a CLI (full reference in [docs/commands.md](docs/commands.md)). Plus a [VSCode extension](https://marketplace.visualstudio.com/items?itemName=SingularityInc.canopy) with the same state-machine view as the agent — features, drift, PR triage, review readiness in one native panel.

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
pytest tests/ -v             # 401 tests, ~60s, all use real temporary Git repos
```

## License

MIT
