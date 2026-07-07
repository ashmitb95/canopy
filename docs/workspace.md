# Workspace

This is the configuration and state reference: what `canopy.toml` declares, what
`canopy init` discovers, and every file canopy writes under `.canopy/`.

Canopy 4.0 runs on **two surfaces** (see [concepts.md](concepts.md)): the **agent
contract** (15 MCP tools — path-safety, registry, focus, safe git ops, recovery)
and the **human/dashboard management surface** (all CLI commands, each with
`--json`). The state files below are shared plumbing — some drive the agent's
`context`/`switch` loop, some feed the management `resume`/triage briefs. Each
entry notes which.

## Layout

```
my-product/
├── canopy.toml                    ← workspace definition (repos, slots, augments, issue provider)
├── .mcp.json                      ← MCP server registry (canopy + linear/github if configured)
├── backend/                       ← canonical / trunk (whichever feature is currently in focus)
├── frontend/                      ← canonical / trunk
└── .canopy/
    ├── features.json              ← feature lanes, linear links, per-repo branches map
    ├── mcps.json                  ← OPTIONAL: external MCP servers (alternative to .mcp.json)
    ├── memory/
    │   └── <feature>.md          ← historian per-feature persistent memory (management)
    ├── state/
    │   ├── heads.json             ← post-checkout hook records HEAD per repo (drift fast path)
    │   ├── heads.json.lock        ← fcntl lock for concurrent hook fires
    │   ├── slots.json             ← canonical/trunk + warm-slot occupancy + LRU + bootstrap + in_flight
    │   ├── active.json            ← intended-focus pointer (set by `start` before any checkout)
    │   ├── preflight.json         ← last preflight result per feature (state-machine input)
    │   ├── prs.json               ← offline fallback cache for the remote PR/CI overlay
    │   ├── deps_fingerprints.json ← per-worktree lockfile hash (bootstrap deps short-circuit)
    │   ├── visits.json            ← {feature: {last_visit, previous_visit}} for the resume brief
    │   ├── thread_resolutions.json ← canopy-driven GitHub thread closure log (management)
    │   └── bot_resolutions.json   ← legacy bot-comment resolution log (read-only in 4.0)
    └── worktrees/
        ├── worktree-1/            ← slot 1 — currently hosts feature X
        │   ├── backend/           ← X's backend checkout
        │   └── frontend/          ← X's frontend checkout
        └── worktree-2/            ← slot 2 — currently hosts feature Y
            └── backend/           ← Y is API-only; only one repo present
```

The number of warm slots is bounded by `[workspace] slots` (default **2** — so 1
canonical + 2 warm = 3 live trees max). Features beyond the cap live as cold
branches. Slot identity (`worktree-1`, `worktree-2`, ...) is stable across feature
swaps; feature occupancy is transient. See [concepts.md §4](concepts.md#4-the-slot-model).

Plus, outside the workspace:

- `~/.canopy/mcp-tokens/<server>.{client,tokens}.json` — OAuth token cache (per-user, per server)
- `~/.claude/skills/using-canopy/SKILL.md` — agent integration skill (per-user mirror)
- `~/.claude/skills/augment-canopy/SKILL.md` — opt-in augment skill (per-user mirror)

## canopy.toml

```toml
[workspace]
name = "my-product"
slots = 2                    # warm-slot cap for switch (default 2)
                             # pre-3.0 max_worktrees raises ConfigError — run canopy migrate-slots
ide = "vscode"               # optional: "vscode" | "none" (default) — worktree .code-workspace gen
bootstrap_default = false    # optional: if true, --bootstrap is implicit on slot creation

[[repos]]
name = "backend"
path = "./backend"
role = "backend"
lang = "python"
default_branch = "main"      # optional; per-repo; defaults to "main"

[[repos]]
name = "frontend"
path = "./frontend"
role = "frontend"
lang = "typescript"

[issue_provider]                  # optional; defaults to linear
name = "linear"                   # or "github_issues"

[issue_provider.linear]           # provider-specific options
api_key_env = "LINEAR_API_KEY"

# [issue_provider.github_issues]
# repo = "owner/repo"
# labels_filter = ["bug", "feature"]   # optional — restrict issue listing

[augments]                        # optional — per-workspace behavioral overrides
preflight_cmd = "make check"      # overrides pre-commit auto-detection
test_cmd = "pytest"               # reserved for future canopy test
review_bots = ["coderabbit", "korbit"]   # case-insensitive substring; bot-comment tracking
```

### `[workspace]`

| Key | Type | Default | Notes |
|---|---|---|---|
| `name` | string | — | Required. Workspace label. |
| `slots` | int ≥ 1 | `2` | Warm-slot cap for `switch`. Canonical/trunk is separate, so 1 + `slots` live trees. Pre-3.0 `max_worktrees` now raises `ConfigError` → run `canopy migrate-slots`. |
| `ide` | string | `"none"` | `"vscode"` generates a `.code-workspace` for each warm slot (worktree bootstrap). |
| `bootstrap_default` | bool | `false` | When true, slot creation bootstraps (env/deps/hooks/IDE) without an explicit `--bootstrap`. |

Only `name` and `slots` are exposed through `canopy config` (which is flat, `[workspace]`-only).

### `[[repos]]`

One table per repo in the workspace. `name` and `path` are required; everything
else is optional and mostly auto-detected by `canopy init`.

| Key | Type | Default | Notes |
|---|---|---|---|
| `name` | string | — | Required. Repo identifier used everywhere (`<repo>#<n>`, `<repo>:<branch>`, etc.). Must be unique. |
| `path` | string | — | Required. Relative path from the workspace root (e.g. `"./backend"`). |
| `role` | string | `""` | Optional: `backend` / `frontend` / `shared` / `infra`. Guessed from name + language. |
| `lang` | string | `""` | Optional: primary language, detected by file-extension frequency. |
| `default_branch` | string | `"main"` | Per-repo trunk. Out-of-scope repos snap here on `switch`. |
| `augments` | table | `{}` | Per-repo override of any `[augments]` key. Per-repo wins on collision. |
| `env_files` | list[string] | `[]` | Worktree bootstrap: files copied into a new warm slot (e.g. `[".env"]`). |
| `install_cmd` | string | `""` | Worktree bootstrap: deps install command (e.g. `"pnpm install"`). Short-circuited by lockfile fingerprint (see `deps_fingerprints.json`). |
| `ide_settings` | table | `{}` | Worktree bootstrap: per-repo settings merged into the generated `.code-workspace`. |

### `[issue_provider]`

Selects which issue tracker backs feature linking, `canopy switch <issue>`, and
the CLI issue reads (`canopy issues` / `canopy issue`). The contract is defined in
[docs/architecture/providers.md](architecture/providers.md). Two backends ship today:

| Name | Sub-table options | Notes |
|---|---|---|
| `linear` (default) | `api_key_env` (default `"LINEAR_API_KEY"`) | Uses the Linear MCP server registered in `.mcp.json` / `.canopy/mcps.json`. |
| `github_issues` | `repo` (required, `"owner/repo"`), `labels_filter` (optional list) | Uses the `gh` CLI; no MCP server required. |

Omit the block entirely to keep the legacy default (Linear, with a one-time
deprecation notice). Only one backend is active per workspace; per-repo overrides
are reserved for a future plan. Issue reads live on the management surface — the
agent does not fetch issues directly.

### `[augments]` — per-workspace behavioral overrides

Customize how canopy operations behave for this workspace without changing any
code. Keys recognized today:

| Key | Type | Consumer | Surface | Notes |
|---|---|---|---|---|
| `preflight_cmd` | string | `canopy preflight` / `preflight` MCP tool | agent | Runs via `sh -c`, so pipes and `&&` chains work. Falls back to auto-detected pre-commit framework when absent. |
| `test_cmd` | string | future `canopy test` | — | Schema-reserved. Safe to set now; consumed when the command lands. |
| `review_bots` | list[string] | bot-comment tracking (`bot-status`, `feature_state`, `resume`) | management | Case-insensitive author substrings. Workspace-level only — the same bot account comments across all repos. |

**Per-repo overrides** apply to any key by adding an `augments` table to the
matching `[[repos]]` entry. Per-repo wins on collision:

```toml
[augments]
preflight_cmd = "make check"

[[repos]]
name = "api"
path = "./api"
augments = { preflight_cmd = "uv run pytest tests/fast" }   # api-only override
```

The augment block is **not** reachable through `canopy config` (that command is
flat-only). Use the bundled `augment-canopy` skill (install with
`canopy setup-agent --skill augment-canopy`) to mutate it from the agent. The
parser is intentionally lenient: unknown keys are preserved (forward-compat) and
validation is deferred to `canopy doctor` in a future release.

> The pre-4.0 `auto_resolve_threads_on_address` augment is no longer wired to any
> command — `commit --address` (which consumed it) was removed when 4.0 stripped
> `commit` to commit-only. Setting it is a harmless no-op.

## Discovery: `canopy init`

`canopy init` (and `canopy init --force`, the reinit path) scans the immediate
children of the workspace root:

1. **Detect repos.** A child directory is a repo if it contains `.git`. A `.git`
   *directory* is a normal repo; a `.git` *file* is a linked worktree (tagged
   `is_worktree` + `worktree_main`). Non-git dirs are reported as skipped.
2. **Infer metadata.** For each repo, `discovery.py` detects the primary language
   (extension frequency), the default branch (remote `origin/HEAD`, else local
   `main`/`master`, else current HEAD), and guesses a role from the name/language.
3. **Write `canopy.toml`.** Only `[workspace] name` + `[[repos]]` entries
   (`name`, `path`, and any non-empty `role`/`lang`/non-`main` `default_branch`).
   `slots`, `[augments]`, `[issue_provider]`, and the bootstrap keys are **not**
   generated — add them by hand.
4. **Install drift hooks.** A `post-checkout` hook goes into each non-worktree
   repo; worktrees inherit it via `commondir`.
5. **Set up the agent** (unless `--no-agent`): installs the `using-canopy` skill
   and writes the `canopy` entry into `.mcp.json`.

Existing warm slots under `.canopy/worktrees/` are reported keyed by their
occupant feature (resolved through `slots.json`, not by slot id). Use
`--dry-run` to print the generated TOML without writing, or `--json` for the
machine shape.

## .canopy/features.json

```json
{
  "SIN-12-search": {
    "repos": ["backend", "frontend"],
    "status": "active",
    "created_at": "2026-04-25T17:00:00Z",
    "linear_issue": "SIN-12",
    "linear_url": "https://linear.app/x/issue/SIN-12",
    "linear_title": "Add /search endpoint with shared filter types"
  },
  "SIN-13-fixes": {
    "repos": ["backend"],
    "status": "active",
    "created_at": "2026-04-25T17:00:00Z",
    "branches": {
      "backend": "SIN-13-fixes-v2"
    }
  }
}
```

| Field | Notes |
|---|---|
| `repos` | List of canopy-registered repo names participating in the lane. Single-repo features are first-class — a UI-only feature lists only `["frontend"]`. |
| `status` | `active` / `merged` / `archived`. `canopy done` flips to `archived`. |
| `linear_issue` / `linear_url` / `linear_title` | Optional Linear link. Powers alias resolution and integration. |
| `branches` | **Optional per-repo branch override.** When a feature uses different branch names per repo (legacy, mismatched naming), set this map. Without it, the branch name is assumed to equal the feature name. Use `lane.branch_for(repo)` — never assume branch == feature name. See [concepts.md](concepts.md#universal-aliases). |
| `created_at` | ISO 8601 timestamp. |

## .canopy/state/slots.json

Written by `switch` and `reclaim` (and the `slot_load`/`slot_clear`/`slot_swap`
primitives). Single source of truth for which feature is canonical/trunk and which
features occupy warm slots. **Drives the agent surface:** `context` reports the
active feature from here; `switch` reads and rewrites it transactionally.

```json
{
  "version": 1,
  "slot_count": 2,
  "canonical": {
    "feature": "SIN-12-search",
    "activated_at": "2026-04-25T17:34:21Z",
    "per_repo_paths": {
      "backend": "/Users/x/projects/my-product/backend",
      "frontend": "/Users/x/projects/my-product/frontend"
    }
  },
  "previous_canonical": "SIN-11-old",
  "slots": {
    "worktree-1": {"feature": "SIN-13-fixes", "occupied_at": "2026-04-25T15:02:55Z"},
    "worktree-2": {"feature": "SIN-14-cache", "occupied_at": "2026-04-21T08:14:09Z"}
  },
  "last_touched": {
    "SIN-12-search": "2026-04-25T17:34:21Z",
    "SIN-13-fixes":  "2026-04-25T15:02:55Z",
    "SIN-14-cache":  "2026-04-21T08:14:09Z"
  },
  "bootstrap": {
    "worktree-1": {"env": "ok", "deps": "ok", "hooks": "ok", "ide": "ok"}
  },
  "in_flight": null
}
```

| Field | Notes |
|---|---|
| `canonical` | The feature currently checked out in the main repo dirs (trunk — the only place to run code). `per_repo_paths` is the source of truth for `canopy_run` and IDE openers. Staleness check on read: any missing path clears only the canonical pointer — slots and last_touched are preserved. |
| `previous_canonical` | Feature name that was canonical before the last switch. |
| `slots` | Map from slot id (`"worktree-1"`, ...) to `{feature, occupied_at}`. Slot ids are stable; feature occupancy is transient. Missing slot dirs are silently dropped on read. |
| `last_touched` | ISO timestamp per feature; used by switch's LRU eviction when the cap fires. |
| `bootstrap` | Per-slot bootstrap status map (env / deps / hooks / IDE). Populated by `worktree_bootstrap`; a loud failure state here surfaces when deps install fails in the background. |
| `in_flight` | Non-null during a switch transaction. Carries `{feature_being_promoted, previously_canonical, started_at, per_repo_completed, failed_repo, error_what}`. A non-null marker means the previous switch may have partially completed; canopy rolls back on the next operation. See [architecture.md](architecture.md) for the rollback protocol. |

Replaces the pre-3.0 `active_feature.json`. Run `canopy migrate-slots` for a
one-shot idempotent migration; `canopy doctor` still recognizes and clears a
stale `active_feature.json` in un-migrated workspaces.

## .canopy/state/active.json

The **intended-focus** pointer, written by `start`. Decoupled from
`slots.canonical` on purpose: `canonical` means "checked out and gated" (set at
the first `join`); `active` means "this is the feature I'm focused on" and can
precede any checkout (lazy feature growth). `context` reports
`active = slots.canonical.feature or active.json`.

```json
{ "active_feature": "SIN-12-search" }
```

Atomic temp+rename writes. Cleared by `clear_active`.

## .canopy/state/visits.json

Written on the management surface by the `resume` brief (`last_visit.py`) and
bumped for the incoming feature on `switch`. Provides the time-window anchor for
the resume brief's `since_last_visit` delta.

```json
{
  "SIN-12-search": {
    "last_visit":     "2026-05-29T15:30:00Z",
    "previous_visit": "2026-05-28T10:00:00Z"
  }
}
```

Atomic temp+rename writes. The anchor advances exactly once per resume call (the
single-bump invariant — see [concepts.md §5](concepts.md#5-returning-to-a-feature--the-resume-brief)).

## .canopy/state/thread_resolutions.json

Append-only log of GitHub review threads that canopy itself resolved (via
`canopy resolve` / `reply` on the management surface). The resume brief uses this
to distinguish "resolved by canopy" from "resolved by a human on GitHub directly."

```json
{
  "PRRT_abc123": {
    "resolved_by_canopy_at": "2026-05-29T12:00:00Z",
    "feature": "SIN-12-search",
    "via_command": "resolve",
    "via_commit_sha": "1367190a"
  }
}
```

Atomic temp+rename writes.

## .canopy/state/bot_resolutions.json

Append-only log of bot review comments that were marked addressed. Read by
`bot-status`, `feature_state`, and the `resume` brief to subtract resolved bot
comments from the actionable count.

> **Legacy / read-only in 4.0.** The writer was `commit --address`, which was
> removed when `commit` was stripped to commit-only. Nothing writes this file in
> 4.0; the readers still consume it for workspaces that accumulated entries
> under earlier versions.

```json
{
  "123456": {
    "feature": "SIN-12-search",
    "repo": "backend",
    "commit_sha": "abc123de",
    "addressed_at": "2026-05-02T17:30:00Z",
    "comment_title": "rename hit_rate to cache_hit_rate",
    "comment_url": "https://github.com/owner/repo/pull/142#discussion_r123456"
  }
}
```

Keys are stringified GitHub comment IDs.

## .canopy/state/heads.json

Written by the post-checkout hook on every branch checkout in any registered
repo. Read by `drift` (the fast cached path), `doctor`, and the management
`historian`/`feature_state`.

```json
{
  "backend": {
    "branch":   "SIN-12-search",
    "sha":      "1367190ac97a...",
    "prev_sha": "fda11998caa2...",
    "ts":       "2026-04-25T17:43:00Z"
  },
  "frontend": { "..." : "..." }
}
```

Concurrent hook fires across repos serialize on `heads.json.lock` (fcntl) +
atomic rename. `feature_state` uses live git rather than this file, so it stays
correct even when the hook has not fired.

## .canopy/state/preflight.json

Written by `canopy preflight <feature>` / the `preflight` MCP tool. Read by
`feature_state`.

```json
{
  "SIN-12-search": {
    "passed": true,
    "ran_at": "2026-04-25T17:58:41Z",
    "head_sha_per_repo": {
      "backend":  "1367190a...",
      "frontend": "e8a21503..."
    },
    "summary": "preflight passed"
  }
}
```

Freshness check: each repo's recorded sha must equal current HEAD. Any moved HEAD
makes the result stale; `feature_state` falls back from `ready_to_commit` to
`in_progress` with a `preflight_stale` warning.

## .canopy/state/prs.json

Offline **fallback cache** for the remote PR/CI overlay — not the source of truth
(a live GitHub fetch is). Served only when a live fetch is impossible
(offline / rate-limited) and to the dashboard, always flagged with `fetched_at`
so staleness is visible. Feature-centric shape (matches triage's grouping).

```json
{
  "fetched_at": "2026-06-30T09:12:00Z",
  "features": { "SIN-12-search": { "backend": { "...": "PR/CI summary" } } }
}
```

Written whenever the remote overlay is refreshed; consumed by `context`'s remote
tier and by `triage`. Atomic temp+rename writes.

## .canopy/state/deps_fingerprints.json

Records the lockfile hash of each warm slot after a successful deps install, so
worktree bootstrap can skip `install_cmd` when the lockfile is unchanged. The
marker lives **outside** the worktree so it never dirties it (an in-tree marker
made every warm slot with real deps permanently dirty, defeating `reclaim`).

```json
{
  "/Users/x/projects/my-product/.canopy/worktrees/worktree-1/frontend": "sha256:…"
}
```

Keyed by absolute worktree path. Written by `worktree_bootstrap` (deps step).

## .mcp.json

Registers MCP servers visible to MCP-aware clients (Claude Code, Cursor).
`canopy init` writes the `canopy` entry; add others (linear, github) here or in
`.canopy/mcps.json` (canopy reads both):

```json
{
  "mcpServers": {
    "canopy": {
      "command": "canopy-mcp",
      "args": [],
      "env": { "CANOPY_ROOT": "/Users/x/projects/my-product" }
    },
    "linear": {
      "type": "http",
      "url": "https://mcp.linear.app/mcp",
      "oauth": true
    }
  }
}
```

The `canopy` server exposes the 15-tool agent surface. Management commands are
**not** MCP tools — they run via `canopy <cmd> --json`. See [mcp.md](mcp.md) for
transport details (stdio, HTTP+OAuth) and the tool list.

## Alias resolution

Every command that takes a feature accepts an alias. Resolution order:

1. **Exact match** — alias matches a feature name in `features.json`.
2. **Per-repo branches map match** — alias matches a value in any lane's `branches` map.
3. **Implicit multi-repo feature** — alias matches a branch present in 2+ repos (no features.json entry needed).
4. **Implicit single-repo feature** — alias matches a branch present in any single repo.
5. **Linear ID match** — alias matches the `linear_issue` field of any lane.
6. **Slot id** — `worktree-N` resolves to that slot's current occupant.

If multiple matches exist, canopy raises `ambiguous_alias` listing the
candidates. If none match, raises `unknown_alias` with
`expected: {explicit_features, implicit_features}`.

The management read commands (`pr`, `branch info`, `comments`) also accept
specific forms that bypass feature lookup:

- `<repo>#<n>` — specific PR by number
- PR URL — `https://github.com/owner/repo/pull/1287`
- `<repo>:<branch>` — specific branch in a specific repo

## Context detection

`canopy preflight` (without `--feature`) and other context-aware commands detect
where you are in the filesystem:

| Context type | Detection | Scope |
|---|---|---|
| `feature_dir` | Inside `.canopy/worktrees/worktree-N/` | All repos in the slot's feature |
| `repo_worktree` | Inside `.canopy/worktrees/worktree-N/<repo>/` | Single repo |
| `repo` | Inside a workspace repo directory | Single repo (feature inferred from current branch when non-default) |
| `workspace_root` | At the `canopy.toml` level | All repos |

Implementation in `canopy/workspace/context.py`. Returns `repo_paths` +
`repo_names` (directory-derived) plus `feature` + `workspace_root`.
