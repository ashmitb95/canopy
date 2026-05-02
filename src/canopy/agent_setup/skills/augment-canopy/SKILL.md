---
name: augment-canopy
description: Use when the user wants to customize how canopy operations behave for this workspace — overriding the preflight command, listing which review-comment authors count as bots, choosing a custom test command, or otherwise tuning canopy.toml's [augments] block. Lets the agent edit canopy.toml directly and confirm the new behavior takes effect on the next operation.
---

# augment-canopy

Per-workspace customization for canopy operations that vary by team or codebase. Lives in `canopy.toml` under an `[augments]` block (workspace defaults) plus optional per-repo overrides on `[[repos]]` entries.

## When to invoke

Listen for cues like:

- *"Use ruff for preflight here, not pre-commit."*
- *"Track CodeRabbit and Korbit comments; ignore Copilot."*
- *"This workspace runs `make check` before commits."*
- *"For the api repo specifically, run `uv run pytest tests/fast` as preflight."*
- *"Make `canopy preflight` run X."*

These are all augment edits — read canopy.toml, mutate the right block, atomic-write back, confirm with the user.

Do **not** invoke for:

- Adding/removing repos (use `canopy init` or edit `[[repos]]` blocks normally — that's structural config, not behavioral augments).
- Changing which issue tracker the workspace uses (that's `[issue_provider]`, a separate concern with its own provider abstraction).
- Per-feature overrides (not supported in v1 — augments are workspace + per-repo only).

## Schema

Workspace defaults under `[augments]`; per-repo overrides on each `[[repos]]` entry. **Per-repo wins on key collision.**

```toml
[augments]
preflight_cmd = "make check"             # workspace default for all repos
test_cmd = "pytest"                      # consumed by future `canopy test`
review_bots = ["coderabbit", "korbit"]   # case-insensitive author substring (M3 bot-tracking)

[[repos]]
name = "api"
path = "./api"
augments = { preflight_cmd = "uv run pytest tests/fast" }   # api-only override
```

### Recognized keys (v1)

| Key | Type | Consumed by | Notes |
|---|---|---|---|
| `preflight_cmd` | string | `canopy preflight` (and `review_prep` path inside `coordinator.py`) | Runs via `sh -c` so pipes / `&&` chains work |
| `test_cmd` | string | future `canopy test` (not v1) | Schema-reserved; safe to set |
| `review_bots` | list[string] | M3 bot-comment tracking (when shipped) | Workspace-level only; per-repo overrides ignored for this key |

Unknown keys are silently preserved by the parser — future augments don't require schema migration.

## How to mutate canopy.toml safely

The augment block is **not** reachable through `canopy config get/set` in v1 (that command is flat-only). Edit the TOML file directly. Use this recipe:

1. **Resolve the path.** The workspace root is the directory containing `canopy.toml`. If the user is in a feature worktree, walk up to find it. The MCP tool `mcp__canopy__workspace_status` returns `workspace_root` if you need it.
2. **Read + parse.** Use `tomllib` (Python ≥3.11) or `tomli`. Preserve unknown keys.
3. **Mutate the right block.**
   - Workspace default: `data.setdefault("augments", {})[key] = value`
   - Per-repo override: find the matching entry in `data["repos"]` by `name`, then `entry.setdefault("augments", {})[key] = value`
4. **Atomic write.** Write to a temp file in the same directory, then `os.replace(tmp, canopy_toml)`. This avoids partial writes if the process is interrupted.
5. **Confirm with the user.** Echo the change back: *"Set `augments.preflight_cmd = 'ruff check .'` in canopy.toml. The next `canopy preflight` run will use it."*

No canopy restart needed — every operation re-reads canopy.toml. Changes take effect on the next call.

## Worked example

User: *"Set up this workspace to run `ruff check . && pyright` before every commit, and to track CodeRabbit + Korbit as the bot reviewers I care about."*

Agent should:

1. Find `canopy.toml` (current dir or via `workspace_status`).
2. Read + parse it.
3. Add or update the `[augments]` block:
   ```python
   data.setdefault("augments", {})
   data["augments"]["preflight_cmd"] = "ruff check . && pyright"
   data["augments"]["review_bots"] = ["coderabbit", "korbit"]
   ```
4. Atomic write back.
5. Reply:
   > Updated canopy.toml:
   > - `augments.preflight_cmd = "ruff check . && pyright"`
   > - `augments.review_bots = ["coderabbit", "korbit"]`
   >
   > The next `canopy preflight` will run the new command. Bot-comment tracking will pick up the `review_bots` list once M3 ships.

## Per-repo override example

User: *"For the api repo only, preflight should be `uv run pytest tests/fast` — keep the workspace default for everything else."*

```python
api_entry = next(r for r in data["repos"] if r["name"] == "api")
api_entry.setdefault("augments", {})
api_entry["augments"]["preflight_cmd"] = "uv run pytest tests/fast"
```

Atomic write, confirm:

> Set per-repo augment for `api`: `preflight_cmd = "uv run pytest tests/fast"`. Other repos still use the workspace default (`make check`).

## Edge cases

- **No `[augments]` block yet.** Create it. The parser handles a missing block as `{}`.
- **Concurrent edits.** Two agents writing simultaneously can clobber each other; the atomic-write minimizes the race window. If you read-then-write and the file mtime changed in between, re-read and retry once. On second failure, surface a `BlockerError`.
- **Symlinked canopy.toml.** Resolve via `Path.resolve()`; write to the resolved directory.
- **Invalid command in `preflight_cmd`.** Surfaces as a non-zero exit code at run time. Doesn't crash canopy. The user can fix by re-invoking this skill.

## Don't

- Don't add validation logic here — the parser is intentionally lenient. Validation (typo detection, unknown-key warnings) lives in `canopy doctor` (deferred).
- Don't introduce nested-key syntax via `canopy config augments.preflight_cmd` — that's a future refactor of `cmd_config`. v1 writes TOML directly.
- Don't alter `[issue_provider]` or `[[repos]]` structural fields from this skill — those are different concerns.
