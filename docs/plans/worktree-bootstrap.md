---
status: queued
priority: P2
effort: ~2d
depends_on: ["doctor.md"]
---

# Worktree Bootstrap — env files, dep install, IDE workspace generation

## Why

A new feature worktree is functionally a fresh checkout: branch is set, files are populated, but the developer-facing scaffolding is missing.

- The repo's `.env` / `.env.local` aren't there (gitignored, didn't follow the worktree).
- `node_modules/` / `.venv/` / equivalent isn't there — the worktree is a separate working tree, deps don't carry over.
- IDEs that key off a `.code-workspace` / `.idea/` / `Cargo.toml` workspace file need one written, especially when multiple repos compose the feature.

Without this, the user does the same three steps every time they spin up a worktree: copy the env file, run the install command, hand-edit the workspace file. The docsum `manage-worktrees` skill (a docsum-specific bash wrapper around `git worktree add`) handles all three. Canopy currently does none of them. This plan absorbs the capability — opt-in, configurable per repo, doesn't run unless asked.

Distinct from the broader `manage-worktrees` skill which is hardcoded to two repos and disabled for agent invocation; canopy's version is generic over `repos[*]` in `canopy.toml` and runs from any context (CLI, MCP, extension).

---

## Behavioral spec

### Three optional bootstrap steps, gated per repo + per invocation

When canopy creates a fresh worktree for a feature (either via `canopy worktree create` or implicitly via `canopy switch` warming a cold feature), each step is **off by default** and runs only when:

1. The relevant config is set in `canopy.toml` for that repo, AND
2. The user passed `--bootstrap` (or set `bootstrap_default = true` in `[workspace]`).

Step 1 — **Env file copy**

Per repo, `env_files = [".env", ".env.local", "apps/web/.env.local"]` lists files (paths relative to repo root) to copy from the main checkout into the new worktree. Subdirectory paths are honored. Missing source files log a `[canopy] env-file missing: …` warning and are skipped — never blocking. Existing destination files aren't overwritten without `--force-bootstrap`.

Step 2 — **Dependency install**

Per repo, `install_cmd = "uv sync"` (or `"pnpm install"`, `"npm ci"`, `"poetry install"`, `"cargo build"`, etc.) runs in the new worktree directory. Stdout/stderr stream to the canopy output channel; exit code surfaces in the structured per-repo result. Failure doesn't roll back the worktree — the worktree is still valid; the user can fix and re-run `canopy worktree bootstrap <feature>` (new subcommand below).

Step 3 — **IDE workspace file**

Workspace-level `[workspace]` config `ide = "vscode"` triggers generation of `<workspace_root>/.canopy/workspaces/<feature>.code-workspace` listing every worktree dir for the feature, plus per-folder settings (e.g., `python.defaultInterpreterPath` pointing at the worktree's `.venv/bin/python`). Layout templated per IDE; v1 supports `vscode` only (`.code-workspace` JSON), with `none` (default) skipping. Future: `jetbrains` (`.idea/`), `cursor` (same as vscode).

### New CLI surface

- `canopy worktree create <feature> --bootstrap` — explicit bootstrap on create.
- `canopy switch <feature> --bootstrap` — bootstrap when warming a cold feature (no-op when the target was already warm).
- `canopy worktree bootstrap <feature>` — re-run all three steps against an existing worktree, idempotent. Useful when env files were updated, deps added, or `canopy.toml` config was extended after the worktree existed.
- `canopy worktree bootstrap <feature> --step env|deps|ide` — run just one step, for the case where deps install is slow and you only need to refresh env.

### Config additions

`canopy.toml`:

```toml
[workspace]
name = "my-product"
ide = "vscode"                     # NEW — "vscode" | "none" (default)
bootstrap_default = false          # NEW — if true, --bootstrap is implicit on create/warm

[[repos]]
name = "api"
path = "./api"
env_files = [".env", ".env.local"]                     # NEW — list of paths relative to repo
install_cmd = "uv sync"                                 # NEW — single shell command, run in worktree dir
ide_settings = { python = ".venv/bin/python" }          # NEW — kv map merged into the IDE workspace's per-folder settings

[[repos]]
name = "ui"
path = "./ui"
env_files = [".env.local", "apps/web/.env.local"]
install_cmd = "pnpm install"
```

All three new fields on `RepoConfig` are optional. Workspaces that don't set them are unaffected.

### Idempotency rules

- Env-file copy: skip if destination exists (warn). With `--force-bootstrap`, overwrite.
- Dep install: always runs; the install command is responsible for its own idempotency (`uv sync`, `pnpm install`, etc. are idempotent in practice).
- IDE workspace file: regenerated each time. The file is fully owned by canopy. Don't hand-edit; put per-folder overrides in `repos[*].ide_settings`.

### Failure model

Per-step structured result so the orchestrator can report cleanly:

```python
{
  "feature": "auth-flow",
  "results": {
    "<repo>": {
      "env": {"status": "ok" | "skipped" | "missing_source", "files_copied": [...]},
      "deps": {"status": "ok" | "failed" | "skipped", "exit_code": int, "duration_ms": int},
    }
  },
  "ide": {"status": "ok" | "skipped" | "no_ide_configured", "path": "..."}
}
```

`canopy worktree bootstrap --json` returns this shape directly. Failure of any step doesn't block the others — they're independent.

---

## Files to touch

### New

- `src/canopy/actions/bootstrap.py` — orchestrator. Public functions: `bootstrap_feature(workspace, feature, force=False, steps=None)`, `bootstrap_repo(workspace, feature, repo, force=False, steps=None)`. Composes the three steps; aggregates the structured result.
- `src/canopy/actions/ide_workspace.py` — pure renderer: given a feature lane + per-repo `ide_settings`, returns the JSON for a `.code-workspace` file. Easy to unit-test as a string-in / dict-out pure function.
- `tests/test_bootstrap.py` — table-driven cases per matrix above (env exists / missing source / install fails / IDE not configured).
- `tests/test_ide_workspace.py` — snapshot test the rendered `.code-workspace` JSON for representative lane shapes.

### Modified

- `src/canopy/workspace/config.py` — add `RepoConfig.env_files: list[str]`, `RepoConfig.install_cmd: str`, `RepoConfig.ide_settings: dict[str, str]`, `WorkspaceConfig.ide: str`, `WorkspaceConfig.bootstrap_default: bool`. Default values keep existing workspaces forward-compatible.
- `src/canopy/actions/evacuate.py` — when promoting a cold feature into a warm worktree, optionally invoke `bootstrap_repo` if `bootstrap_default=True` or the caller passed `--bootstrap`. Wire via a `bootstrap` parameter on `_evacuate_one`.
- `src/canopy/actions/switch.py` — pass-through `bootstrap` flag to evacuate when warming a cold feature.
- `src/canopy/features/coordinator.py` `worktree_create` — accept `bootstrap=True` and call `bootstrap_repo` post-creation.
- `src/canopy/cli/main.py` — add `cmd_worktree_bootstrap`, wire `--bootstrap` flag on `cmd_switch` + `cmd_worktree_create`, register subparsers.
- `src/canopy/mcp/server.py` — register `worktree_bootstrap(feature, force=False, steps=None)` tool.
- `docs/commands.md` — new section.
- `docs/workspace.md` — document the new `canopy.toml` keys.
- `docs/agents.md` — note that the agent should call `worktree_bootstrap` after a cold feature warms (not auto-invoked, agent's choice).
- Both skill files (`~/.claude/skills/using-canopy/SKILL.md` and `src/canopy/agent_setup/skill.md`) — flag bootstrap as an explicit step the agent can take.

---

## Tasks (rough sequence)

### T1 — Config schema

Extend `RepoConfig` and `WorkspaceConfig`. Update `parse_config` to accept and default the new fields. Tests in `test_config.py` covering: legacy toml parses unchanged; new fields parse; missing fields default empty/false.

### T2 — Env-file copy primitive

`actions/bootstrap.py:_copy_env_files(workspace, repo, src_dir, dst_dir, force)`. Iterates `repo.env_files`, copies each (preserving relative path inside the repo), reports per-file status. Pure file-system; tests use temp dirs.

### T3 — Dep install primitive

`actions/bootstrap.py:_run_install(repo, dst_dir, output_channel)`. Wraps `subprocess.Popen` to stream stdout to the output channel, captures exit code + duration. Tests mock subprocess.

### T4 — IDE workspace renderer + writer

`actions/ide_workspace.py` — pure renderer + atomic writer (write to tmp, rename). Snapshot tests on the rendered JSON.

### T5 — `bootstrap_feature` / `bootstrap_repo` orchestrators

Compose the three steps. Per-repo parallelism via the existing `concurrent.futures` pattern. Aggregate into the structured result. Tests cover the matrix.

### T6 — Wire into `evacuate` + `switch` + `worktree_create`

Add the `bootstrap` parameter through the three call sites. Default false (preserves existing behavior). Tests assert: `--bootstrap` triggers the steps; absence of flag leaves the worktree untouched.

### T7 — CLI subparser + MCP tool registration

`canopy worktree bootstrap <feature>`, `--bootstrap` flag on `switch` and `worktree create`, `--step` flag on `worktree bootstrap`. MCP `worktree_bootstrap` tool.

### T8 — Docs + skills

`docs/commands.md`, `docs/workspace.md`, `docs/agents.md`. Both skill files updated with the new tool listed in the preferred-over table.

---

## Edge cases to remember

- **Symlinked env files.** If `repo/.env` is a symlink (some workflows), copy follows the link by default. Document as expected behavior.
- **Multi-app repos.** docsum-ui has `apps/web/.env.local` AND `apps/word-addin/.env.local`. Both listed in `env_files`. Subdirs honored.
- **Install command needs network.** `uv sync` / `pnpm install` may fail offline. Surface stderr in the result; don't retry.
- **IDE workspace conflict.** If the user has an existing hand-written `.code-workspace` at the same path, canopy refuses to overwrite without `--force-bootstrap`. Canopy-managed workspaces live at `.canopy/workspaces/<feature>.code-workspace` — namespaced — but the user might point IDE settings at a different path. Don't overwrite anything outside `.canopy/`.
- **`bootstrap` during `switch` of an active-rotation cycle.** When X evacuates → Y warms, do we bootstrap Y? Yes if Y was cold (warming = first time worktree exists). No if Y was already warm (worktree exists, env files already there). The `bootstrap_repo` function checks worktree state and short-circuits the env step accordingly.
- **Parallel `bootstrap` runs.** Each repo's install command runs in its own subprocess; they're parallel-safe (no shared state). Tests assert thread-safety of the result aggregation.

---

## Out of scope

- **Generating the install command from language inference.** v1 is opt-in via `install_cmd`; we don't infer "this is python ergo `uv sync`". Future helper: `canopy worktree detect-bootstrap <feature>` proposes a config based on what files exist (`pyproject.toml` → `uv sync`, `package.json` → `pnpm install`, etc.).
- **Watching env files in the main checkout for changes.** If the user updates `.env` in main, the warm worktrees don't auto-update. They'd run `canopy worktree bootstrap <feature> --step env --force` to refresh. Auto-watch is a future ergonomic.
- **Alternative IDE formats.** v1 ships `vscode` only. JetBrains `.idea/`, `cursor` (different format from vscode despite the marketing), Helix, etc. — additive plans.
- **Removing env files / deps on `canopy done`.** When a feature is archived, the worktree is removed (existing behavior). Env files inside the worktree go with it. No special cleanup needed.

---

## After this lands

- A new contributor running `canopy worktree create <feature> --bootstrap` gets a ready-to-run dev environment in one command — env files in place, deps installed, IDE workspace open-able.
- The README failure-mode #5 (raw `git worktree add` mess) gets a stronger fix: not just predictable layout, but predictable readiness.
- Canopy absorbs the workflow that was forcing teams to write per-monorepo bash wrappers (like the docsum `manage-worktrees` skill) and reframes it as configurable canopy infrastructure.
- The `using-canopy` skill becomes more recommendation-able to monorepo teams who would otherwise reach for one-off scripts.
