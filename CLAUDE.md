# Canopy — Claude Code Context

## What This Project Is

Canopy is the **context contract** between an AI coding agent and a multi-repo workspace, plus a **drift-proof CLI** for the human. Every operation takes semantic context (`feature`, `repo`, alias) and resolves paths internally — the agent literally can't `cd` to the wrong directory because it never specifies a directory. Multi-repo drift is detected in real time via per-repo post-checkout hooks and surfaced as a structured `BlockerError`. PR review comments are temporally classified into `actionable_threads` vs `likely_resolved_threads`, so the agent's context budget goes to comprehension, not orchestration.

**Two surfaces (4.0 "the great distillation").** Canopy is split into (1) an **agent contract** — the **15 MCP tools** the agent needs to work safely and stay oriented (path-safety + registry + focus + safe-git-ops + recovery), and (2) a **human/dashboard management surface** — PR triage, review-comment classification, bot rollups, ship, historian, resume briefs, conflict detection, Linear/GitHub reads — which is NOT on the agent surface. Management lives in `canopy/management/` and is reached by the human (or dashboard) via `canopy <cmd> --json`. Nothing was deleted; management moved off the agent surface so the agent's context budget goes to comprehension, not orchestration.

**`canopy switch` is the focus primitive (Wave 3.0 slot model).** Each feature lives in one of three states: **canonical** (checked out in main repo — the only place code is meant to run), **warm** (occupies a numbered slot at `.canopy/worktrees/worktree-N/<repo>/`), **cold** (branch only). Slots are stable disk resources; features are transient tenants — a slot keeps its id (`worktree-1`, `worktree-2`, ...) across feature swaps. `switch(Y)` promotes Y to canonical; previously-canonical X either evacuates into a warm slot (active rotation, default — instant to switch back) or goes cold with a feature-tagged stash (wind-down via `--release-current`). Cap (`slots`, default 2) protects against unbounded growth via LRU eviction or a `worktree_cap_reached` BlockerError. See [docs/concepts.md §4](docs/concepts.md#4-the-slot-model).

## Architecture

```
src/canopy/
├── cli/main.py              # argparse entry point; ALL commands (core + management), each --json
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
│                             #   (review_status/comments/prep extracted to management/review_ops.py in 4.0)
├── actions/                 # AGENT-CORE — the 15-tool surface + core primitives (imports NO management)
│   ├── errors.py            # ActionError / BlockerError / FailedError / FixAction
│   ├── aliases.py           # universal alias resolver (incl. worktree-N → slot occupant)
│   ├── registry.py          # context — the two-tier workspace map (local instant + remote PR/CI overlay)
│   ├── start.py / join.py   # registry writes: lazy feature start; register a repo into active feature
│   ├── switch.py            # WAVE 3.0: slot-model focus primitive (+ --to-slot / --evict-to)
│   ├── reclaim.py           # free a warm slot whose PR merged
│   ├── slots.py             # slots.json reader/writer + path resolution + LRU
│   ├── slot_load.py / slot_bootstrap.py / slot_policy.py   # slot lifecycle primitives
│   ├── switch_preflight.py  # WAVE 3.0: predictable-failure detection for switch
│   ├── migrate_slots.py     # WAVE 3.0: one-shot pre-3.0 → 3.0 layout migration
│   ├── evacuate.py          # WAVE 2.9: per-repo evacuate primitive (stash → wt-add → pop)
│   ├── commit.py            # feature-scoped multi-repo commit (commit-only in 4.0; --address dropped)
│   ├── push.py / stash.py   # push; feature-tagged stash save/list/pop
│   ├── drift.py             # detect_drift + assert_aligned (cached path)
│   ├── preflight_state.py   # records preflight result for state machine
│   ├── bootstrap.py         # M6: env-file copy + install_cmd + IDE workspace gen for worktrees
│   ├── ide_workspace.py     # M6: pure renderer for `.code-workspace` files
│   ├── augments.py          # M2: per-workspace augment resolver (preflight_cmd, review_bots, ...)
│   ├── pr_map.py            # NEW 4.0: PR-mapping (branch↔PR↔feature); feeds context remote tier
│   ├── prs_cache.py         # PR overlay cache for the remote tier
│   ├── repo_paths.py        # NEW 4.0: resolve_repo_paths (core path helper)
│   ├── active.py / advisories.py   # active-feature resolution; advisory surfacing
│   ├── doctor.py            # 21-code recovery primitive
│   └── hook_gate.py / hook_context.py   # NEW 4.0: Claude Code enforcement hooks (PreToolUse git gate + SessionStart brief)
├── management/              # NEW 4.0: quarantined HUMAN/dashboard surface — CLI --json only, NO MCP
│   ├── review_ops.py        # review_status/comments/prep (extracted from coordinator)
│   ├── review_filter.py     # temporal classifier (actionable vs likely-resolved)
│   ├── reads.py             # alias-aware read primitives
│   ├── draft_replies.py     # M9: file-history-based addressed-comment classifier + reply templates
│   ├── thread_actions.py    # GH thread resolve/reply wrappers + local resolution log
│   ├── thread_resolutions.py  # thread_resolutions.json load/record/filter_since
│   ├── bot_status.py        # M3: per-feature bot-comment rollup
│   ├── bot_resolutions.py   # M3: persistent log of bot comments addressed via commit
│   ├── historian.py         # M4: cross-session feature memory at .canopy/memory/<feature>.md
│   ├── resume.py            # feature_resume compound action + resume_summary (counts-only)
│   ├── last_visit.py        # per-feature last-visit anchor (visits.json get/mark/reset)
│   ├── ship.py              # M8: PR open/update orchestrator with cross-repo body links
│   ├── conflicts.py         # M12: cross-feature file/line overlap detection
│   ├── slot_details.py      # rich slots shape (PR/CI/bots/linear per slot+canonical)
│   ├── triage.py            # cross-repo PR enumeration + priority tiers (slot-enriched)
│   └── feature_state.py     # 9-state machine, dashboard backend (live git, worktree-aware)
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
    ├── server.py            # MCP server — 15 agent tools, stdio transport
    └── client.py            # MCP client — stdio + HTTP+OAuth transports
```

## Key conventions

- **`git/repo.py` is the only module that calls `subprocess.run(["git", ...])`.** Everything else routes through it. Keeps the git layer testable and replaceable.
- **Agent-core imports NOTHING from management.** `actions/`, `features/`, `agent/` must not import from `canopy.management` — enforced by `tests/test_import_boundary.py`. Management may depend on agent-core, never the reverse.
  - Adding an **agent tool** → implement in `actions/` and register under `@mcp.tool()` in `mcp/server.py`.
  - Adding a **management / human tool** → implement in `canopy/management/` and wire the CLI only (a `cmd_<name>` in `cli/main.py`) — **no `@mcp.tool`**.
- **`mcp/server.py` and `cli/main.py` are thin wrappers.** Business logic lives in `actions/`, `management/`, `features/coordinator.py`, `git/multi.py`, `workspace/`.
- **All CLI commands support `--json`.** This is the contract between CLI, MCP, and any GUI (the dashboard consumes management via CLI `--json`). Same JSON shape across surfaces.
- **Actions return structured errors.** `BlockerError(code, what, expected, actual, fix_actions, details)`. CLI renders via `cli/render.py`; MCP returns `to_dict()`. Same shape, two consumers.
- **Universal aliases** — every read tool accepts feature name, Linear ID, `<repo>#<n>`, PR URL, `<repo>:<branch>`, or slot id (`worktree-N` → slot's current occupant). Resolved by `actions/aliases.py:resolve_feature` (with single-repo + per-repo-branch fallbacks).
- **Per-repo branches map** — `FeatureLane.branches: dict[repo, branch]` overrides "branch == feature name" for legacy mismatched-naming features. Use `lane.branch_for(repo)` or `repos_for_feature(workspace, feature)` everywhere — never recompute as `[r for r in feature.repos]` with feature name as branch (regresses Gap 2).
- **Feature lanes use real Git branches and worktrees.** No virtual branches.
- **Feature metadata lives in `.canopy/features.json`. Worktrees in `.canopy/worktrees/worktree-N/<repo>/` (generic numbered slots).** A slot holds one feature at a time; a feature's repos sit as siblings inside its slot. Canonical (main repo dirs) is the only place to *run* code; worktrees are passive branch storage.
- **State files** at `.canopy/state/heads.json` (post-checkout hook output), `.canopy/state/preflight.json` (preflight tracker), `.canopy/state/slots.json` (canonical + warm slot occupancy + `last_touched` LRU map + `in_flight` transaction marker), `.canopy/state/visits.json` (per-feature last-visit anchor: `{feature: {last_visit, previous_visit}}`), and `.canopy/state/thread_resolutions.json` (log of GH review threads canopy itself resolved: `{thread_id: {resolved_by_canopy_at, feature, via_command, via_commit_sha}}`). OAuth tokens at `~/.canopy/mcp-tokens/`.
- **MCP client supports two transports.** Stdio (existing) for npm/python servers. HTTP+OAuth (new) for hosted servers like Linear's `mcp.linear.app`. Tokens cache per server.
- **GitHub fallback to gh CLI.** When no `github` MCP server is configured, `integrations/github.py` falls back to `gh api` / `gh pr` for the same return shapes. If neither is available, raises `BlockerError(code='github_not_configured')` with platform-aware install hints.
- **Single source of truth for state.** `management/feature_state.py` uses live git (not heads.json) so it's correct even when the hook hasn't fired. `drift` uses heads.json for the fast cached path.
- **Feature-aware stash tagging** — `stash save --feature` writes `[canopy <feature> @ <ts>] <message>`. Parser tolerates git's `On <branch>: ` auto-prefix.

## Build & Test

```bash
pip install -e ".[dev]"
pytest tests/ -v          # ~987 tests, ~60s
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
- **Enforcement hooks (4.0):** canopy ships Claude Code hooks. A **PreToolUse git gate** (`actions/hook_gate.py`) resolves the effective directory of a git command — through cd-chains, `git -C`, heredocs — and blocks mutations from the wrong path / wrong branch. A **SessionStart brief** (`actions/hook_context.py`) orients the agent. This is the enforcement half of "the agent can't `cd` wrong."
- **`--no-track` on branch creation:** `git/repo.py:create_branch` and `worktree_add` always pass `--no-track` so a `branch.autoSetupMerge=inherit` gitconfig doesn't accidentally set the new branch's upstream to `dev`.
- **Slot limits:** `[workspace] slots = N` in canopy.toml caps the number of warm slots (default **2**, so 1 canonical + 2 warm = 3 live trees max). The pre-3.0 `max_worktrees` key now raises `ConfigError` pointing at `canopy migrate-slots`. See `actions/switch_preflight.py:warm_slot_cap`.
- **Action contract:** `actions/protocol.py` (planned) will formalize the per-repo `{status, before, after, reason?}` shape. For now, each action returns it ad-hoc.
- **Skill bundling:** Bundled skills live at `src/canopy/agent_setup/skills/<name>/SKILL.md`. `canopy setup-agent` copies them to `~/.claude/skills/<name>/SKILL.md`. The default `using-canopy` skill always installs; opt-in extras (e.g. `augment-canopy`) install via `--skill <name>` (repeatable). Foreign skills with the same path are not overwritten without `--reinstall`. The `_SKILL_SOURCE` constant remains as a backward-compat alias pointing at `using-canopy`'s source.
- **Version bumps:** When shipping a milestone, bump `__version__` in [`src/canopy/__init__.py`](src/canopy/__init__.py) and add a section to [`CHANGELOG.md`](CHANGELOG.md). The version handshake (`canopy --version`, `mcp__canopy__version`, doctor's `cli_stale` / `mcp_stale` checks) is only useful when this number actually moves — drift was the bug 0.5.0 caught.

## MCP Server (15 agent tools)

The agent surface is distilled to the 15 tools of the core loop. Run with `canopy-mcp` (entry point) or `python -m canopy.mcp.server`.

```
Meta:          version                                  # version handshake for doctor staleness
Registry:      context, start, join                     # single-read workspace map; lazy feature start; register a repo
Focus / slots: switch, reclaim                          # promote a feature into trunk (run target); free a merged warm slot
Safe git ops:  run, commit, push, preflight             # path-safe exec; feature-scoped commit (commit-only); push; pre-commit gate
Recovery:      doctor, drift                            # 21-code / 11-category integrity check + repair; branch-drift detection
WIP + slots:   stash_save_feature, stash_pop_feature, worktree_bootstrap   # feature-tagged stash; bootstrap a warm slot
```

`context` is THE registry read — feature ↔ repo ↔ branch ↔ path ↔ state, with a local (instant) tier and a remote (PR/CI overlay) tier. It supersedes the old `workspace_status` / `workspace_context` / `feature_list` / `feature_status` / `slots`.

**The management surface is NOT MCP.** Triage, review (status/comments/prep), ship, historian, bot rollups, thread resolve/reply, draft-replies, resume briefs, conflicts, Linear/GitHub reads, `feature_state` — all live in `canopy/management/` and are reached by the human/dashboard via `canopy <cmd> --json`. The CLI kept ALL of these commands; only the agent (MCP) surface was distilled.

**~25 borderline tools are commented off the MCP surface** (reversible — one uncomment away; the code stays in `actions/`): `slots`, `feature_list/status/paths/create/done`, `workspace_config/reinit`, `slot_load/clear/swap`, `migrate_slots`, and the git-plumbing `checkout/log/sync/branch_*/stash_*` (raw) / `worktree_info/worktree_create`. Rationale: git plumbing is reachable path-safely via `run "git …"`, and the feature/slot lifecycle reads are subsumed by `context`.

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
- **Two-surface rule:** decide which surface a new tool belongs on before writing it (see the import-boundary convention above).
  - **New agent tool:** stub in `src/canopy/actions/`, raise `BlockerError` for preconditions, register under `@mcp.tool()` in `mcp/server.py`, expose the CLI in `cli/main.py`. Import NOTHING from `canopy.management`. Update `docs/mcp.md` and `docs/agents.md`.
  - **New management / human tool:** stub in `src/canopy/management/`, wire the CLI only (`cmd_<name>` in `cli/main.py`) with `--json` — do NOT add an `@mcp.tool`. Update `docs/commands.md`.
  - Add tests in `tests/test_<name>.py` using the existing `workspace_with_feature` fixture.
- New CLI commands: define a handler `cmd_<name>(args)`, add a subparser in `main()`, dispatch in the `commands` dict. Update `docs/commands.md`.
- Adding a new agent tool to canopy → also update `~/.claude/skills/using-canopy/SKILL.md` and `src/canopy/agent_setup/skills/using-canopy/SKILL.md` so the agent learns when to prefer it.
