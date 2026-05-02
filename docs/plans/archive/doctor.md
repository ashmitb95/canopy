---
status: shipped
priority: P0
effort: ~3-4d
depends_on: []
---

# `canopy doctor` — state-file integrity checker + repair

## Why

Canopy keeps state in five places: `canopy.toml`, `.canopy/features.json`, `.canopy/state/heads.json`, `.canopy/state/active_feature.json`, `.canopy/state/preflight.json` — plus the per-repo `post-checkout` hooks and the `.canopy/worktrees/` directory tree. Every operation reads or writes some subset of these.

Today, if any of these get out of sync — partial write after a crash, manual edit gone wrong, file-system snapshot restore, post-checkout hook silently uninstalled by another tool — canopy doesn't notice. The next operation reads stale state, makes a decision based on it, and either fails opaquely or compounds the corruption.

`canopy doctor` is the safety net: walk every state file, cross-reference with live git + filesystem, surface inconsistencies with diagnostic codes, and auto-repair the obvious cases when invoked with `--fix`.

This is the first thing a user (or agent) runs when they suspect "something is off" — before they go hunting through stash lists and worktree paths. Returns structured JSON so an agent can act on the findings programmatically.

---

## Behavioral spec

`canopy doctor [--check | --fix | --fix=<category>] [--feature <X>]`

Default mode is `--check`: report only, no modifications. `--fix` repairs every fixable issue. `--fix=<category>` repairs just one category (heads / worktrees / hooks / preflight / features). `--feature <X>` scopes the diagnosis to one feature instead of the whole workspace.

### Diagnostic categories (each maps to a `code`)

**`heads_stale`** — `.canopy/state/heads.json` has a per-repo head sha that doesn't match `git rev-parse HEAD` in that repo.
- Cause: post-checkout hook didn't fire (e.g., hook uninstalled, race on concurrent checkout, file write failure)
- Fix: rewrite `heads.json` from live git
- Severity: warn (state will self-correct on next checkout)

**`active_feature_orphan`** — `.canopy/state/active_feature.json` points at a feature that no longer exists in `features.json`.
- Cause: manual `features.json` edit, `done` ran but didn't clear active state
- Fix: clear `active_feature.json` (back to no-active-feature)
- Severity: error (subsequent commands will misbehave)

**`active_feature_path_missing`** — `active_feature.json` lists per-repo paths that don't exist on disk.
- Cause: worktree manually deleted, filesystem restore
- Fix: re-resolve paths from `features.json` + `lane.repo_states[*].worktree_path`
- Severity: error

**`worktree_orphan`** — directory in `.canopy/worktrees/` that isn't referenced by any feature in `features.json`.
- Cause: feature done'd via raw git, partial cleanup, manual mkdir
- Fix: prompt for removal (or `--fix` removes; `--fix-worktrees` honored, others ignored)
- Severity: warn

**`worktree_missing`** — `features.json` lists `worktree_path` for a feature × repo pair, but the directory doesn't exist.
- Cause: filesystem restore, manual rm, partial done that updated features.json before removing dir (shouldn't happen but defense in depth)
- Fix: clear the worktree_path entry; mark feature as cold for that repo
- Severity: error

**`hook_missing`** — repo doesn't have canopy's post-checkout hook installed (or has a different one not chaining canopy's).
- Cause: hook uninstalled by another tool, fresh clone of an existing canopy workspace
- Fix: re-run hook installation for that repo
- Severity: error (drift detection will silently fail)

**`hook_chained_unsafe`** — hook exists but the chain is broken (canopy's hook calls a previous hook that no longer exists, or a previous hook returns non-zero unexpectedly).
- Cause: user reinstalled their global hooks, husky reset, etc.
- Fix: surface the broken chain; recommend `canopy hooks reinstall` (existing command)
- Severity: warn

**`preflight_stale`** — `.canopy/state/preflight.json` records a passed result, but the recorded `head_sha_per_repo` no longer matches current HEAD on any of the repos.
- Cause: commits made after preflight ran (preflight result is no longer authoritative for current state)
- Fix: clear stale preflight entries
- Severity: info (not strictly broken, just no longer valid signal)

**`features_unknown_repo`** — `features.json` references a repo name that's not in `canopy.toml`.
- Cause: repo removed from canopy.toml without `done`-ing affected features
- Fix: surface; no auto-fix (user has to decide whether to remove the feature or restore the repo)
- Severity: error

**`branches_missing`** — feature has `branches[repo]` set to a branch name that doesn't exist as a local branch in the repo.
- Cause: user deleted the branch via raw git, accidental `done` partial run
- Fix: surface; offer to remove the feature (no auto-fix)
- Severity: error

### Output shape (--json)

```python
{
  "workspace": "canopy-test",
  "checked_at": "2026-04-28T12:34:56Z",
  "issues": [
    {
      "code": "heads_stale",
      "severity": "warn",
      "what": "heads.json out of sync for test-api",
      "expected": "abc123de",
      "actual": "9c2e1abc",
      "repo": "test-api",
      "fix_action": "rewrite heads.json from live git",
      "auto_fixable": true,
    },
    ...
  ],
  "summary": {"errors": 1, "warnings": 2, "info": 0},
  "fixed": [],     # populated when --fix ran
  "skipped": [],   # issues that --fix couldn't repair
}
```

### CLI rendering

Issues grouped by severity, with `severity glyph` (✗ error / ! warn / · info), code, and one-line `what`. `--verbose` adds `expected` / `actual`. `--fix` shows what was repaired.

---

## State model changes

None. Doctor reads existing state, repairs in place. Doesn't introduce new state files.

---

## Command surface changes

| Today | After |
|---|---|
| `canopy doctor` (does not exist) | New CLI command + MCP tool. |
| `canopy hooks reinstall` (existing — see `cmd_hooks`) | Unchanged. Doctor surfaces a `hook_missing` issue with a recommendation pointing at it. |
| `canopy workspace reinit` (existing) | Unchanged. Doctor recommends it for `features_unknown_repo` and similar wide-scope issues. |

---

## Files to touch

### New

- `src/canopy/actions/doctor.py` — orchestrator. One check function per category (each pure: takes workspace, returns list of `Issue` dataclass). Aggregator runs all checks (or a subset), composes the structured result. Repair functions are separate (each takes the issue, returns repair-result).
- `tests/test_doctor.py` — table-driven cases for each category. Use `workspace_with_feature` fixture + targeted state-file mutations.

### Modified

- `src/canopy/cli/main.py` — `cmd_doctor(args)`, dispatch + subparser. Render via existing `cli/render.py` style.
- `src/canopy/mcp/server.py` — register `doctor(check=True, fix=False, fix_categories=None, feature=None)` MCP tool.
- `docs/commands.md` — `doctor` section with example output.
- `docs/agents.md` — agent recipe: "if a canopy operation returns an unexpected error, call `mcp__canopy__doctor` first to see whether state is corrupted."
- Both skill files — flag `doctor` as the recovery entry point.

---

## Tasks (rough sequence)

### T1 — `Issue` dataclass + check protocol

`actions/doctor.py:Issue(code, severity, what, expected, actual, repo, feature, fix_action, auto_fixable)`. Each check function returns `list[Issue]`. Pure — takes workspace, no side effects.

### T2 — One check per category

Implement nine check functions (one per code in the matrix above). Each is a small pure function reading specific state files / git output and producing zero or more `Issue` records.

Tests: per-category fixtures that create a known-bad state, assert the right issues are reported.

### T3 — Repair functions

Per category, a `repair_<category>(workspace, issue) -> RepairResult` function. RepairResult has `{success, action_taken, error?}`. Repairs either: rewrite a state file, remove a worktree, reinstall a hook, or surface "no auto-fix possible."

Tests: per-category fixture, run check → repair → re-check → assert clean.

### T4 — Aggregator orchestrator

`doctor(workspace, fix=False, fix_categories=None, feature=None)`. Runs all checks (or filtered to feature scope), collects issues, optionally runs repairs, returns the structured result dict.

### T5 — CLI rendering

Group by severity, show counts, render each issue. `--verbose` for expected/actual. `--fix` shows repaired issues.

### T6 — MCP tool registration

Thin wrapper over the action. Returns the structured dict directly.

### T7 — Docs + skills

`docs/commands.md`, `docs/agents.md`, both skill files updated.

### T8 — Recovery integration test

End-to-end: workspace with feature → corrupt heads.json → call `doctor` → assert issues reported → call with `--fix` → assert state repaired → assert `doctor` returns clean.

---

## Edge cases to remember

- **Concurrent ops while doctor runs.** If a switch is happening in another terminal, doctor might see transient state. Doctor reads with a short retry/stabilize loop (read state, wait 100ms, re-read; if changed, defer the issue). Not a hard guarantee.
- **Doctor itself corrupts state on `--fix`.** Every repair writes to a tmp file then atomic-renames. If the rename fails, the original is preserved.
- **Hook detection on Husky workspaces.** Husky sets `core.hooksPath`. Doctor respects that — looks for canopy's hook in the configured hooksPath, not just `.git/hooks/`.
- **Workspace with no features.** Most checks short-circuit cleanly (empty issue list). Don't surface "no features" as an issue.
- **`--fix` and worktree removal.** Removing an orphan worktree dir uses `git worktree remove --force` to ensure git's worktree registry is cleaned. Doctor prompts confirmation in CLI mode (skipped with `--yes`); MCP mode auto-confirms (the agent invoked it, presumably knowing what it's doing).

---

## Out of scope

- **Predictive diagnostics.** Doctor reports current-state issues, not "your workflow is going to break in 3 commits." Static analysis of features.json beyond cross-references is out.
- **Cross-workspace doctor.** One workspace per invocation.
- **Linear / GitHub external state.** Doctor doesn't reach out to verify Linear issue exists or PR is open. That's `triage` / `review_status` territory. Boundaries respected.

---

## After this lands

- An agent that gets an unexpected error from any canopy MCP call has a clear next-step: call `doctor`. Recovery becomes mechanical.
- Users with shared workspaces (multiple shells, occasional crashes) have a one-command sanity check.
- The README's "Why it's load-bearing" table picks up another row: *"Canopy state files get out of sync — heads.json is stale after a crash, an orphan worktree directory lingers from a partial done."* → `canopy doctor` finds and fixes.
- Pairs with the `audit log` plan (if shipped) — doctor can read the recent audit trail to suggest causes for issues found.

---

## Addendum (2026-05-02) — Install-staleness categories + version handshake

The original "canopy upgrade" plan was absorbed into doctor: machine-level artifact staleness (CLI / MCP / vsix / skill / .mcp.json) is the same kind of work as workspace-state-file integrity (diagnose → classify → repair). One unified `canopy doctor` command, growing taxonomy.

### Six new diagnostic categories (added on top of the original 9)

| Code | Severity | Detection | Repair |
|---|---|---|---|
| `cli_stale` | warn | `canopy --version` < `__version__` (sourced from `src/canopy/__init__.py`) | re-pip-install or re-pipx-install (detected from install method) |
| `mcp_stale` | error | MCP `version()` tool returns version < `__version__`, or tool missing entirely | reinstall the canopy-mcp venv via the existing `runInstallBackend` pattern from the extension |
| `mcp_missing_in_workspace` | error | `<workspace>/.mcp.json` lacks a `canopy` entry, or its `CANOPY_ROOT` doesn't match the workspace root | `install_mcp(workspace_root, reinstall=True)` |
| `skill_missing` | warn | no `SKILL.md` at `~/.claude/skills/<name>/` for any skill in the configured list (`using-canopy`, `augment-canopy`, future) | `install_skill(name)` for each missing |
| `skill_stale` | warn | byte-compare against the bundled source returns mismatch | `install_skill(name, reinstall=True)` |
| `vsix_duplicates` | info | multiple `singularityinc.canopy-*` directories in `~/.vscode/extensions/` | report stale candidates; `--clean-vsix` flag removes non-current versions (active version preserved) |

Total diagnostic categories after this addendum: **15** (9 original + 6 install-staleness).

### Version handshake (precondition for the new categories)

Three reporting layers, all sourcing from `src/canopy/__init__.py:__version__`:

- **CLI:** `canopy --version` (argparse `version` action)
- **MCP server:** new `version()` MCP tool returning `{cli_version, mcp_version, schema_version}`. Schema version starts at `"1"` and bumps on canopy.toml schema changes (independent of the package version).
- **VSCode extension:** at MCP startup, calls `version()` once. Logs a warning on minor version mismatch; refuses activation on major mismatch with a toast offering `canopy doctor --fix`.

### Files to touch (additions)

- `src/canopy/__init__.py` — `__version__` constant (sourced from `pyproject.toml`)
- `src/canopy/cli/main.py` — `--version` argparse action; `cmd_doctor` extended to call install-staleness checks
- `src/canopy/mcp/server.py` — register the new `version()` tool
- `src/canopy/actions/doctor.py` — six new check functions + six new repair functions, slotted into the existing `Issue` / repair pattern
- `vscode-extension/src/canopyClient.ts` — version handshake on MCP startup
- `tests/test_doctor.py` — extend with install-staleness fixtures (mock binaries with stale version output, missing skill/mcp.json, vsix dir scenarios)

### New CLI flags

- `canopy doctor --check` (existing, no behavior change) — adds the 6 new categories to the report
- `canopy doctor --fix` (existing) — repairs everything fixable; `cli_stale` and `mcp_stale` repairs may require a process restart, returning `BlockerError(code='reload_required', fix_action='reload window')` rather than blocking silently
- `canopy doctor --clean-vsix` (new) — extends `--fix` to also remove `vsix_duplicates`-flagged stale extension dirs

### Sequence note

This addendum's categories require the `__version__` constant + the `version()` MCP tool to exist. They land together in the doctor PR, not as a separate version-handshake PR. The vsix duplicate detector and the skill-staleness checker have no version dependency and could ship slightly earlier in development if useful.
