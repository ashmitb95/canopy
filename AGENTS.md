# Canopy — Contributor Guide for AI Agents

This file is the "how to extend canopy without breaking module boundaries" guide.
It is CLAUDE.md's sibling, not its replacement:

- `CLAUDE.md` — what canopy is, architecture overview, key conventions, MCP tool list
- `docs/concepts.md` — the four conceptual pillars (action framework, context contract, state machine, slot model, resume brief)
- `docs/architecture.md` — formal module reference

## Before You Start

1. Read `CLAUDE.md`. It has the architecture diagram, slot model explanation, and all key conventions.
2. Read `docs/concepts.md` if you need the vocabulary for the state machine or action framework.
3. Run the test suite to confirm your baseline: `pytest tests/ -v` (857 tests, ~225s).
4. If you are adding to the slot model or switch flow, read `actions/slots.py` and `actions/switch.py` first.

## Module Boundaries

These are hard rules. Do not break them.

- **`git/repo.py` is the only file that calls `subprocess.run(["git", ...])`.**
  New git operations belong here. Everything else calls functions from this module.

- **`git/multi.py` handles cross-repo git operations.** It calls `git/repo.py` functions;
  it does not shell out to git directly.

- **`mcp/server.py` and `cli/main.py` are thin wrappers.**
  Business logic lives in `actions/`, `features/coordinator.py`, `git/multi.py`,
  and `workspace/`. Neither the MCP server nor the CLI should own logic.

- **All actions live in `actions/`.** This is the most-modified directory. Each action
  module owns one concern: `switch.py` owns slot focus, `slots.py` owns slot state
  reads/writes, `drift.py` owns drift detection, `resume.py` owns the resume brief, etc.

- **Actions raise `BlockerError` for precondition failures.**
  Shape: `BlockerError(code, what, expected, actual, fix_actions, details)`.
  CLI renders via `cli/render.py`. MCP returns `to_dict()`. Same shape, two consumers.

- **Universal aliases — every read tool accepts multiple forms.**
  Feature name, Linear ID, `<repo>#<n>`, PR URL, `<repo>:<branch>`, or slot id
  (`worktree-N` → slot's current occupant). Always resolve via
  `actions/aliases.py:resolve_feature`. Never reimplement alias resolution inline.

- **Per-repo branches map — never assume branch == feature name.**
  Use `lane.branch_for(repo)` or `repos_for_feature(workspace, feature)`.
  `FeatureLane.repos` alone does not give you branch names for legacy features.

- **All integrations go through `mcp/client.py` or the `gh` CLI fallback.**
  Integration modules in `integrations/` never call external APIs directly.
  `integrations/github.py` falls back to `gh api` / `gh pr` when no MCP server
  is configured. If neither is available, raise `BlockerError(code='github_not_configured')`.

- **`integrations/precommit.py` is the one exception to the MCP-only rule.**
  It runs local hooks via subprocess. This is intentional — hooks run locally.

## State Files

All state is under `.canopy/state/`. OAuth tokens at `~/.canopy/mcp-tokens/`.

| File | Owner | Notes |
|---|---|---|
| `heads.json` | `git/hooks.py` + post-checkout hook | Written by hook; read by `drift.py`, `historian.py` |
| `slots.json` | `actions/slots.py` | Canonical + warm slot occupancy, `last_touched` LRU, `in_flight` marker |
| `preflight.json` | `actions/preflight_state.py` | Records preflight result per feature |
| `visits.json` | `actions/last_visit.py` | Per-feature `last_visit` / `previous_visit` ISO timestamps |
| `thread_resolutions.json` | `actions/thread_resolutions.py` | Resolved GitHub review threads |
| `bot_resolutions.json` | `actions/bot_resolutions.py` | Bot-comment resolutions addressed via `commit --address` |

All state writes use atomic temp+rename (`tmp.replace(path)`) to prevent corruption
from concurrent agents. See `actions/slots.py` for the canonical pattern.

## Adding a New Action

This is the most common change.

1. Create `src/canopy/actions/<name>.py`. Raise `BlockerError` for preconditions.
   Use existing fixtures and patterns; don't re-invent error shapes.

2. Expose via CLI in `cli/main.py`:
   - Add `cmd_<name>(args: argparse.Namespace) -> None`
   - Add a subparser in `main()`
   - Dispatch via the `commands` dict
   - Support `--json` via `_print_json()`

3. Expose via MCP in `mcp/server.py`:
   - Add `@mcp.tool()` wrapper that calls the action function
   - Write a clear docstring — it becomes the tool description agents see

4. Add tests in `tests/test_<name>.py` using the `workspace_with_feature` fixture
   (or another fixture from `tests/conftest.py`).

5. If the action is user-facing:
   - Update `docs/commands.md`
   - Update `docs/mcp.md`
   - Update the architecture box and MCP-tool-group listing in `CLAUDE.md`

6. If agents need to know when to prefer the new tool, update
   `~/.claude/skills/using-canopy/SKILL.md` and
   `src/canopy/agent_setup/skills/using-canopy/SKILL.md`.

## Adding a New CLI Command Only

When a new subcommand wraps existing actions without needing a new action module:

1. Add `cmd_<name>(args)` in `cli/main.py` calling existing action functions.
2. Add subparser in `main()`, dispatch in the `commands` dict.
3. Support `--json` via `_print_json()`.
4. Human-readable output: 2-space indent, `─` for separators.
5. Update `docs/commands.md`.

## Adding a New MCP Tool Only

When the action already exists and you just need to expose it:

1. Add `@mcp.tool()` in `mcp/server.py`. Call the existing action function directly.
2. Return dicts/lists (FastMCP handles JSON serialization).
3. Write a docstring — it is the tool description.
4. Update `docs/mcp.md` and the tool-group listing in `CLAUDE.md`.

## Adding a New Git Operation

1. Add the function to `git/repo.py` using `_run()` or `_run_ok()`.
   Prefer `_run()` (raises on failure) for write operations.
   `_run_ok()` (returns empty string on failure) is only safe for reads.
2. Write a test in `tests/test_repo.py`.
3. Do not call `subprocess.run(["git", ...])` anywhere else.

## Adding a New State File

1. Create `actions/<name>.py` with a module docstring naming the path
   (e.g., `State file: .canopy/state/<name>.json`).
2. Use the atomic temp+rename pattern from `actions/slots.py` or
   `actions/thread_resolutions.py`:
   ```python
   tmp = path.with_suffix(".tmp")
   tmp.write_text(json.dumps(data))
   tmp.replace(path)
   ```
3. Update the state-files table in this file.
4. Update the state-files line in `CLAUDE.md`.
5. Update the state-files table in `docs/architecture.md` and
   the state-files section in `docs/workspace.md`.

## Adding a New Integration

1. Add a module in `integrations/`.
2. Use `mcp/client.py` to call the MCP server, or `gh` CLI as fallback.
3. Check for server presence via `mcp.client.get_mcp_config()` before calling.
4. Handle `McpClientError` gracefully — never fail the whole operation because
   an integration is unavailable.
5. If the integration is Linear or GitHub, link metadata into `features.json`
   via `FeatureLane` fields rather than a separate sidecar file.
6. Write tests that mock the MCP call but test the data flow end-to-end.

## Adding a New Bundled Skill

1. Create `src/canopy/agent_setup/skills/<name>/SKILL.md`.
2. Default skills (always installed on `canopy setup-agent`) must be declared
   in `agent_setup/__init__.py`.
3. Opt-in skills install via `canopy setup-agent --skill <name>`.
4. Document the new skill in `docs/agents.md` under the skills section.
5. Foreign skills at the same install path are not overwritten without `--reinstall`.

## Adding a New Augment Key

1. Update `src/canopy/actions/augments.py`.
   The resolver is intentionally lenient — unknown keys are silently preserved,
   so adding a new key is backward-compatible.
2. Consume the new key in whichever action or integration needs it via
   `repo_augments(workspace, repo_name).get("<key>")`.
3. Document the key in the recognized-keys table in
   `src/canopy/agent_setup/skills/augment-canopy/SKILL.md`.
4. Add a `canopy doctor` check if misconfiguration has a clear error form.

## Testing Conventions

- All tests use real temporary Git repos, not mocks. This catches real git behavior.
- Fixtures are in `tests/conftest.py`. Key fixtures:
  - `workspace_dir` — bare workspace with `api/` and `ui/` repos on main
  - `workspace_with_feature` — workspace with `auth-flow` branches + commits in both repos
  - `canopy_toml` — workspace with a canopy.toml already written
- Test file naming: `test_<module>.py` or `test_<feature_area>.py`.
- Worktree tests must clean up with `git worktree remove` when done.
- Run: `pytest tests/ -v` from the `canopy/` directory.

## JSON Output Contract

Every `--json` command and MCP tool returns structured data. The shape is the contract
and is defined in each action's docstring. CLI and MCP return identical bytes.

Key shapes:

| Tool / command | Root shape |
|---|---|
| `workspace_status` | `WorkspaceStatus` (see `Workspace.to_dict()`) |
| `feature_list` | `list[FeatureLane.to_dict()]` |
| `feature_status` | `FeatureLane.to_dict()` with `repo_states` |
| `feature_state` | 9-state machine result + `summary` + `next_actions` |
| `feature_resume` | `version: 1`, `since_last_visit`, `current_state`, `intent_hints` |
| `slots(rich=True)` | `canonical` + per-slot enriched dashboard payload |
| `triage` | priority-tiered cross-repo PR enumeration |

## Context Detection

`workspace/context.py` distinguishes four context types based on cwd:

1. `feature_dir` — inside `.canopy/worktrees/worktree-N/` (slot root; all repos in scope)
2. `repo_worktree` — inside `.canopy/worktrees/worktree-N/<repo>/` (single repo)
3. `repo` — inside a normal workspace repo (feature = current branch if non-default)
4. `workspace_root` — at the canopy.toml level (all repos in scope)

Used by `canopy stage` and other context-sensitive commands.

## Version Handshake

When shipping a milestone:

1. Bump `__version__` in `src/canopy/__init__.py`.
2. Add a section to `CHANGELOG.md`.
3. Doctor's `cli_stale` / `mcp_stale` checks compare against this version —
   the handshake is only useful if the number actually moves.

## Hooks Safety

`git/templates/post-checkout.py` uses `fcntl.flock` and atomic rename so concurrent
fires across repos in the same workspace don't race. It chains any pre-existing user
hooks and is installed by `canopy init` (or `canopy hooks install`). Worktrees inherit
hooks via the git `commondir` mechanism.
