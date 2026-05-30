# Canopy — Claude Code Context

## What This Project Is

Canopy is the **context contract** between an AI coding agent and a multi-repo workspace, plus a **drift-proof CLI** for the human. Every operation takes semantic context (`feature`, `repo`, alias) and resolves paths internally — the agent literally can't `cd` to the wrong directory because it never specifies a directory. Multi-repo drift is detected in real time via per-repo post-checkout hooks and surfaced as a structured `BlockerError`. PR review comments are temporally classified into `actionable_threads` vs `likely_resolved_threads`, so the agent's context budget goes to comprehension, not orchestration.

**`canopy switch` is the focus primitive (Wave 3.0 slot model).** Each feature lives in one of three states: **canonical** (checked out in main repo — the only place code is meant to run), **warm** (occupies a numbered slot at `.canopy/worktrees/worktree-N/<repo>/`), **cold** (branch only). Slots are stable disk resources; features are transient tenants — a slot keeps its id (`worktree-1`, `worktree-2`, ...) across feature swaps. `switch(Y)` promotes Y to canonical; previously-canonical X either evacuates into a warm slot (active rotation, default — instant to switch back) or goes cold with a feature-tagged stash (wind-down via `--release-current`). Cap (`slots`, default 2) protects against unbounded growth via LRU eviction or a `worktree_cap_reached` BlockerError. See [docs/concepts.md §4](docs/concepts.md#4-the-slot-model).

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
│   ├── aliases.py           # universal alias resolver (incl. worktree-N → slot occupant)
│   ├── slots.py             # WAVE 3.0: slots.json reader/writer + path resolution + LRU
│   ├── slot_load.py         # WAVE 3.0: slot_load / slot_clear / slot_swap primitives
│   ├── slot_details.py      # WAVE 3.0: rich slots shape (PR/CI/bots/linear per slot+canonical)
│   ├── migrate_slots.py     # WAVE 3.0: one-shot pre-3.0 → 3.0 layout migration
│   ├── drift.py             # detect_drift + assert_aligned (cached path)
│   ├── evacuate.py          # WAVE 2.9: per-repo evacuate primitive (stash → wt-add → pop)
│   ├── feature_state.py     # 9-state machine, dashboard backend (live git, worktree-aware)
│   ├── bot_resolutions.py   # M3: persistent log of bot comments addressed via `commit --address`
│   ├── bot_status.py        # M3: per-feature bot-comment rollup
│   ├── augments.py          # M2: per-workspace augment resolver (preflight_cmd, review_bots, ...)
│   ├── bootstrap.py         # M6: env-file copy + install_cmd + IDE workspace gen for worktrees
│   ├── conflicts.py         # M12: cross-feature file/line overlap detection
│   ├── draft_replies.py     # M9: file-history-based addressed-comment classifier + reply templates
│   ├── historian.py         # M4: cross-session feature memory at .canopy/memory/<feature>.md
│   ├── ide_workspace.py     # M6: pure renderer for `.code-workspace` files
│   ├── preflight_state.py   # records preflight result for state machine
│   ├── reads.py             # 4 alias-aware read primitives
│   ├── review_filter.py     # temporal classifier
│   ├── ship.py              # M8: PR open/update orchestrator with cross-repo body links
│   ├── stash.py             # feature-tagged stash save/list/pop
│   ├── switch.py            # WAVE 3.0: slot-model focus primitive (+ --to-slot / --evict-to)
│   ├── switch_preflight.py  # WAVE 3.0: predictable-failure detection for switch
│   ├── triage.py            # cross-repo PR enumeration + priority tiers (slot-enriched)
│   ├── last_visit.py        # per-feature last-visit anchor (visits.json get/mark/reset)
│   ├── resume.py            # feature_resume compound action + resume_summary (counts-only)
│   ├── thread_actions.py    # GH thread resolve/reply wrappers + local resolution log
│   └── thread_resolutions.py  # thread_resolutions.json load/record/filter_since
├── agent/
│   └── runner.py            # canopy_run — directory-safe shell exec
├── agent_setup/             # ships bundled skills + setup_agent installer
│   ├── __init__.py          # install_skill / install_mcp / check_status
│   └── skills/              # one SKILL.md per skill name
│       ├── using-canopy/SKILL.md     # default, always installed
│       └── augment-canopy/SKILL.md   # opt-in via --skill augment-canopy (M2)
├── integrations/
│   ├── linear.py            # Linear issue fetching (via mcp/client.py)
│   ├── github.py            # GitHub PR + comments (MCP or gh CLI fallback)
│   └── precommit.py         # detect + run pre-commit hooks
└── mcp/
    ├── server.py            # MCP server — 67 tools, stdio transport
    └── client.py            # MCP client — stdio + HTTP+OAuth transports
```

## Key conventions

- **`git/repo.py` is the only module that calls `subprocess.run(["git", ...])`.** Everything else routes through it. Keeps the git layer testable and replaceable.
- **`mcp/server.py` and `cli/main.py` are thin wrappers.** Business logic lives in `actions/`, `features/coordinator.py`, `git/multi.py`, `workspace/`.
- **All CLI commands support `--json`.** This is the contract between CLI, MCP, and any GUI. Same JSON shape across surfaces.
- **Actions return structured errors.** `BlockerError(code, what, expected, actual, fix_actions, details)`. CLI renders via `cli/render.py`; MCP returns `to_dict()`. Same shape, two consumers.
- **Universal aliases** — every read tool accepts feature name, Linear ID, `<repo>#<n>`, PR URL, `<repo>:<branch>`, or slot id (`worktree-N` → slot's current occupant). Resolved by `actions/aliases.py:resolve_feature` (with single-repo + per-repo-branch fallbacks).
- **Per-repo branches map** — `FeatureLane.branches: dict[repo, branch]` overrides "branch == feature name" for legacy mismatched-naming features. Use `lane.branch_for(repo)` or `repos_for_feature(workspace, feature)` everywhere — never recompute as `[r for r in feature.repos]` with feature name as branch (regresses Gap 2).
- **Feature lanes use real Git branches and worktrees.** No virtual branches.
- **Feature metadata lives in `.canopy/features.json`. Worktrees in `.canopy/worktrees/worktree-N/<repo>/` (generic numbered slots).** A slot holds one feature at a time; a feature's repos sit as siblings inside its slot. Canonical (main repo dirs) is the only place to *run* code; worktrees are passive branch storage.
- **State files** at `.canopy/state/heads.json` (post-checkout hook output), `.canopy/state/preflight.json` (preflight tracker), `.canopy/state/slots.json` (canonical + warm slot occupancy + `last_touched` LRU map + `in_flight` transaction marker), `.canopy/state/visits.json` (per-feature last-visit anchor: `{feature: {last_visit, previous_visit}}`), and `.canopy/state/thread_resolutions.json` (log of GH review threads canopy itself resolved: `{thread_id: {resolved_by_canopy_at, feature, via_command, via_commit_sha}}`). OAuth tokens at `~/.canopy/mcp-tokens/`.
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
- **Slot limits:** `[workspace] slots = N` in canopy.toml caps the number of warm slots (default **2**, so 1 canonical + 2 warm = 3 live trees max). The pre-3.0 `max_worktrees` key now raises `ConfigError` pointing at `canopy migrate-slots`. See `actions/switch_preflight.py:warm_slot_cap`.
- **Action contract:** `actions/protocol.py` (planned) will formalize the per-repo `{status, before, after, reason?}` shape. For now, each action returns it ad-hoc.
- **Skill bundling:** Bundled skills live at `src/canopy/agent_setup/skills/<name>/SKILL.md`. `canopy setup-agent` copies them to `~/.claude/skills/<name>/SKILL.md`. The default `using-canopy` skill always installs; opt-in extras (e.g. `augment-canopy`) install via `--skill <name>` (repeatable). Foreign skills with the same path are not overwritten without `--reinstall`. The `_SKILL_SOURCE` constant remains as a backward-compat alias pointing at `using-canopy`'s source.
- **Version bumps:** When shipping a milestone, bump `__version__` in [`src/canopy/__init__.py`](src/canopy/__init__.py) and add a section to [`CHANGELOG.md`](CHANGELOG.md). The version handshake (`canopy --version`, `mcp__canopy__version`, doctor's `cli_stale` / `mcp_stale` checks) is only useful when this number actually moves — drift was the bug 0.5.0 caught.

## MCP Server (67 tools)

Grouped by topic. Run with `canopy-mcp` (entry point) or `python -m canopy.mcp.server`.

```
Meta:         version, doctor              # 21-code / 12-category recovery primitive
Workspace:    workspace_status, workspace_context, workspace_config, workspace_reinit
Feature:      feature_create, feature_list, feature_status, feature_diff,
              feature_changes, feature_merge_readiness, feature_paths, feature_done,
              feature_link_linear, feature_state
Slots:        slots, slot_load, slot_clear, slot_swap, migrate_slots   # WAVE 3.0
Actions:      switch, triage, drift, conflicts   # switch is the slot-model focus primitive
Reads:        linear_get_issue, github_get_pr, github_get_branch, github_get_pr_comments,
              linear_my_issues, pr_checks         # pr_checks = M10 CI rollup
Workflow:     ship, draft_replies, feature_resume  # M8 + M9 + Plan 2 — capstone + reply drafts + session resume
Threads:      resolve_thread, reply_to_thread      # Plan 2 — GH review thread mutations + local log
Run/Pre:      run, preflight, review_status, review_comments, review_prep
Stash:        stash_save_feature, stash_list_grouped, stash_pop_feature,
              stash_save, stash_pop, stash_list, stash_drop
Worktree:     worktree_create, worktree_info, worktree_bootstrap   # bootstrap = M6
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
- Adding a new ⨯ tool to canopy → also update `~/.claude/skills/using-canopy/SKILL.md` and `src/canopy/agent_setup/skills/using-canopy/SKILL.md` so the agent learns when to prefer it.
