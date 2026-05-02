---
status: queued
priority: P1
effort: ~2-3d
depends_on: ["doctor.md"]
---

# Augment skill — per-workspace customization

## Why

Canopy operations that vary by team/codebase — which preflight command runs, which test command runs, which authors count as bots — are currently hardcoded. `pre-commit run --all-files` is the only preflight; `author_type == "Bot"` substring is the only bot detector; there's no `canopy test` command yet.

Real workspaces want per-workspace customization. Examples:
- "This monorepo uses `ruff format && pyright` for preflight, not `pre-commit run`."
- "Track CodeRabbit + Korbit as bot reviewers; ignore Copilot's nits."
- "The frontend repo's tests are `pnpm test:unit`; the backend is `pytest tests/fast`."

This plan adds a `[augments]` workspace-level config table plus per-repo overrides, a new `augment-canopy` skill that teaches the agent how to mutate the config, and the wiring needed for the first consumer (preflight).

## Goal

Per-workspace customization for canopy operations, stored in `canopy.toml` and set via the `augment-canopy` skill. v1 covers preflight; review_bots and test_cmd are declared in the schema and consumed where ready (review_bots is consumed by N2 bot-comment tracking).

## Non-goals

- Custom commit-message templates, branch-naming conventions, etc. Future augments; not v1.
- Per-feature augments (different preflight for different features in same workspace). Workspace + per-repo is enough complexity for v1.
- Reachable via `canopy config get/set augments.preflight_cmd` — `cmd_config` is flat-only; nested-key support is a separate refactor. The augment-canopy skill writes TOML directly in v1.
- Augment validation (catching typos like `preflight_cmmd` silently being ignored by the lenient parser). Add `canopy doctor --check-augments` later, or fold into doctor.

## Schema

Two-tier: workspace defaults + per-repo override.

```toml
[augments]
preflight_cmd = "make check"             # workspace default for all repos
test_cmd = "pytest"
review_bots = ["coderabbit", "korbit"]   # case-insensitive author substring match (consumed by N2)

[[repos]]
name = "api"
path = "./api"
augments = { preflight_cmd = "uv run pytest tests/fast" }   # per-repo override
```

**Resolution helper** (new module):

```python
# src/canopy/actions/augments.py

def repo_augments(workspace: WorkspaceConfig, repo_name: str) -> dict[str, Any]:
    """Merge workspace [augments] defaults with per-repo augments override.
    Per-repo wins on key collision."""
    workspace_augments = workspace.augments or {}
    repo_config = next((r for r in workspace.repos if r.name == repo_name), None)
    repo_augments = (repo_config.augments if repo_config else {}) or {}
    return {**workspace_augments, **repo_augments}

def bot_authors(workspace: WorkspaceConfig) -> list[str]:
    """Return the configured list of bot-author substrings (lowercased)."""
    augments = workspace.augments or {}
    return [s.lower() for s in augments.get("review_bots", [])]
```

The `cmd_config` CLI is flat-only and the augment-canopy skill (separate concern) handles config mutation by writing TOML directly. Defer `canopy config augments.preflight_cmd "..."` until augments stabilize.

## New skill: `augment-canopy`

Lives at `src/canopy/agent_setup/skills/augment-canopy/SKILL.md`. Loaded only when the user is actively customizing — the existing `using-canopy` skill covers normal operations.

The skill teaches the agent:
- **When to suggest customization.** User says "use X for preflight", "track these specific bots", "this repo uses Y for tests" — agent recognizes the pattern and offers to update canopy.toml.
- **The TOML schema.** Workspace `[augments]` vs per-repo `[[repos]] augments = {...}`. Per-repo wins on collision.
- **How to mutate canopy.toml safely.** Read → parse with `tomli`/`tomllib` → modify → atomic write (`os.rename` from a temp file in the same directory).
- **Augment changes are picked up on next operation.** No canopy restart required; each operation re-reads canopy.toml.

The skill includes a worked example: user says "this workspace uses ruff for preflight" → agent reads canopy.toml → adds `preflight_cmd = "ruff check ."` to `[augments]` → atomic write → confirms with the user.

## Wiring change (v1 consumer: preflight)

`src/canopy/integrations/precommit.py`:

```python
def run_precommit(repo_path: Path, repo_config: RepoConfig | None = None) -> dict:
    """Run the configured preflight command for this repo, falling back to auto-detection."""
    augments = repo_augments(workspace, repo_config.name) if repo_config else {}
    if "preflight_cmd" in augments:
        return _run_custom_preflight(repo_path, augments["preflight_cmd"])
    # existing auto-detection: detect_precommit() → _run_framework() or _run_git_hook()
    ...
```

Three call sites pass `repo_config`:
- `src/canopy/features/coordinator.py:1035` (review_prep path)
- `src/canopy/mcp/server.py:563` (preflight MCP tool)
- `src/canopy/cli/main.py:1126` (cmd_preflight)

When `repo_config.augments.preflight_cmd` is set, the override runs; otherwise existing auto-detection (pre-commit framework or git hook) applies.

## Skill packaging refactor

The existing skill installer is single-skill. Generalize to support multiple skills:

```
src/canopy/agent_setup/
├── __init__.py
└── skills/
    ├── using-canopy/SKILL.md       # existing, moved from agent_setup/skill.md
    └── augment-canopy/SKILL.md     # new in this plan
```

```python
def install_skill(name: str = "using-canopy", *, reinstall: bool = False) -> dict:
    src = _SKILLS_DIR / name / "SKILL.md"
    dst = _USER_SKILLS_DIR / name / "SKILL.md"
    # ... existing idempotency logic, generalized over name
```

```python
def setup_agent(workspace_root, *, skills: tuple[str, ...] = ("using-canopy",), do_mcp=True, reinstall=False) -> dict:
    ...
```

Doctor's diagnostic categories iterate the same skill list to detect missing/stale skills.

## Files to touch

- `src/canopy/workspace/config.py` — extend `WorkspaceConfig` with `augments: dict[str, Any]`, extend `RepoConfig` with `augments: dict[str, str]`, update `_parse_config()` to populate both
- **New:** `src/canopy/actions/augments.py` — `repo_augments()` resolver, `bot_authors()` helper
- `src/canopy/integrations/precommit.py` — `run_precommit` signature change to accept optional `repo_config`
- `src/canopy/features/coordinator.py`, `src/canopy/mcp/server.py`, `src/canopy/cli/main.py` — three call-site updates
- `src/canopy/agent_setup/__init__.py` — skill packaging refactor; `install_skill` + `setup_agent` generalization
- **Move:** `src/canopy/agent_setup/skill.md` → `src/canopy/agent_setup/skills/using-canopy/SKILL.md`
- **New:** `src/canopy/agent_setup/skills/augment-canopy/SKILL.md` (~3-4 KB content, includes worked example of "user says X → agent edits canopy.toml")
- `tests/test_augments.py` (new), `tests/test_config.py` (extended), `tests/test_precommit.py` (extended)
- `docs/workspace.md` — document `[augments]` block + per-repo override
- `docs/agents.md` — reference the augment skill

## Implementation order

1. Extend `RepoConfig` + `WorkspaceConfig` dataclasses + parser. Tests pass with empty defaults (backward-compatible).
2. New `repo_augments()` resolver in `actions/augments.py`. Pure function; unit-tested.
3. Extend `run_precommit()` signature with optional `repo_config`. Update three call sites. Existing tests pass with default `None` (preserves auto-detection behavior).
4. Reorganize skill packaging. Update `cmd_init` and `cmd_setup_agent` callers.
5. Write `augment-canopy/SKILL.md`.
6. Add `canopy setup-agent --skill augment-canopy` flag for opt-in install.

## Verification

- Unit: resolver merges workspace + per-repo correctly; per-repo wins on collision; missing keys return `None`/empty.
- Unit: `run_precommit` with custom `preflight_cmd` runs the override; with `None`, auto-detect still works.
- Integration: workspace with `augments.preflight_cmd = "echo ok && exit 0"` → `canopy preflight` returns success.
- Manual: agent reads "this workspace uses ruff for preflight" from a user message → invokes `augment-canopy` skill instructions → canopy.toml updated → `canopy preflight` runs `ruff check .`.

## Edge cases

- **Symlinked canopy.toml**: read via `Path.resolve()`, write to the resolved path's directory.
- **Concurrent agent edits**: agents may run in parallel and both try to mutate canopy.toml. Atomic-write via `os.rename` from a temp file in the same directory minimizes race window. If the file changes between read and write, retry once; on second failure, return `BlockerError(code='canopy_toml_concurrent_write')`.
- **Invalid command in `preflight_cmd`**: surfaces as a non-zero exit code from `_run_custom_preflight`. Captured in the result dict; doesn't crash canopy.
- **Old canopy reading new schema**: lenient parser silently ignores unknown keys. Old canopy versions with new canopy.toml work unchanged (just don't honor the augments).

## Effort

~2-3 days. Most of the work is the schema additions + resolver + three call-site updates + the new skill content.

## After this lands

- N2 (bot-comment tracking) reads `bot_authors(workspace)` from this resolver.
- The `using-canopy` skill picks up minor updates to teach the agent to *suggest* the augment-canopy skill at the right moments.
- Foundation for future augments (commit message templates, branch-naming conventions, etc.) — same `[augments]` table grows.
- Provider-injection pattern (architecture doc, providers-arch.md) is conceptually similar; augments + providers form canopy's two-pronged customization story (augments = behavioral overrides, providers = swappable integrations).
