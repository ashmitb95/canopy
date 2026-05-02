---
status: shipped
priority: P1
effort: ~3-4d
depends_on: ["archive/providers-arch.md"]
---

# Issue-provider scaffold (M5)

> **Spec:** [`docs/architecture/providers.md`](../architecture/providers.md). This file is the implementation tracker; the architecture doc is the design.

## Goal

Implement the provider-injection contract from M0. Refactor the existing Linear coupling into the contract, add a GitHub Issues backend, and switch the action layer to resolve providers via `get_issue_provider(workspace)`.

After M5: workspaces opt in via `[issue_provider]` in canopy.toml. Old `linear_*` MCP tools keep working as deprecated aliases.

## Scope (per architecture doc)

- New package `src/canopy/providers/`:
  - `types.py` — `Issue` dataclass + `IssueProvider` protocol (architecture §2)
  - `linear.py` — `LinearProvider` refactored from `integrations/linear.py` (architecture §7)
  - `github_issues.py` — new `GitHubIssuesProvider` (architecture §7)
  - `__init__.py` — registry + `get_issue_provider(workspace)` (architecture §3, §5)
- Config schema: `[issue_provider]` + `[issue_provider.<name>]` in canopy.toml (architecture §4)
  - Add `issue_provider` field to `WorkspaceConfig`
  - Default to Linear when block missing (one-cycle deprecation; warn-once)
- Call-site updates (3 sites):
  - `src/canopy/actions/reads.py:34` (`linear_get_issue`)
  - `src/canopy/features/coordinator.py:335` (`link_linear_issue`)
  - `src/canopy/mcp/server.py:1023` (the `linear_my_issues` MCP tool)
- New MCP tools: `issue_get`, `issue_list_my_issues`. Old `linear_get_issue` / `linear_my_issues` kept as deprecated aliases for one release cycle.
- `integrations/linear.py` → re-export shim from `providers/linear.py` for one cycle (so external code doesn't break).

## Files to touch

**New:**
- `src/canopy/providers/__init__.py`
- `src/canopy/providers/types.py`
- `src/canopy/providers/linear.py`
- `src/canopy/providers/github_issues.py`
- `tests/test_providers_types.py`
- `tests/test_providers_linear.py`
- `tests/test_providers_github_issues.py`
- `tests/test_providers_registry.py`

**Modified:**
- `src/canopy/integrations/linear.py` — shrink to a re-export shim (deprecated)
- `src/canopy/workspace/config.py` — `IssueProviderConfig` dataclass + parse `[issue_provider]` block
- `src/canopy/actions/reads.py` — line 34 call site
- `src/canopy/features/coordinator.py` — line 335 call site
- `src/canopy/mcp/server.py` — `linear_my_issues` tool (line 1023) + add `issue_get` / `issue_list_my_issues` + alias deprecation warnings
- `docs/workspace.md` — document `[issue_provider]` block
- `docs/mcp.md` — new tool list + deprecation notice on old tools

## Implementation order

1. **types.py** — `Issue` dataclass + `IssueProvider` protocol. No deps.
2. **linear.py** — wrap existing logic from `integrations/linear.py` as `LinearProvider` methods. Behavior identical; just re-shaped.
3. **github_issues.py** — new from scratch using existing `_gh` helper from `integrations/github.py:141`.
4. **__init__.py** — registry + `get_issue_provider(workspace)` with per-workspace cache.
5. **workspace/config.py** — schema additions; backward-compat default.
6. **Call-site updates** — `reads.py`, `coordinator.py`, `mcp/server.py:linear_my_issues`.
7. **New MCP tools** — `issue_get`, `issue_list_my_issues`. Existing `linear_*` tools become aliases that log a deprecation notice and call through.
8. **`integrations/linear.py`** — shrink to re-export shim with module-level `DeprecationWarning`.
9. **Tests** — mirror existing pattern (mock-based via `@patch`).
10. **Docs** — workspace.md (config), mcp.md (tools).

## Verification

- All 436 existing tests pass unchanged (call-site updates preserve behavior).
- New tests cover: `Issue` dataclass shape, `LinearProvider.get_issue` (round-trip), `LinearProvider.list_my_issues`, `LinearProvider.format_branch_name`, `GitHubIssuesProvider.get_issue` (mocked `_gh`), `GitHubIssuesProvider.list_my_issues`, registry (`get_issue_provider`) for both backends + unknown-provider error.
- Manual: workspace with `[issue_provider] name = "github_issues"` → `canopy issue #142` resolves via GH backend; workspace without the block → defaults to Linear with a deprecation warning logged once.

## Out of scope

Per architecture §1 + §8:
- Per-repo provider override (workspace-level only in v1)
- Third-party provider entry points (bundled-only in v1)
- `update_issue_state` lifecycle automation (contract reserves the slot; first impls raise NotImplementedError)
- Bot-author / CI / code-review / IDE / pre-commit provider-ifying (named in arch §8 with < 5% effort cap; not v1)

## Sequencing notes

- M0 (architecture doc) shipped — this is the implementation.
- Doesn't depend on M1 (canopy doctor); can land in parallel.
- M3 (bot-tracking) and M4 (historian) read `[review_bots]` from N3 (augments) — independent of provider injection. M5 won't conflict with them either.
