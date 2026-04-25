# Canopy — Claude Code Context

## What This Project Is

Canopy is the **context contract** between an AI coding agent and a multi-repo workspace, plus a **drift-proof CLI** for the human. Every operation takes semantic context (`feature`, `repo`, alias) and resolves paths internally — the agent literally can't `cd` to the wrong directory because it never specifies a directory. Multi-repo drift is detected in real time via per-repo post-checkout hooks and surfaced as a structured `BlockerError`. PR review comments are temporally classified into `actionable_threads` vs `likely_resolved_threads`, so the agent's context budget goes to comprehension, not orchestration.

**`canopy switch` is the focus primitive (Wave 2.9 canonical-slot model).** Each feature lives in one of three states: **canonical** (checked out in main repo), **warm** (worktree at `.canopy/worktrees/<f>/<r>/`), **cold** (branch only). `switch(Y)` promotes Y to canonical; previously-canonical X either evacuates to warm (active rotation, default — instant to switch back) or goes cold with a feature-tagged stash (wind-down via `--release-current`). Cap (`max_worktrees`, default 2) protects against unbounded growth via LRU eviction or a `worktree_cap_reached` BlockerError. See [docs/concepts.md §4](docs/concepts.md#4-the-canonical-slot-model).

## Architecture

```
src/canopy/
├── cli/main.py              # argparse entry point, all commands (thin wrapper)
├── cli/render.py            # structured-error renderer
├── workspace/
│   ├── config.py            # canopy.toml parser
│   ├── discovery.py         # auto-detect repos + worktrees, generate toml
│   ├── context.py           # context detection (feature_dir, repo_worktree, repo, workspace_root)
│   └── workspace.py         # Workspace class, RepoState dataclass
├── git/
│   ├── repo.py              # ALL git subprocess calls go here
│   ├── multi.py             # cross-repo operations
│   ├── hooks.py             # install/uninstall post-checkout hook + heads.json reader
│   └── templates/post-checkout.py   # hook script (Python, fcntl-locked, never blocks git)
├── features/coordinator.py   # FeatureLane, FeatureCoordinator (+ branches map for per-repo branches)
├── actions/                 # WAVE 2+: action layer — completion-driven recipes
│   ├── errors.py            # ActionError / BlockerError / FailedError / FixAction
│   ├── aliases.py           # universal alias resolver + repos_for_feature helper
│   ├── active_feature.py    # .canopy/state/active_feature.json reader/writer + last_touched LRU
│   ├── drift.py             # detect_drift + assert_aligned (cached path)
│   ├── evacuate.py          # WAVE 2.9: per-repo evacuate primitive (stash → wt-add → pop)
│   ├── feature_state.py     # 8-state machine, dashboard backend (live git, worktree-aware)
│   ├── preflight_state.py   # records preflight result for state machine
│   ├── reads.py             # 4 alias-aware read primitives
│   ├── realign.py           # internal helper used by switch (deprecated from CLI/MCP in Wave 2.9)
│   ├── review_filter.py     # temporal classifier
│   ├── stash.py             # feature-tagged stash save/list/pop
│   ├── switch.py            # WAVE 2.9: canonical-slot focus primitive
│   ├── switch_preflight.py  # WAVE 2.9: predictable-failure detection for switch
│   └── triage.py            # cross-repo PR enumeration + priority tiers (canonical-slot enriched)
├── agent/
│   └── runner.py            # canopy_run — directory-safe shell exec
├── agent_setup/             # ships using-canopy skill + setup_agent installer
│   ├── __init__.py          # install_skill / install_mcp / check_status
│   └── skill.md             # canonical skill content
├── integrations/
│   ├── linear.py            # Linear issue fetching (via mcp/client.py)
│   ├── github.py            # GitHub PR + comments (MCP or gh CLI fallback)
│   └── precommit.py         # detect + run pre-commit hooks
└── mcp/
    ├── server.py            # MCP server — 41 tools, stdio transport
    └── client.py            # MCP client — stdio + HTTP+OAuth transports
```

## Key conventions

- **`git/repo.py` is the only module that calls `subprocess.run(["git", ...])`.** Everything else routes through it. Keeps the git layer testable and replaceable.
- **`mcp/server.py` and `cli/main.py` are thin wrappers.** Business logic lives in `actions/`, `features/coordinator.py`, `git/multi.py`, `workspace/`.
- **All CLI commands support `--json`.** This is the contract between CLI, MCP, and any GUI. Same JSON shape across surfaces.
- **Actions return structured errors.** `BlockerError(code, what, expected, actual, fix_actions, details)`. CLI renders via `cli/render.py`; MCP returns `to_dict()`. Same shape, two consumers.
- **Universal aliases** — every read tool accepts feature name, Linear ID, `<repo>#<n>`, PR URL, or `<repo>:<branch>`. Resolved by `actions/aliases.py:resolve_feature` (with single-repo + per-repo-branch fallbacks).
- **Per-repo branches map** — `FeatureLane.branches: dict[repo, branch]` overrides "branch == feature name" for legacy mismatched-naming features. Use `lane.branch_for(repo)` or `repos_for_feature(workspace, feature)` everywhere — never recompute as `[r for r in feature.repos]` with feature name as branch (regresses Gap 2).
- **Feature lanes use real Git branches and worktrees.** No virtual branches.
- **Feature metadata lives in `.canopy/features.json`.** Worktrees in `.canopy/worktrees/<feature>/<repo>/` (only when created with `--worktree`).
- **State files** at `.canopy/state/heads.json` (post-checkout hook output), `.canopy/state/preflight.json` (preflight tracker), and `.canopy/state/active_feature.json` (current canonical + per-repo paths + `last_touched` LRU map for switch eviction). OAuth tokens at `~/.canopy/mcp-tokens/`.
- **MCP client supports two transports.** Stdio (existing) for npm/python servers. HTTP+OAuth (new) for hosted servers like Linear's `mcp.linear.app`. Tokens cache per server.
- **GitHub fallback to gh CLI.** When no `github` MCP server is configured, `integrations/github.py` falls back to `gh api` / `gh pr` for the same return shapes. If neither is available, raises `BlockerError(code='github_not_configured')` with platform-aware install hints.
- **Single source of truth for state.** `feature_state` uses live git (not heads.json) so it's correct even when the hook hasn't fired. `drift` uses heads.json for the fast cached path.
- **Feature-aware stash tagging** — `stash save --feature` writes `[canopy <feature> @ <ts>] <message>`. Parser tolerates git's `On <branch>: ` auto-prefix.

## Build & Test

```bash
pip install -e ".[dev]"
pytest tests/ -v          # 401 tests, ~60s
```

## Test Fixtures

Tests use real temporary Git repos created in `tests/conftest.py`:
- `workspace_dir` — bare workspace with `api/` and `ui/` repos on main
- `workspace_with_feature` — workspace with `auth-flow` branches + commits in both repos
- `canopy_toml` — workspace with a canopy.toml already written

For integration testing against real services, see `~/projects/canopy-test/` (memory: project_test_workspace).

## Important Implementation Details

- **Python 3.10+ compat:** `tomli` on 3.10, `tomllib` on 3.11+. See `config.py`.
- **Drift detection:** post-checkout hook installed by `canopy init` (or `canopy hooks install`). Hook is Python; uses `fcntl.flock` + atomic rename so concurrent fires across repos don't race. Respects `core.hooksPath` (Husky-friendly). Chains pre-existing user hooks. Worktrees inherit hooks via `commondir` resolution.
- **`--no-track` on branch creation:** `git/repo.py:create_branch` and `worktree_add` always pass `--no-track` so a `branch.autoSetupMerge=inherit` gitconfig doesn't accidentally set the new branch's upstream to `dev`.
- **Worktree limits:** `max_worktrees` in canopy.toml caps explicit `worktree_create` calls (`WorktreeLimitError` includes stale candidates). For `switch`'s canonical-slot logic, the same field is interpreted as the warm-slot cap; if unset (0), the new default is **2** (1 canonical + 2 warm = 3 live trees max). See `actions/switch_preflight.py:warm_slot_cap`.
- **Action contract:** `actions/protocol.py` (planned) will formalize the per-repo `{status, before, after, reason?}` shape. For now, each action returns it ad-hoc.
- **Skill bundling:** `src/canopy/agent_setup/skill.md` ships in the wheel; `canopy setup-agent` (or `canopy init`) copies it to `~/.claude/skills/using-canopy/SKILL.md`. Foreign skills with the same path are not overwritten without `--reinstall`.

## MCP Server (41 tools)

Grouped by topic. Run with `canopy-mcp` (entry point) or `python -m canopy.mcp.server`.

```
Workspace:    workspace_status, workspace_context, workspace_config, workspace_reinit
Feature:      feature_create, feature_list, feature_status, feature_diff,
              feature_changes, feature_merge_readiness, feature_paths, feature_done,
              feature_link_linear, feature_state
Actions:      switch, triage, drift          # realign deprecated from MCP; internal helper
Reads:        linear_get_issue, github_get_pr, github_get_branch, github_get_pr_comments,
              linear_my_issues
Run/Pre:      run, preflight, review_status, review_comments, review_prep
Stash:        stash_save_feature, stash_list_grouped, stash_pop_feature,
              stash_save, stash_pop, stash_list, stash_drop
Worktree:     worktree_create, worktree_info
Branch:       branch_list, branch_delete, branch_rename
Misc:         log, checkout, sync
```

## MCP Client

Two transports.

**stdio** for npm/python servers:
```json
{ "github": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
              "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_..."} } }
```

**HTTP + OAuth** for hosted servers like Linear:
```json
{ "linear": { "type": "http", "url": "https://mcp.linear.app/mcp", "oauth": true } }
```

Token cache at `~/.canopy/mcp-tokens/<server>.{client,tokens}.json`. First call opens browser; subsequent calls silent.

## When working in this repo

- Read `docs/concepts.md` if you need the action framework / state machine vocabulary.
- Read `docs/agents.md` if you're implementing or using the agent integration.
- New actions: stub in `src/canopy/actions/`, raise `BlockerError` for preconditions, expose via CLI in `cli/main.py` + MCP in `mcp/server.py`. Add tests in `tests/test_<action>.py` using the existing `workspace_with_feature` fixture.
- New MCP tools: register an existing `actions/*.py` function under `@mcp.tool()` in `mcp/server.py`. Update `docs/mcp.md` and `docs/agents.md`.
- New CLI commands: define a handler `cmd_<name>(args)`, add a subparser in `main()`, dispatch in the `commands` dict. Update `docs/commands.md`.
- Adding a new ⨯ tool to canopy → also update `~/.claude/skills/using-canopy/SKILL.md` and `src/canopy/agent_setup/skill.md` so the agent learns when to prefer it.
