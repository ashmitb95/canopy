# Canopy — Execution Roadmap (2026-05-02)

> **Live tracker:** [INDEX.md](INDEX.md). This document is the design/sequencing rationale; INDEX.md is the rolled-up status dashboard. Each plan's frontmatter is the per-plan source of truth.

## Status snapshot (2026-05-02)

Shipped from this roadmap so far:

- ✅ **M0 — Architecture: provider injection** — [archive/providers-arch.md](archive/providers-arch.md), delivered as [`docs/architecture/providers.md`](../architecture/providers.md)
- ✅ **M1 — `canopy doctor`** — [archive/doctor.md](archive/doctor.md) — 16 diagnostic categories, version handshake (PR #8)
- ✅ **M5 — Issue-provider scaffold** — [archive/issue-providers.md](archive/issue-providers.md) — Linear refactored into the contract; GitHub Issues backend; `issue_get` / `issue_list_my_issues` MCP tools (PR #9)

Sequencing took a divergence from §4: M5 (issue-provider scaffold) shipped in parallel with M1 (doctor) once both could be worked independently. The original "doctor → augments → bot-tracking → historian → first scaffold" chain still holds for M2–M4; M5 just landed early because it had no real dependency on M2–M4.

Active queue (M2 → M4 → M6–M12) is the same as before; INDEX.md has the full board.

---

## Context

This document is the canonical source-of-truth for canopy's pending work. It supersedes the prior tracker at `~/.claude/plans/2026-04-26-canopy-skipped-phases.md`, consolidating:

1. **Existing plans** I wrote in earlier sessions (eight plan files in `~/.claude/plans/canopy-*.md`).
2. **New asks** from a real-world dogfood transcript (`~/projects/canopy/canopy-improvement-research.md`) that surfaced setup-propagation failures, bot-comment-tracking gaps, and per-workspace customization needs.
3. **A scope refinement** for the provider-injection scaffolding pattern: scoped to issue providers (per [issue #5](https://github.com/ashmitb95/canopy/issues/5)), not a sweeping refactor.

What changed in this session:

- **N1 (`canopy upgrade`) is absorbed into the existing doctor plan** — they're orthogonal in scope but identical in shape (Issue / repair pattern). One unified `canopy doctor` command. Validated by reasoning through the Plan agent's output + the user's instinct that doctor is the more robust design.
- **A provider-injection architecture document** is now a planned artifact, separate from any sub-plan. Lives at `docs/architecture/providers.md`. Scoped to issue providers in v1; future candidate use cases (bot-author / CI / code-review / IDE workspace formats) are *named but not specified* — they only adopt the pattern if it drops in seamlessly.
- **Three new sub-plans** added to the queue: augment skill (N3), bot-comment tracking (N2), and historian (cross-session feature memory). All file-by-file specced below.
- **Sequencing locked**: arch doc → doctor → augments (N3) → bot-tracking (N2) → historian → first issue-provider scaffold. Other existing plans (worktree-bootstrap, sidebar-single-tree, ship, draft_replies, ci-status, action-drawer, conflicts) slot in afterward; their order remains as in their individual plan files.

---

## Section 0 — Full pending inventory

Every plan currently in `~/.claude/plans/`:

| # | File | Scope | Status | Priority | Depends on |
|---|------|-------|--------|----------|------------|
| 1 | `2026-04-26-canopy-skipped-phases.md` | Meta tracker for skipped Wave 2.3/2.4/4 backends | superseded by this doc | n/a | n/a |
| 2 | `2026-04-26-canopy-wave-2-3-commit-push.md` | `commit` + `push` MCP tools | ✅ shipped | n/a | n/a |
| 3 | `2026-04-26-canopy-wave-2-4-ship.md` | `ship` MCP tool (commit + push + open PRs) | pending | medium | wave-2-3 (shipped) |
| 4 | `2026-04-26-canopy-wave-4-draft-replies.md` | `draft_replies` MCP tool | pending | medium | review classifier (shipped) |
| 5 | `2026-04-26-canopy-sidebar-single-tree.md` | Extension sidebar collapse to single tree | pending | low (UI only, independent) | none |
| 6 | `2026-04-26-canopy-action-drawer.md` | Extension dashboard right-rail rebuild, ~16 wired actions | pending | low (depends on backends) | wave-2-4 + wave-4 |
| 7 | `2026-04-28-canopy-doctor.md` | State-file integrity check + repair | ✅ shipped (M1) | **HIGH** | none — earliest foundation |
| 8 | `2026-04-28-canopy-ci-status.md` | CI status in `feature_state` + `awaiting_ci` state + `pr_checks` MCP tool | pending | medium | none |
| 9 | `2026-04-28-canopy-cross-feature-conflicts.md` | `canopy conflicts` cross-feature file-overlap | pending | LOW (nice-to-have) | none |
| 10 | `2026-04-28-canopy-worktree-bootstrap.md` | Env-file copy + dep install + IDE workspace gen on worktree create | pending | medium | none |
| 11 | **THIS FILE** | Roadmap + 3 new sub-plans + arch-doc spec | drafting | HIGH | n/a |

The four new artifacts embedded in this file (no separate plan files written for them — they live here so the roadmap stays consolidated):

- ✅ **Architecture doc — provider injection (issue providers scoped)** → shipped as [`docs/architecture/providers.md`](../architecture/providers.md) (M0)
- **Augment skill (M2)** → per-workspace customization (preflight_cmd, test_cmd, review_bots) + new `augment-canopy` skill
- **Bot-comment tracking (M3)** → distinguish bot vs human review threads, `commit --address`, `awaiting_bot_resolution` state
- **Historian (cross-session feature memory) (M4)** → `.canopy/memory/<feature>.md` persistent log of decisions, events, comment activity, PR context. Auto-read on `canopy switch`. Eliminates the agent's "re-derive everything every session" tax.

A fifth implementation plan was extracted later for **M5 — issue-provider scaffold** ([archive/issue-providers.md](archive/issue-providers.md), shipped) — implements the M0 contract.

---

## Section 1 — Cross-cutting decisions

These apply across multiple sub-plans. Documented here once; sub-plan sections reference by anchor.

### 1.1 — Doctor absorbs `canopy upgrade` categories

The existing doctor plan covers workspace state-file integrity (heads.json stale, orphan worktrees, missing hooks, etc.). The proposed-but-now-merged "canopy upgrade" idea covers machine-level artifact staleness (CLI version, MCP version, vsix cleanup, missing skill, missing `.mcp.json` entry, version handshake).

**Decision:** these are the same kind of work — diagnose, classify, repair. One `canopy doctor` command, growing taxonomy. Severity tiers (`info` / `warn` / `error`) handle the urgency distinction; `--fix=<category>` opts into specific repairs; reload-required repairs return `BlockerError(code='reload_required', fix_action='reload window')` rather than silent UX bumps.

The doctor plan ([`2026-04-28-canopy-doctor.md`](~/.claude/plans/2026-04-28-canopy-doctor.md)) is extended with six new categories — see Section 3 below for the additions.

### 1.2 — Architecture doc for provider injection (issue providers scoped)

A separate engineering reference at `docs/architecture/providers.md`. Defines the contract / discovery / configuration / DI wiring for **issue providers** specifically (Linear, GitHub Issues, JIRA shape).

Future candidate use cases (bot-author detection, CI providers, code-review platforms, IDE workspace formats) are *named in the doc but not specified*. They adopt the pattern only if it drops in seamlessly during implementation; otherwise their current handling stays.

**Effort cap on the non-issue-provider candidates: < 5% of total architecture-doc effort.**

### 1.3 — State machine: `awaiting_bot_resolution` placement (N2)

Insert between `awaiting_review` and `approved`. Do **not** gate `approved` — human approval is the merge gate; bot nits are a side-channel.

```
drifted > needs_work (human) > in_progress > ready_to_commit
       > ready_to_push > awaiting_bot_resolution > awaiting_review
       > approved > no_prs
```

Trigger: no human `CHANGES_REQUESTED`, no actionable human threads, ≥1 actionable bot thread, PR not yet `APPROVED`. If approved + bot threads still open: state stays `approved`; "address bot comments" is a *secondary* CTA in `next_actions`.

`_per_repo_facts` splits `actionable_count` → `actionable_human_count` + `actionable_bot_count` (using the existing `author_type` field at `integrations/github.py:537`).

### 1.4 — Augment config schema (N3)

Two-tier: workspace defaults + per-repo override.

```toml
[augments]
preflight_cmd = "make check"
test_cmd = "pytest"
review_bots = ["coderabbit", "korbit"]   # case-insensitive author substring match

[[repos]]
name = "api"
augments = { preflight_cmd = "uv run pytest tests/fast" }
```

Resolution helper (new — `src/canopy/actions/augments.py`):

```python
def repo_augments(workspace: WorkspaceConfig, repo_name: str) -> dict[str, Any]:
    """Merge workspace [augments] defaults with per-repo override. Per-repo wins."""
```

Three call sites consume this in v1: `precommit.py:run_precommit` (preflight_cmd), `actions/feature_state.py:_per_repo_facts` (review_bots filter), and a future `canopy test` command (test_cmd, not v1).

The augment config is **not reachable via `canopy config` CLI** in v1 — `cmd_config` is flat-only. The `augment-canopy` skill mutates canopy.toml directly via parse → modify → write atomic.

### 1.5 — Skill packaging: one installer, multiple skills

Reorganize bundled skills:

```
src/canopy/agent_setup/
├── __init__.py
└── skills/
    ├── using-canopy/SKILL.md       # existing, moved from agent_setup/skill.md
    └── augment-canopy/SKILL.md     # new in N3
```

Generalize the installer:

```python
def install_skill(name: str = "using-canopy", *, reinstall: bool = False) -> dict:
    src = _SKILLS_DIR / name / "SKILL.md"
    dst = _USER_SKILLS_DIR / name / "SKILL.md"
    # ...existing idempotency logic
```

`setup_agent` accepts a list:

```python
def setup_agent(workspace_root, *, skills: tuple[str, ...] = ("using-canopy",), do_mcp=True, reinstall=False) -> dict:
    ...
```

Doctor's diagnostic categories iterate the same list to detect missing/stale skills.

### 1.6 — Version handshake (doctor expansion)

Single source of truth: `src/canopy/__init__.py:__version__`. Three reporting layers:

- **CLI:** `canopy --version` (argparse `version` action)
- **MCP server:** new `version()` MCP tool returning `{cli_version, mcp_version, schema_version}`. Schema version starts at `"1"`, bumps on canopy.toml schema changes (independent of package version).
- **Extension:** at MCP startup, calls `version()` once. Logs warning on minor mismatch; refuses activation on major mismatch with toast offering `canopy doctor --fix`.

Doctor reads each binary's `--version` output to determine staleness.

### 1.7 — Sequencing rationale

```
arch doc (issue providers) ✅      ← design reference; doesn't ship code        [M0]
   ↓
doctor (extended w/ install-staleness categories + version handshake) ✅       [M1]
   ↓                              ↘
M2 augment skill                    First issue-provider scaffold ✅            [M5 — landed in parallel with M1]
   ↓                                  ← references the arch doc; refactors Linear into the contract; adds GitHub Issues
M3 bot-comment tracking            ← uses review_bots from M2, awaiting_bot_resolution state
   ↓
M4 Historian                       ← consumes M3's bot_resolutions + classifier output; cross-session memory
   ↓
[existing plans pick up: M6 worktree-bootstrap, M10 ci-status, M8 ship, M9 draft_replies, etc.]
```

Reasoning:
- **Arch doc first.** The provider-injection requirement is real and concrete; design before code prevents Linear-shaped APIs leaking into the contract.
- **Doctor second.** Foundation for portability across machines (the dogfood transcript's load-bearing failure). The version handshake bits are preconditions for later upgrade detection.
- **N3 before N2.** N2's bot classifier reads the `review_bots` list from N3's augments. Without N3, N2 falls back to hardcoded `author_type == "Bot"` — workable but less powerful.
- **Historian after N2.** Historian's "comments resolved" log consumes N2's `bot_resolutions.json` + the temporal classifier's `likely_resolved` output. Without N2, historian would have to reimplement structured comment-resolution state. With N2 first, historian is a thin narrative layer on top.
- **Issue-provider scaffold last** in this group. The arch doc + doctor + augment + historian foundations make the implementation cleaner.

### 1.8 — Historian capture mechanism (Historian)

Hybrid: explicit MCP tool calls (primary) + Stop-hook tail-parse (backup).

- **Primary: explicit tool calls.** Skill teaches the agent to call `mcp__canopy__historian_decide(feature, decisions=[...])` after committing to an approach (after a commit, after a pivot, on pause). Reliable; structured input validated by the MCP protocol.
- **Backup: Stop-hook tail-parse.** Skill teaches: at end of turn where you decided something but didn't call the tool, emit `<historian-decisions>[{title, rationale}, ...]</historian-decisions>` in the response. Stop hook scans the last assistant message; parses; writes any decisions not already captured (deduped by title).
- **Rejected: extra-prompt round-trip.** A hook that fires after commit and asks the agent "any decisions worth recording?" wastes an LLM turn given the tool-call primitive exists.

The hybrid handles two failure modes: (a) agent forgets to call the tool but mentions the decision in their response (tail-parse rescue), (b) agent does both (deduped). Format-only would have ~5–10% silent gaps in long sessions; tool-only would miss free-text decisions that didn't trigger an explicit call. The hybrid pushes silent-gap rate to near zero.

---

## Section 2 — New artifacts this roadmap introduces

Each of the three new items below is specced in this file (no separate plan file). Each can be split out into its own plan file when execution starts, if a fresh-context session prefers it.

### 2.1 — Architecture doc: `docs/architecture/providers.md`

**Goal:** define the provider-injection pattern for issue providers, document the contract/discovery/config/wiring, and name (without specifying) the future candidate use cases.

**Why first:** the GitHub-issues requirement ([issue #5](https://github.com/ashmitb95/canopy/issues/5)) is concrete. We need the design pinned before any code lands so Linear-shaped assumptions don't bleed into the contract.

**Doc structure:**

1. **Motivation** — why provider injection (issue #5, future-proofing, multi-provider workspaces).
2. **The contract** — Python protocol / abstract base for an issue provider:
   - `get_issue(alias: str) -> Issue` — returns canonical `Issue` shape (id, identifier, title, description, state, url, assignee, labels, priority)
   - `list_my_issues(limit: int = 50) -> list[Issue]`
   - `format_branch_name(issue_id: str, title: str | None, custom: str | None) -> str` — provider-specific slug rules
   - Optional: `update_issue_state(alias: str, new_state: str) -> None` for lifecycle automation (deferred to a future plan; contract reserves the slot).
3. **Discovery** — how canopy finds providers:
   - **v1: bundled.** Canopy ships `canopy.providers.linear` and `canopy.providers.github_issues` as built-in modules.
   - **Future: entry points.** Third-party providers register via `pyproject.toml` entry points (`canopy.providers` group). Not v1.
4. **Configuration** — how the user/workspace picks a provider:
   - canopy.toml top-level `[issue_provider]` block: `name = "linear"` or `"github_issues"`, plus provider-specific config (e.g., `linear.api_key_env = "LINEAR_API_KEY"`, `github_issues.repo = "owner/repo"`).
   - Per-repo override possible via `[[repos]] issue_provider = {...}` for the rare case a single workspace has repos using different trackers (deferred — workspace-level only in v1).
5. **DI wiring** — how the action layer obtains the provider instance:
   - New module `src/canopy/providers/__init__.py` exposes `get_issue_provider(workspace) -> IssueProvider`.
   - Cached per-workspace; constructed lazily on first access.
   - Action code calls `get_issue_provider(ws).get_issue(alias)` instead of `linear.get_issue(workspace.config.root, alias)`.
6. **Backward compatibility** — existing code paths:
   - Current `integrations/linear.py` becomes the Linear backend implementing the contract.
   - Current `integrations/github.py` PR/branch logic stays separate (review-platform concern, not issue-provider concern).
   - Existing `mcp__canopy__linear_get_issue` MCP tool keeps working (deprecated alias for `mcp__canopy__issue_get` once the new tool ships).
7. **Examples** — fully worked Linear backend + skeleton GitHub Issues backend.
8. **Future candidates (not v1)** — one paragraph per:
   - Bot-author detection (currently hardcoded `author_type == "Bot"` substring; *no plan to make a provider unless seamless*)
   - CI providers (deferred to ci-status plan; *no plan to make a provider unless seamless*)
   - Code-review platforms (gh fallback works fine today; *no plan to make a provider unless seamless*)
   - IDE workspace formats (bootstrap plan deferred; *no plan to make a provider unless seamless*)
   - Pre-commit frameworks (auto-detection works fine today; *no plan to make a provider unless seamless*)

**Deliverable:** the doc itself. Code lands in subsequent plans.

**Verification:** the doc is reviewable as a design artifact. Once a future plan implements an issue-provider backend, that plan's PR description references the section it implements.

### 2.2 — Doctor extension: install-staleness categories + version handshake

**Goal:** extend the existing doctor plan with six new diagnostic categories and the version handshake. Keeps doctor as the single recovery primitive.

**New diagnostic categories** (additions to the doctor plan's matrix):

| Code | Severity | Detection | Repair |
|---|---|---|---|
| `cli_stale` | warn | `canopy --version` < `__version__` | re-pip-install or re-pipx-install (detected from install method) |
| `mcp_stale` | error | MCP `version()` returns < `__version__`, or tool missing entirely | reinstall venv via existing `runInstallBackend` pattern |
| `mcp_missing_in_workspace` | error | `.mcp.json` lacks canopy entry, or `CANOPY_ROOT` mismatched | `install_mcp(workspace_root, reinstall=True)` |
| `skill_missing` | warn | no SKILL.md at `~/.claude/skills/<name>/` for any skill in the configured list | `install_skill(name)` for each missing |
| `skill_stale` | warn | byte-compare against bundled source returns mismatch | `install_skill(name, reinstall=True)` |
| `vsix_duplicates` | info | multiple `singularityinc.canopy-*` dirs in `~/.vscode/extensions/` | report; `--clean-vsix` flag removes non-current versions |

**Version handshake** (per cross-cutting 1.6):
- New constant `__version__` in `src/canopy/__init__.py` (sourced from `pyproject.toml`).
- New CLI: `canopy --version`.
- New MCP tool: `version()` returns `{cli_version, mcp_version, schema_version}`.
- Extension calls `version()` at MCP startup; mismatch handling per 1.6.

**Files to touch (additions to doctor plan):**

- `src/canopy/__init__.py` — `__version__` constant
- `src/canopy/cli/main.py` — `--version` argparse action; `cmd_doctor` extended to call install-staleness checks
- `src/canopy/mcp/server.py` — new `version()` tool
- `src/canopy/actions/doctor.py` — six new check functions, six new repair functions
- `vscode-extension/src/canopyClient.ts` — version handshake on MCP startup
- `tests/test_doctor.py` — extend with install-staleness fixtures

**Deliverable:** doctor with 15 diagnostic codes (9 existing + 6 new), single command, severity-tiered output.

### 2.3 — N3 augment skill: per-workspace customization

(Detailed spec — this becomes the source-of-truth when execution starts; can be extracted to its own plan file then if preferred.)

**Goal:** per-workspace customization for canopy operations that vary by team/codebase: which preflight command runs, which test command runs, which authors count as bots. Stored in canopy.toml. Set via the `augment-canopy` skill.

**Schema additions** (per cross-cutting 1.4):
- `[augments]` workspace-level table with `preflight_cmd`, `test_cmd`, `review_bots`
- `[[repos]] augments = {...}` per-repo override
- `repo_augments(workspace, repo_name)` resolver in new `src/canopy/actions/augments.py`

**New skill:** `src/canopy/agent_setup/skills/augment-canopy/SKILL.md`. Loaded only when user is actively customizing. Teaches the agent:
- When to suggest customization ("user says X uses Y for Z")
- The TOML schema (workspace defaults vs per-repo overrides)
- How to mutate canopy.toml safely (read → tomli/tomllib parse → modify → atomic write)
- Augment changes are picked up on next operation (no canopy restart required)

**Wiring change:** `integrations/precommit.py:run_precommit(repo_path, repo_config: RepoConfig | None = None)`. Three call sites pass `repo_config`:
- `features/coordinator.py:1035` (review_prep path)
- `mcp/server.py:563` (preflight MCP tool)
- `cli/main.py:1126` (cmd_preflight)

When `repo_config.augments.preflight_cmd` is set, the override runs; otherwise existing auto-detection (pre-commit framework or git hook) applies.

**Skill packaging refactor** (per cross-cutting 1.5):
- Move `src/canopy/agent_setup/skill.md` → `src/canopy/agent_setup/skills/using-canopy/SKILL.md`
- Generalize `install_skill(name="using-canopy", *, reinstall=False)`
- `setup_agent(workspace_root, *, skills=("using-canopy",), do_mcp=True, reinstall=False)`
- Doctor (2.2) iterates the configured skill list

**Files to touch:**

- `src/canopy/workspace/config.py` — `WorkspaceConfig.augments: dict[str, Any]`, `RepoConfig.augments: dict[str, str]`, parser updates
- **New:** `src/canopy/actions/augments.py` — `repo_augments()` resolver, `bot_authors()` helper
- `src/canopy/integrations/precommit.py` — `run_precommit` signature change
- `src/canopy/features/coordinator.py`, `src/canopy/mcp/server.py`, `src/canopy/cli/main.py` — three call-site updates
- `src/canopy/agent_setup/__init__.py` — skill packaging refactor; `install_skill` + `setup_agent` generalization
- **Move:** `src/canopy/agent_setup/skill.md` → `src/canopy/agent_setup/skills/using-canopy/SKILL.md`
- **New:** `src/canopy/agent_setup/skills/augment-canopy/SKILL.md` (~3-4 KB content, includes worked example of "user says X → agent edits canopy.toml")
- `tests/test_augments.py` (new), `tests/test_config.py` (extended), `tests/test_precommit.py` (extended)
- `docs/workspace.md` — document `[augments]` block + per-repo override
- `docs/agents.md` — reference the augment skill

**Implementation order:**

1. Extend `RepoConfig` + `WorkspaceConfig` dataclasses + parser. Tests pass with empty defaults (backward-compat).
2. New `repo_augments()` resolver. Pure function; unit-tested.
3. Extend `run_precommit()` signature. Update three call sites. Existing tests pass with default `None`.
4. Reorganize skill packaging. Update `cmd_init` and `cmd_setup_agent` callers.
5. Write `augment-canopy/SKILL.md`.
6. `canopy setup-agent --skill augment-canopy` flag for opt-in install.

**Verification:**
- Unit: resolver merges; per-repo wins on collision; missing keys return None/empty.
- Unit: `run_precommit` with custom `preflight_cmd` runs the override; with None, auto-detect still works.
- Integration: workspace with `augments.preflight_cmd = "echo ok && exit 0"` → `canopy preflight` returns success.
- Manual: agent reads "this workspace uses ruff for preflight" → invokes augment-canopy skill → canopy.toml updated → `canopy preflight` runs ruff.

### 2.4 — N2 bot-comment tracking + `commit --address`

(Detailed spec — same treatment as N3.)

**Goal:** treat bot review comments (CodeRabbit, Korbit, Cubic, Copilot) as a distinct workflow concern. Track per-comment "addressed by which commit." Provide a rollup ("all bot comments resolved?") and a `commit --address <comment-id>` flag with auto-formatted commit messages.

**Data model changes:**

- `integrations/github.py:_normalize_comments` (line 537): include `id` field — `"id": c.get("id")`. Backward-compat.
- **New persistent state:** `<workspace>/.canopy/state/bot_resolutions.json`. Append-only mapping `{<comment_id>: {feature, repo, commit_sha, addressed_at, comment_title}}`.
- `actions/feature_state.py:_per_repo_facts`: split `actionable_count` → `actionable_human_count` + `actionable_bot_count`. Bot determined by `author_type == "Bot"` AND author matching `bot_authors(workspace)` (uses N3's `review_bots` augment).
- `actions/feature_state.py:_decide_state`: insert `awaiting_bot_resolution` per cross-cutting 1.3.

**New CLI/MCP surface:**

- `canopy commit --address <comment-id>`:
  - Resolves `<comment-id>` against the feature's actionable bot threads (via `_per_repo_facts`)
  - Looks up comment `body` (truncated first sentence) and `url`
  - Auto-formats: `<user message>\n\nAddresses bot comment: "<title-fragment>" (<url>)`. If no `--message`, uses just the auto-line.
  - On success, appends to `bot_resolutions.json`
  - Returns existing per-repo result dict + `addressed_comment_id` field
- `canopy bot-status [--feature <X>] [--unresolved-only]`:
  - Per-PR rollup: total bot comments, resolved, unresolved
  - `--json` returns structured dict (used by agent + dashboard)
- `mcp__canopy__bot_comments_status(feature)`: same shape as CLI `--json`, returns `{feature, repos: {<repo>: {pr_number, total, resolved, unresolved, threads}}, all_resolved: bool}`

**Files to touch:**

- `src/canopy/integrations/github.py` (line 537) — add `id` field
- `src/canopy/actions/feature_state.py` — split actionable counts; new state
- `src/canopy/actions/commit.py` (line 165) — `address: str | None = None` param
- **New:** `src/canopy/actions/bot_resolutions.py` — `record_resolution()`, `load_resolutions()`, `is_resolved()`
- **New:** `src/canopy/actions/bot_status.py` — `bot_comments_status()` rollup
- `src/canopy/cli/main.py` — `cmd_bot_status` + subparser; extend `cmd_commit` argparse
- `src/canopy/mcp/server.py` — register `bot_comments_status` tool
- `tests/test_bot_resolutions.py` (new), `tests/test_bot_status.py` (new), `tests/test_commit.py` (extended), `tests/test_feature_state.py` (extended)

**Implementation order:**

1. Add `id` to normalized comments. Update fixtures in `tests/test_review_filter.py` and `tests/test_reads.py`.
2. New `actions/bot_resolutions.py` (file IO for `.canopy/state/bot_resolutions.json`). Unit tests.
3. Split actionable counts in `_per_repo_facts`. Use `bot_authors()` helper from N3 (or fallback to `author_type == "Bot"` if N3 not yet in).
4. Add `awaiting_bot_resolution` state in `_decide_state` per trigger rules.
5. Extend `commit()` with `--address` param. Resolve comment ID. Format message. Record resolution.
6. Build `bot_comments_status` rollup. CLI + MCP wiring.
7. `next_actions` updates: when state is `awaiting_bot_resolution`, surface `canopy commit --address <id> -m "..."` per unresolved thread.

**Verification:**
- Unit: resolution round-trip; rollup correctness with mixed resolved/unresolved.
- Unit: `_decide_state` returns `awaiting_bot_resolution` for the four trigger conditions.
- Integration: workspace with fake bot comment → `commit --address <id> -m "fix"` → `bot_resolutions.json` has entry → `bot_comments_status` returns `all_resolved: true`.
- Manual: real PR with bot comments → `canopy bot-status` shows them → `canopy commit --address` produces a properly attributed commit → re-run shows resolved.

### 2.5 — Historian: cross-session feature memory

(Detailed spec — same treatment as N2/N3.)

**Goal:** capture decisions, events, comment activity, and PR context for each feature into a persistent markdown memory file (`<workspace>/.canopy/memory/<feature>.md`) that future agents read automatically on `canopy switch`. Eliminates the "agent re-derives PR review state, past decisions, file context every session" tax. Especially valuable for cross-session agent handoff (Monday agent works on X; Wednesday a fresh session resumes — historian carries the context cold).

**Why after N2:** historian's "comments resolved" log consumes N2's `bot_resolutions.json` and `commit --address` flow as data sources. Without N2, historian would reimplement structured comment-resolution state.

**Eight capture categories** (decisions use the hybrid mechanism per cross-cutting 1.8):

| # | Category | Examples | Trigger |
|---|---|---|---|
| 1 | Decisions | "chose `jwt.decode` over `pyjwt`; reason: stdlib only" | **Hybrid** (per 1.8): primary `mcp__canopy__historian_decide` + Stop-hook tail-parse backup |
| 2 | Events | "edited `src/auth/oauth.py`", "ran preflight (passed)" | PostToolUse hook on Bash + Edit, in active worktree only; one-line summary |
| 3 | Pauses | "blocked on design-system copy" | Stop hook (end of session) or explicit `historian_pause` |
| 4 | Comments read | "read coderabbit comment on `cache.py:42` — suggested rename" | PostToolUse on `review_comments` MCP call; logs each unique comment URL once per session |
| 5 | Comments resolved | "addressed comment 123456 in `abc123de`: renamed `hit_rate → cache_hit_rate`" | PostToolUse on `commit --address` (consumes N2's flow); pulls comment title + sha + diff snippet |
| 6 | Classifier-resolved | "temporal classifier marked 3 threads likely-resolved (file modified since)" | PostToolUse on `review_comments`; logs classifier's `likely_resolved` output once per session |
| 7 | PR context | "opened PR #142, addresses SIN-7, includes commits abc/def/ghi" | PostToolUse on `ship` (Wave 2.4) or explicit `historian_pr_opened` |
| 8 | PR updates | "pushed 2 commits to PR #142: addressed bot 789, added edge-case test" | PostToolUse on `push` when an open PR exists for the feature |

**File format** (`.canopy/memory/<feature>.md`):

Three top-level sections, newest content first within each:

```markdown
# Feature: <name> · <linear-id>

## Resolutions log
- ✓ comment <id> (<author>, <file:line>) resolved by <sha>
  <gist of resolution>
- ⊙ comment <id> (<author>, <file:line>) likely-resolved by classifier
  <classifier rationale>
- ⚠ comment <id> (<author>, <file:line>) UNRESOLVED
  <last status>
- ⊘ comment <id> (<author>, <file:line>) DEFERRED
  <deferral reason>

## PR context
### PR #<n> — <title>
**Opened:** <date> against <base>
**Branch:** <feature>
**Rationale:** <why this PR>
**Commits:** <count>; review rounds: <n>

### Updates
- <date>: <action>

## Sessions (newest first)
### <date> — <status>
**Where we are:** ...
**Last decision:** ...
**Open questions:** ...
**Last command:** ...
**Touched:** ...
```

**Switch integration:** `mcp__canopy__switch(feature)` response includes a `memory: <markdown>` field for the new active feature. Agent sees memory immediately on switch — no extra MCP call.

**Compaction:** old sessions get LLM-summarized when (a) `canopy switch <other>` (compact the just-finished session) or (b) explicit `historian_compact`. Resolution log + PR context are NEVER compacted (always-current source of truth). Keeps the file readable as it grows.

**Files to touch:**

- **New:** `src/canopy/actions/historian.py` — `record_decision`, `record_event`, `record_pause`, `record_comment_read`, `record_comment_resolved`, `record_comment_deferred`, `record_pr_context`, `record_pr_update`, `compact`, `read`, `format_for_agent`
- **New:** `tests/test_historian.py`
- `src/canopy/mcp/server.py` — register 5 historian tools (`historian_decide`, `historian_pause`, `historian_defer_comment`, `feature_memory`, `historian_compact`)
- `src/canopy/cli/main.py` — `cmd_historian_show`, `cmd_historian_compact` (read-only inspection + manual compact trigger)
- `src/canopy/actions/switch.py` — extend response with `memory` field via `format_for_agent(feature)`
- `src/canopy/actions/commit.py` — when `--address` succeeds, also call `record_comment_resolved` (extends N2's flow)
- `src/canopy/actions/reads.py` — when `review_comments` returns, call `record_comment_read` and `record_classifier_resolved`
- `src/canopy/agent_setup/skills/using-canopy/SKILL.md` — teach: read memory on switch; call `historian_decide` at meaningful moments; emit `<historian-decisions>` tail as fallback
- Stop hook (autopilot integration): scan last assistant message for `<historian-decisions>` block; parse; dedup against tool-call writes; persist
- PostToolUse hooks (autopilot integration): events for Bash/Edit, comment-read for `review_comments`, comment-resolved for `commit --address`, pr-context for `ship`, pr-update for `push`

**Implementation order:**

1. New `actions/historian.py`: file IO + record functions for each category. Pure module; unit-tested independently.
2. MCP tool registration. The 5 new tools wrap the record functions.
3. Skill update: `using-canopy/SKILL.md` gains a "Historian" section teaching when to call each tool, plus the tail-fallback format.
4. Switch integration: extend `switch_impl` response with `memory: format_for_agent(feature)`.
5. Hooks integration: PostToolUse + Stop hook bundle (lands as part of autopilot's observer category).
6. Commit + review integration: extend N2's `commit --address` flow to call `record_comment_resolved`; extend `review_comments` reads to call `record_comment_read` and `record_classifier_resolved`.
7. Compaction: LLM-summarize old sessions; trigger on switch-away.

**Verification:**
- Unit: each `record_*` appends correctly; `format_for_agent` renders all 3 sections in order; compaction summarizes without losing resolution log or PR context.
- Integration: `workspace_with_feature` → simulate session: `review_comments` call → `commit --address` → `historian_decide` → switch away → switch back → assert memory has resolution-log entry + classifier-resolved entry + decision entry + session entry.
- Hybrid mechanism: agent calls `historian_decide` directly: persisted once. Agent emits format-tail without tool call: Stop-hook persists. Agent does both with same title: deduped to one entry.
- Manual: real PR with bot comments → use canopy normally for an hour → `canopy historian show <feature>` → eyeball that memory captures decisions, events, resolutions, classifier output, PR context.

**Effort:** ~5–6 days. Depends on autopilot's Stop + PostToolUse hook infrastructure being in place; if those slip, historian's auto-capture (categories 2, 4, 5, 6, 7, 8) defers and only categories 1 (decisions, hybrid) and 3 (pauses, explicit) ship in v1.

---

## Section 3 — Existing pending plans (status + position in sequence)

Each plan stays in its existing file. The summaries below note where they slot relative to the new work.

### 3.1 — Wave 2.4 `ship` ([plan](~/.claude/plans/2026-04-26-canopy-wave-2-4-ship.md))

Ship a feature: commit + push + open/update PR per repo, with cross-repo PR descriptions linking siblings. Depends on Wave 2.3 (✅ shipped). **Slots after N2** (so PRs opened by `ship` correctly trigger the bot-comment-tracking workflow). Medium priority — can be deferred if N1/N2/N3 take longer than expected.

### 3.2 — Wave 4 `draft_replies` ([plan](~/.claude/plans/2026-04-26-canopy-wave-4-draft-replies.md))

Auto-draft reply text for PR comments addressed in subsequent commits. Template-based (no LLM in v1). Depends on the temporal classifier (✅ shipped). **Slots alongside or after N2** — both deal with bot/comment workflows; cross-pollination likely. Useful pairing: `commit --address <id>` resolves a comment; `draft_replies` then drafts the "Done in <sha>" reply.

### 3.3 — `worktree-bootstrap` ([plan](~/.claude/plans/2026-04-28-canopy-worktree-bootstrap.md))

Env-file copy + dep install + `.code-workspace` generation when worktrees are created. Adds `env_files`, `install_cmd`, `ide_settings` per `RepoConfig`. **Independent — can ship anytime after doctor.** No deps on N2/N3/arch-doc. Quality-of-life win for new feature spinups.

### 3.4 — CI status ([plan](~/.claude/plans/2026-04-28-canopy-ci-status.md))

CI status in `feature_state` + `awaiting_ci` state + `pr_checks` MCP tool. **Slots after N2** — both add states to the state machine; would be useful to land them together to avoid two state-machine refactors. Or after `ship` to cleanly answer "is this PR truly ready to merge?"

### 3.5 — Sidebar single-tree ([plan](~/.claude/plans/2026-04-26-canopy-sidebar-single-tree.md))

Extension UI: collapse 5 sidebar trees → 1 unified tree. **Independent of all backend work.** Can ship anytime. Good candidate for a quick win between heavier backend plans.

### 3.6 — Action drawer ([plan](~/.claude/plans/2026-04-26-canopy-action-drawer.md))

Extension UI: rebuild dashboard right rail with ~16 wired actions. **Depends on Wave 2.4 (`ship`) + Wave 4 (`draft_replies`)** for full action surface. Without those, ~6 of the 16 actions stay dark. Lowest-priority extension work.

### 3.7 — Cross-feature conflicts ([plan](~/.claude/plans/2026-04-28-canopy-cross-feature-conflicts.md))

`canopy conflicts` for cross-feature file-overlap detection. **Lowest priority overall.** Nice-to-have; defer until everything above lands.

---

## Section 4 — Recommended execution order

Concrete sequence with rough effort estimates. Strikethrough = shipped.

1. ✅ ~~**Architecture doc** (`docs/architecture/providers.md`) — design only, ~1 day~~ (M0, PR #7)
2. ✅ ~~**Doctor** (existing plan + 6 new categories from §2.2 + version handshake) — ~3-4 days~~ (M1, PR #8)
3. **M2 augment skill** (§2.3) — ~2-3 days
4. **M3 bot-comment tracking** (§2.4) — ~3 days
5. **M4 Historian** (§2.5) — ~5-6 days
6. ✅ ~~**First issue-provider scaffold** — Linear refactored into the contract, GitHub Issues backend — ~3-4 days~~ (M5, PR #9 — landed early in parallel with M1, since it had no real dep on M2–M4)
7. **M6 Worktree bootstrap** ([3.3](worktree-bootstrap.md)) — ~2 days
8. **M7 Sidebar single-tree** ([3.5](sidebar-single-tree.md)) — ~1 day
9. **M8 Wave 2.4 `ship`** ([3.1](wave-2-4-ship.md)) — ~2-3 days
10. **M9 Wave 4 `draft_replies`** ([3.2](wave-4-draft-replies.md)) — ~2 days
11. **M10 CI status** ([3.4](ci-status.md)) — ~2 days
12. **M11 Action drawer** ([3.6](action-drawer.md)) — ~3-4 days
13. **M12 Cross-feature conflicts** ([3.7](cross-feature-conflicts.md)) — ~1-2 days

Estimated total: ~30-36 days when planned. ~7-8 days shipped (items 1, 2, 6); remaining ~22-28 days across M2–M4 + M6–M12.

---

## Section 5 — Out of scope / explicit deferrals

| Item | Why deferred |
|---|---|
| Wave 2.9 B4 — cross-workspace MCP (`workspace_select` tool, global `~/.claude/mcp.json`, `~/.canopy/workspaces.json` registry) | Bigger design surface; per-workspace `.mcp.json` works fine after doctor lands. Revisit later. |
| Augment config via `canopy config augments.<key>` CLI | `cmd_config` is flat-only; nested-key support is its own refactor. Augment-canopy skill writes TOML directly in v1. |
| Augment validation (catch typos like `preflight_cmmd`) | Lenient parser silently ignores. Add `canopy doctor --check-augments` later, or fold into doctor. |
| LLM-augmented draft replies on bot comments | Wave 4.1 future work; v1 templates are sufficient. |
| Auto-running `canopy doctor` on extension activation | User-invoked only in v1; opt-in flag possible later. |
| Per-feature augments (different preflight for different features in same workspace) | Workspace + per-repo is enough for v1. |
| **Provider-injection for non-issue cases** (bot-author, CI providers, code-review platforms, IDE workspace formats, pre-commit frameworks) | Effort cap: < 5% of arch-doc effort. Adopt the pattern only if it drops in seamlessly. Otherwise current handling stays. |

---

## Section 6 — End-to-end verification (smoke test for the first 6 items)

After arch doc + doctor + N3 + N2 + historian + first issue-provider scaffold land, this scenario should work cold on a new machine:

```bash
# Fresh machine. Install via pipx.
pipx install git+https://github.com/ashmitb95/canopy.git

# In a multi-repo workspace:
cd ~/projects/my-product
canopy init                                       # creates canopy.toml, hooks, .mcp.json, installs using-canopy skill
canopy setup-agent --skill augment-canopy        # opt-in second skill (N3)

# Customize per-workspace via the agent (uses augment-canopy skill):
# user: "this workspace uses ruff for preflight, tracks coderabbit + korbit bots, uses GitHub Issues not Linear"
# agent edits canopy.toml: [augments] preflight_cmd, review_bots, [issue_provider] name="github_issues" repo="..."

# Use canopy:
canopy switch SIN-42                              # provider-agnostic alias resolves via configured issue_provider
                                                  # response includes memory: <markdown> from historian (empty on first switch)
canopy preflight                                  # honors augments.preflight_cmd (ruff)
canopy commit -m "..."                            # historian records event + decision (via skill-driven historian_decide)
canopy push

# Address bot comments on the PR:
canopy bot-status SIN-42                          # lists unresolved bot comments (N2)
canopy commit --address 123456 -m "rename foo to bar"   # auto-formats with comment URL
                                                        # historian records resolution (sha + comment title) automatically

# Switch away and come back days later:
canopy switch SIN-99                              # historian compacts SIN-42's last session
# ...work on other feature for 2 days...
canopy switch SIN-42                              # response.memory contains: resolutions log (resolved + classifier-resolved + deferred), PR context, last paused session
                                                  # agent reads memory; knows immediately what's resolved, what's open, where it left off

# 6 months later, on a different machine:
canopy doctor --check                             # detects stale CLI/MCP/skill (doctor + N1 categories)
canopy doctor --fix                               # converges everything to current
```

Each step exercises one of the first-6 deliverables. The full chain validates that arch doc → doctor → N3 → N2 → historian → issue-provider scaffold compose without friction.

---

## Section 7 — Critical files (cross-plan index)

Files touched by multiple sub-plans / artifacts. Listed once here so executors of any individual plan know which adjacent plans share the file.

| File | Touched by |
|---|---|
| [`src/canopy/__init__.py`](src/canopy/__init__.py) | Doctor (§2.2 — `__version__`) |
| [`src/canopy/agent_setup/__init__.py`](src/canopy/agent_setup/__init__.py) | Doctor (§2.2 — install_skill iteration), N3 (§2.3 — generalize signatures) |
| [`src/canopy/agent_setup/skills/using-canopy/SKILL.md`](src/canopy/agent_setup/skills/using-canopy/SKILL.md) | N3 (§2.3 — moved + extended), Historian (§2.5 — teach historian tools + tail format) |
| [`src/canopy/cli/main.py`](src/canopy/cli/main.py) | Doctor (`cmd_doctor`), N2 (`cmd_bot_status`, `cmd_commit --address`), N3 (`run_precommit` call site), Historian (`cmd_historian_show`, `cmd_historian_compact`) |
| [`src/canopy/mcp/server.py`](src/canopy/mcp/server.py) | Doctor (`version()`), N2 (`bot_comments_status`), N3 (`run_precommit` call site), arch doc (issue-provider tools), Historian (5 historian tools) |
| [`src/canopy/workspace/config.py`](src/canopy/workspace/config.py) | N3 (augment fields), arch doc (`[issue_provider]` block) |
| [`src/canopy/integrations/github.py`](src/canopy/integrations/github.py) (line 537) | N2 (add `id` field) |
| [`src/canopy/integrations/precommit.py`](src/canopy/integrations/precommit.py) | N3 (signature change) |
| [`src/canopy/integrations/linear.py`](src/canopy/integrations/linear.py) | Arch doc / first scaffold (refactor into IssueProvider contract) |
| [`src/canopy/actions/feature_state.py`](src/canopy/actions/feature_state.py) | N2 (state + facts) |
| [`src/canopy/actions/commit.py`](src/canopy/actions/commit.py) | N2 (`--address` param), Historian (call `record_comment_resolved` on `--address` success) |
| [`src/canopy/actions/reads.py`](src/canopy/actions/reads.py) | Historian (call `record_comment_read` + `record_classifier_resolved` on `review_comments`) |
| [`src/canopy/actions/switch.py`](src/canopy/actions/switch.py) | Historian (extend response with `memory: <markdown>` field) |
| [`src/canopy/features/coordinator.py`](src/canopy/features/coordinator.py) | N3 (`run_precommit` call site) |
| [`vscode-extension/src/canopyClient.ts`](vscode-extension/src/canopyClient.ts) | Doctor (version handshake on MCP startup) |

## Section 8 — New files this roadmap introduces

- **`docs/architecture/providers.md`** — provider-injection design reference (arch doc, §2.1)
- `src/canopy/upgrade/` *(deleted from earlier plan — no longer a separate package; logic absorbed into `src/canopy/actions/doctor.py`)*
- `src/canopy/actions/augments.py` (N3)
- `src/canopy/agent_setup/skills/using-canopy/SKILL.md` (moved from `agent_setup/skill.md`) (N3 + Historian extensions)
- `src/canopy/agent_setup/skills/augment-canopy/SKILL.md` (N3 — new content)
- `src/canopy/actions/bot_resolutions.py`, `bot_status.py` (N2)
- **`src/canopy/actions/historian.py`** (Historian, §2.5)
- **`<workspace>/.canopy/memory/<feature>.md`** (Historian, §2.5 — runtime artifact, per-feature; not committed to repos by default — listed in `.canopy/.gitignore`)
- **`src/canopy/providers/__init__.py`**, `linear.py`, `github_issues.py` (first issue-provider scaffold)
- `tests/test_doctor.py` extensions (existing file; adds install-staleness + version-handshake fixtures)
- `tests/test_augments.py`, `tests/test_bot_resolutions.py`, `tests/test_bot_status.py` (new)
- `tests/test_historian.py` (Historian, §2.5)
- `tests/test_providers.py` (first issue-provider scaffold)

---

## Section 9 — Tracking via in-tree docs

Tracking lives in [INDEX.md](INDEX.md), not GitHub issues. Each plan file's YAML frontmatter declares its `status` / `priority` / `effort` / `depends_on`; INDEX.md is the rolled-up epic dashboard with a checkbox per milestone.

**Why in-tree docs instead of issues:**

- The plans are already detailed and reviewable as files. Duplicating into issue bodies adds maintenance overhead.
- The user is mostly solo on canopy today; full GitHub Issues machinery (labels, templates, multi-issue dependency graph) is overkill.
- The plan file is the spec; INDEX.md aggregates status. Future contributors (when they appear) can comment on the design via PR review on the plan file.

**Workflow:**

1. When a milestone starts: update its checkbox/glyph in INDEX.md (🟦 → 🟨); update its plan's frontmatter (`status: queued` → `in-progress`).
2. When it ships: ✅ in INDEX.md, `status: shipped` in frontmatter, move the plan to `archive/` with a date.
3. Plan amendments happen via PR on the plan file itself.
4. If multi-contributor coordination becomes needed later, revisit issue tracking — the in-tree approach is the floor, not the ceiling.

## Migration history

The `~/.claude/plans/` → `docs/plans/` migration is complete (PR #6). All plan files live in-tree now; `~/.claude/plans/` is deprecated as a canonical location. INDEX.md tracks status; this roadmap captures rationale.
