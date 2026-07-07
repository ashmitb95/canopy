# Commands

The CLI is canopy's **human / dashboard surface**. Every command supports `--json` — that JSON is the contract the dashboard (and any GUI) consumes. Commands that accept a feature name accept any [universal alias](concepts.md#universal-aliases) (feature name, Linear ID, `<repo>#<n>`, PR URL, `<repo>:<branch>`, or slot id).

## Two surfaces

Canopy 4.0 ("the great distillation") splits into two surfaces:

- **The agent (MCP) surface** — 15 tools for the safe core loop: path-safety, registry, focus, safe git ops, recovery. The agent names semantic context and canopy resolves paths, so it can't `cd` to the wrong repo. See [mcp.md](mcp.md).
- **The human / management surface** — everything else: PR triage, review-comment classification, ship, historian, resume briefs, conflict detection, Linear/GitHub reads. This lives in `canopy/management/` and is reached only through the CLI (`canopy <cmd> --json`). It is deliberately **not** exposed to the agent, so the agent's context budget goes to comprehension, not orchestration.

The CLI keeps **all** commands (core + management). Below, commands that are **also** one of the 15 agent MCP tools are marked ⚡ **(agent tool)**; unmarked commands are human/CLI-only management. The 15 mapped commands are: `context`, `start`, `join`, `switch`, `reclaim`, `run`, `commit`, `push`, `preflight`, `doctor`, `drift`, `stash save --feature`, `stash pop --feature`, `worktree-bootstrap`, and `--version`.

Organized by **workflow stage** — top to bottom matches a typical day.

## Setup

| Command | What it does |
|---|---|
| `canopy init [path]` | Discover repos, write `canopy.toml`, install drift hooks, register the `using-canopy` skill, add canopy MCP to `.mcp.json`. `--name` sets the workspace name, `--dry-run` prints the toml without writing, `--force` overwrites an existing one, `--no-agent` skips the skill + MCP bits. |
| `canopy setup-agent` | Install (or refresh) the agent integration — skills, MCP config, and (with `--hooks`) the Claude Code enforcement hooks. `--check` reports status without changing anything. `--reinstall` forces overwrite of foreign/current files. `--skill-only` / `--mcp-only` scope partial installs; `--skill <name>` (repeatable) installs an extra bundled skill (e.g. `augment-canopy`). |
| `canopy hooks install\|uninstall\|status` | Manage the **drift-tracking** post-checkout hooks per repo. These feed `.canopy/state/heads.json`. (Distinct from the enforcement hooks installed by `setup-agent --hooks`; see "Enforcement hooks" below.) |
| `canopy config [key] [value]` | Read/write workspace settings (e.g. `slots`). No args prints all settings; a key alone reads it; key + value writes it. |
| `canopy migrate-slots` | One-shot migration from pre-3.0 feature-named worktrees (`.canopy/worktrees/<feature>/<repo>/`) to the slot model (`.canopy/worktrees/worktree-N/<repo>/`). Renames dirs, rewrites canopy.toml (`max_worktrees` → `slots`), migrates `active_feature.json` → `slots.json`. Dry-run preflight; refuses on dirty trees. Idempotent — refuses to re-run once `slots.json` exists. |

## Register & orient

| Command | What it does |
|---|---|
| ⚡ `canopy context [--remote]` **(agent tool)** | The registry read — one call for the workspace map: feature ↔ repo ↔ branch ↔ path ↔ slot state ↔ advisories. **Tier 1** (default): local + instant, no network. **Tier 2** (`--remote`): adds a live PR + CI + origin-divergence overlay per repo. Intent rule: local code/feature work → `context`; addressing PR comments, checking CI, or review → `context --remote`. Surfaces `unregistered_join_candidate` advisories — repos on the active feature's branch that were never `canopy join`-ed. Powers `preflight`'s context detection and the SessionStart brief. |
| ⚡ `canopy start <alias>` **(agent tool)** | Begin new work: resolves the issue provider best-effort (Linear ID, GitHub issue, etc.) and creates the feature lazily — zero repos until you `join`. Marks the feature active in `.canopy/state/active.json`. |
| ⚡ `canopy join <repo>` **(agent tool)** | The lazy-growth primitive: creates the active feature's branch in `<repo>`, registers the repo on the feature lane, and promotes the feature to canonical so the enforcement gate and `context` recognize it. A raw `git checkout -b` does not register — `context` will advise `join` for unregistered branches. |

## Discover

| Command | What it does |
|---|---|
| `canopy triage [--author @me]` | Prioritized list of features needing attention. Groups open PRs across repos by feature, sorts by review state (`changes_requested` > `review_required_with_bot_comments` > `review_required` > `approved`). Use this every morning. |
| `canopy state <feature>` | The 9-state machine for one feature, plus the suggested `next_actions`. Same JSON the dashboard renders. |
| ⚡ `canopy drift [<feature>]` **(agent tool)** | Per-feature alignment from `.canopy/state/heads.json` (the post-checkout hook's data). Fast, hook-driven — doesn't touch git directly. |
| `canopy conflicts [--feature <f>] [--with <other>] [--include-cold] [--lines]` | Cross-feature file-overlap detection — which active features touch the same files. `--feature` / `--with` scope to specific pairs; `--include-cold` also scans cold features; `--lines` computes line-range overlap (slower, downgrades to `medium` when files overlap but lines don't). |
| `canopy list` | Compact feature overview — names, Linear links, per-repo branch/dirty/ahead-behind. |
| `canopy status` | Per-repo branch + dirty + divergence from default branch. |
| `canopy feature list` | Same as `list` (legacy spelling). |
| `canopy feature status <name>` | Detailed per-repo state + merge-readiness check. |
| `canopy worktree` | Live worktree dashboard — branch, dirty state, ahead/behind per linked worktree. |
| `canopy slots [--rich]` | Slot occupancy snapshot — what's in canonical and each warm slot, plus the `last_touched` LRU. `--rich` (implied by `--json`) enriches each slot with branch, dirty, ahead/behind, PR + CI rollup, unresolved bot threads, linear link, and computed `feature_state` per repo — the same payload the dashboard renders. |
| `canopy log [--feature <f>]` | Interleaved chronological log across repos. |

## Read

Read primitives — alias-aware fetches against Linear and GitHub, plus review classification. Use these instead of shelling `gh api` or `gh pr view`.

| Command | What it does |
|---|---|
| `canopy issue <alias>` | Linear/GitHub issue by ID (`SIN-412`) or feature alias (lookup via lane's `linear_issue`). |
| `canopy issues [--limit N]` | List the current user's open issues from the workspace provider (default 25). |
| `canopy pr <alias>` | PR data per repo. Alias forms: feature, `<repo>#<n>`, PR URL. |
| `canopy pr-checks <alias>` | CI check rollup for a PR alias — per-repo check runs + aggregate status. |
| `canopy branch info <alias>` | Branch HEAD, upstream, ahead/behind per repo. Alias forms: feature, `<repo>:<branch>`. |
| `canopy comments <alias>` | Temporally classified PR review comments — `actionable_threads` vs `likely_resolved_threads` vs resolved count. Alias: feature, `<repo>#<n>`, PR URL. |
| `canopy draft-replies <alias> [--include-likely-resolved]` | Auto-draft replies for PR review comments the diff shows you already addressed. `--include-likely-resolved` also drafts for the temporal classifier's low-confidence `likely_resolved` set. |
| `canopy review <feature>` | Combined: PR status + unresolved comments + pre-commit checks. Older composite — prefer `state` + `comments` separately. |
| `canopy bot-status [--feature <f>] [--unresolved-only]` | Per-feature rollup of bot review comments — total / resolved / unresolved per repo + an `all_resolved` flag. Bot vs human classification respects `[augments] review_bots` in canopy.toml. |
| `canopy historian show [<feature>]` | Print the rendered memory file for a feature (3 sections: resolutions log, PR context, sessions). Empty when no memory recorded yet. |
| `canopy historian compact [<feature>] [--keep-sessions N]` | Trim the Sessions section to the most-recent N (default 5). Resolutions log + PR context preserved regardless. v1 is mechanical (no LLM). |
| `canopy feature diff <name>` | Aggregate diff vs default branch + cross-repo type overlap detection. |
| `canopy feature changes <name>` | Per-file change summary across the feature lane. |

## Focus & slots

| Command | What it does |
|---|---|
| ⚡ `canopy switch <feature> [--release-current] [--no-evict] [--evict <f>] [--evict-to <slot-N>] [--to-slot <slot-N>]` **(agent tool)** | The RUN-target focus primitive. Promote a feature to the canonical slot — reserved for when you actually need to run it full-stack; addressing review comments happens **in the worktree**, no switch (see [concepts.md §4](concepts.md#4-the-slot-model)). Validates every in-scope repo before mutating any (no partial flips). Default: the previously-canonical feature goes **warm** iff it has an open PR or live/uncommitted WIP, else **cold** with a feature-tagged stash. `--release-current` forces cold. `--no-evict` refuses to auto-evict an LRU warm slot if the cap would fire. `--evict <f>` / `--evict-to <slot-N>` override which feature/slot is affected. `--to-slot <slot-N>` promotes whatever feature already occupies that slot (omit `<feature>`). Cap-reached (`worktree_cap_reached`) surfaces three explicit fix actions — raise the cap, send the vacating feature cold, or evict a specific warm PR — never a silent auto-evict. |
| ⚡ `canopy reclaim` **(agent tool)** | Free every warm slot whose feature's PR(s) are all merged/closed AND whose worktree is clean: checks out the repo's default branch in the slot and drops the `slots.json` entry, returning the slot to the pool (dir + installed deps persist for the next tenant). A merged-but-dirty slot is left untouched and reported as an advisory. Also runs passively inside `canopy context --remote`. |
| `canopy slot load <feature> [<slot-N>] [--replace] [--bootstrap]` | Warm a cold feature into a slot **without** changing canonical. `<slot-N>` defaults to the lowest free slot. `--replace` evicts the slot's current occupant to cold first. `--bootstrap` runs env-file copy + `install_cmd` + IDE workspace gen (same as `worktree-bootstrap`). The feature must already be registered (`canopy feature create` first). |
| `canopy slot clear <slot-N>` | Evict that slot's occupant to cold with a feature-tagged stash if dirty. The slot id stays — only the occupant moves. |
| `canopy slot swap <slot-A> <slot-B>` | Exchange the features in two warm slots. v1 requires identical repo scope on both features (mismatched-scope swap raises `BlockerError(code='swap_scope_mismatch')`). |

## Work

Write actions and execution.

| Command | What it does |
|---|---|
| ⚡ `canopy run <repo> <command> [--feature <f>] [--timeout N]` **(agent tool)** | Run a shell command in a canopy-managed repo with cwd resolved internally. The "never `cd`" tool — also useful from a CLI in a deeply nested directory. `--timeout` kills the process after N seconds (default 60). |
| `canopy checkout <branch>` | Plain checkout across all repos — no feature context, no per-repo branch resolution. Use `switch` for feature-scoped focus changes. |
| `canopy code\|cursor\|fork <feature\|.>` | Open the feature in VS Code / Cursor / Fork.app (alias-aware; generates `.code-workspace` for the IDE ones). |
| `canopy sync` | Pull default branch + rebase feature branches across repos. |
| ⚡ `canopy commit -m <msg> [--feature <f>] [--repo <r,...>] [--paths <p ...>] [--no-hooks] [--amend]` **(agent tool)** | Commit across every repo in the canonical (or named) feature with a single message. Pre-flight refuses with `BlockerError(code='wrong_branch')` if any in-scope repo has drifted; per-repo hook failures don't cancel the others (status: `hooks_failed`). `--paths` filters staging; `--no-hooks` passes `--no-verify`; `--amend` amends HEAD instead of creating new commits. (4.0: commit is commit-only — the pre-4.0 `--address` / `--resolve-thread` bot-comment plumbing was removed; classify and resolve threads with `canopy comments` / `canopy resolve` / `canopy reply` instead.) |
| ⚡ `canopy push [--feature <f>] [--repo <r,...>] [--set-upstream] [--force-with-lease] [--dry-run]` **(agent tool)** | Push the feature branch in every in-scope repo. Pre-flight raises `BlockerError(code='no_upstream')` if any repo lacks an upstream and `--set-upstream` was not passed; the fix-action carries the same args + `--set-upstream` so an agent retries mechanically. `--force-with-lease` allows safe non-fast-forward pushes. Per-repo statuses: `ok`, `up_to_date`, `rejected`, `failed`. |
| `canopy ship [--feature <f>] [--repo <r,...>] [--draft] [--reviewers <h,...>] [--base <branch>] [--dry-run]` | Open or update one PR per repo in the canonical (or named) feature, with cross-repo body links. `--draft` opens as drafts (initial open only); `--reviewers` requests review from GitHub handles; `--base` overrides the base branch (default: each repo's `default_branch`); `--dry-run` enumerates without pushing or opening PRs. |

## Verify

| Command | What it does |
|---|---|
| ⚡ `canopy preflight [<feature>]` **(agent tool)** | Run per-repo pre-commit checks. With `<feature>`, runs against the feature lane and records the result to `.canopy/state/preflight.json` (which feeds `canopy state`'s `ready_to_commit` detection). Without `<feature>`, runs against the current cwd's context. **Use as a dry-run before `canopy commit`** — preflight stages and runs hooks but never commits. |

## Review threads

| Command | What it does |
|---|---|
| `canopy resolve <thread_id> [--feature <f>]` | Resolve a GitHub PR review thread via GraphQL + record the closure in `.canopy/state/thread_resolutions.json`. `--feature` pins which feature the resolution is attributed to (defaults to the canonical feature). |
| `canopy reply <thread_id> [--body <text> \| --body-file <path> \| stdin] [--resolve] [--feature <f>]` | Post a reply to a GitHub review thread. Body comes from `--body`, `--body-file`, or stdin (pipe-friendly). `--resolve` closes the thread after posting and logs the closure. |

## Resume

| Command | What it does |
|---|---|
| `canopy resume <alias> [--reset-anchor]` | Session-start primitive: switch-aware compound action — alias → switch-if-needed → refresh GitHub + Linear → compute structured brief → bump last-visit anchor. Returns `{feature, switch_performed, first_visit, window_hours, since_last_visit, current_state, next_actions, intent_hints}`. `--reset-anchor` clears `last_visit` so the next call is treated as a first visit (fresh delta window). See [concepts.md §5](concepts.md#5-returning-to-a-feature--the-resume-brief). (Human/CLI tool — the agent orients via `context` at session start.) |

## Stash (feature-aware)

| Command | What it does |
|---|---|
| `canopy stash save -m <msg> [--feature <f>]` | Stash dirty changes (incl. untracked when `--feature` is used). Tagged stash messages: `[canopy <feature> @ <ts>] <msg>`. ⚡ **`stash save --feature` is the agent tool `stash_save_feature`.** |
| `canopy stash list [--feature <f>]` | Stashes across repos. With `--feature`, groups by feature tag. Without, flat list per repo. |
| `canopy stash pop [--feature <f>] [<index>]` | Pop. With `--feature`, pops the most recent matching tagged stash per repo. ⚡ **`stash pop --feature` is the agent tool `stash_pop_feature`.** |
| `canopy stash drop [<index>]` | Drop a stash by index. |

## Worktree

| Command | What it does |
|---|---|
| `canopy worktree <name> [issue]` | Create linked worktrees for a feature in every repo, optionally linking an issue. Worktrees go to `.canopy/worktrees/worktree-N/<repo>/` (generic numbered slot, allocated as the lowest free slot). Slot creation auto-bootstraps — env-file copy, IDE workspace gen, and per-clone hook install run synchronously so the worktree is immediately usable; `install_cmd` runs detached in the background with status (`installing`/`ready`/`failed`) surfaced in `canopy context`. |
| ⚡ `canopy worktree-bootstrap <feature> [--force] [--step env\|deps\|ide] [--deps] [--interactive]` **(agent tool)** | Bootstrap a feature's worktrees by hand: env-file copy, `install_cmd`, IDE workspace gen, and the per-clone hook step. `--step` restricts to one step; `--deps` runs deps only (retry a `failed`/`installing` slot, or the target of the background install `context` points at); `--interactive` runs the deps install in the foreground to stream output / handle prompts; `--force` overwrites existing env files and bypasses the lockfile-unchanged short-circuit. |
| `canopy worktree` | Live dashboard (read-only, see "Discover"). |

## Branch

| Command | What it does |
|---|---|
| `canopy branch list` | Branches per repo. |
| `canopy branch delete <name> [--force]` | Delete across repos. |
| `canopy branch rename <old> <new>` | Rename across repos. |
| `canopy branch info <alias>` | Branch state per repo (alias-aware; see "Read"). |

## Cleanup

| Command | What it does |
|---|---|
| `canopy feature create <name> [...]` | Create a feature lane (register a feature without any repos or worktrees yet — the low-level primitive `start` wraps for provider-aware creation). |
| `canopy done <feature> [--force]` | Clean up a completed feature — remove worktrees, delete branches (if merged), archive lane in `features.json`. `--force` overrides the dirty-tree refusal. |

## Recover

| Command | What it does |
|---|---|
| ⚡ `canopy doctor [-v] [--feature <f>]` **(agent tool)** | Diagnose **21 codes across 11 categories** of state-file drift + install staleness (incl. slot-state and orphan-process checks). Reports `errors`/`warnings`/`info` with structured `code`, `expected`, `actual`, and per-issue `fix_action`. **Run this first** when any other canopy operation returns an unexpected error. `--json` returns the full report shape `{issues, summary, fixed, skipped}`. |
| `canopy doctor --fix` | Repair every `auto_fixable=true` issue. Examples: rewrite `heads.json` from live git, drop orphan worktree dirs via `git worktree remove --force`, reinstall a missing post-checkout hook, clean up an orphan slot dir, reap orphaned `canopy-mcp` processes, write a missing `.mcp.json` entry, reinstall the `using-canopy` skill. |
| `canopy doctor --fix-category <c>` | Repair just one category. Accepts: `active_feature`, `branches`, `cli`, `features`, `heads`, `hooks`, `mcp`, `preflight`, `skill`, `worktrees` (implies `--fix`). The 11th category, `slots`, is intentionally not offered here — its fixes are manual (you decide which side is canonical). |
| `canopy --version` | ⚡ **(agent tool `version`)** Print the installed CLI version — the handshake `doctor`'s `cli_stale` / `mcp_stale` checks compare against. |

### Diagnostic codes

State-integrity (the workspace's own bookkeeping):

| Code | Category | Severity | Detection | Auto-fix |
|---|---|---|---|---|
| `heads_stale` | heads | warn | `heads.json` out of sync with `git rev-parse HEAD` | rewrite from live git |
| `active_feature_orphan` | active_feature | error | `active_feature.json` points at unknown feature | clear the file |
| `active_feature_path_missing` | active_feature | error | `per_repo_paths` reference non-existent dirs | re-resolve from `features.json` |
| `worktree_orphan` | worktrees | warn | `.canopy/worktrees/…` not referenced by any feature | `git worktree remove --force` |
| `worktree_missing` | worktrees | error | feature × repo `worktree_paths` entry has no dir on disk | drop the entry |
| `slot_dir_orphan` | slots | warn | `.canopy/worktrees/worktree-N/` exists with no entry in `slots.json` | drop the dir |
| `slot_entry_orphan` | slots | warn | `slots.json` references a slot whose dir is missing | drop the entry |
| `slot_repo_worktree_missing` | slots | error | slot holds feature F but one of F's repos has no worktree on disk | recreate the worktree from the feature's branch (else `branches_missing` owns it) |
| `slot_branch_mismatch` | slots | error | slot's repo HEAD ≠ recorded feature branch | manual (decide which is canonical: live HEAD or slots.json) |
| `slot_detached_head` | slots | info | slot's repo is on a detached HEAD (bisect / explicit `checkout <sha>`) | manual (informational — re-attach when done) |
| `hook_missing` | hooks | error | repo lacks canopy's post-checkout hook | reinstall (chains existing user hook) |
| `hook_chained_unsafe` | hooks | warn | chained user hook present but not executable | `chmod +x` |
| `preflight_stale` | preflight | info | recorded `head_sha_per_repo` no longer matches live HEAD | drop the entry |
| `features_unknown_repo` | features | error | `features.json` references repo not in `canopy.toml` | manual (restore the repo or `done` the feature) |
| `branches_missing` | branches | error | feature's recorded branch doesn't exist locally | manual (restore branch or `done` feature) |

Install-staleness (canopy's installation around the workspace):

| Code | Category | Severity | Detection | Auto-fix |
|---|---|---|---|---|
| `cli_stale` | cli | warn | `canopy --version` < running `__version__` | manual reinstall |
| `mcp_stale` | mcp | error | `canopy-mcp --version` < running `__version__` | manual reinstall |
| `mcp_missing_in_workspace` | mcp | error | `.mcp.json` lacks canopy entry, or its `CANOPY_ROOT` is wrong | `install_mcp(reinstall=True)` |
| `mcp_orphans` | mcp | info | orphaned `canopy-mcp` processes (PPID=1) left behind by disconnected editors/agents | reap (SIGTERM, then SIGKILL after 2s) |
| `skill_missing` | skill | warn | no `~/.claude/skills/using-canopy/SKILL.md` | `install_skill()` |
| `skill_stale` | skill | warn | installed skill drifted from bundled source | `install_skill(reinstall=True)` |

## Enforcement hooks

Claude Code hooks that stop the agent from mutating git state in the wrong place. Separate from the drift-tracking `canopy hooks install|uninstall|status` (post-checkout, feeds `heads.json`) described in "Setup".

| Command | What it does |
|---|---|
| `canopy setup-agent --hooks` | Installs (or refreshes) the enforcement hooks into `<workspace>/.claude/settings.json`: a `PreToolUse` entry (matcher `Bash`) running `canopy-hook-gate`, and a `SessionStart` entry running `canopy-hook-context`. **Project-scoped, not user-scoped** — the workspace root is normally not itself a git repo, so nothing lands in `~/.claude/settings.json` or any employer repo's tree. Merges into existing `settings.json` (other keys preserved untouched); re-running is a no-op (`action: "unchanged"`) once both entries are present. Invalid-JSON `settings.json` → install skipped with a `reason` rather than clobbering it. Combine with the other `setup-agent` flags as usual. |

`canopy-hook-gate` and `canopy-hook-context` are internal console scripts (registered in `pyproject.toml`, not meant to be run by hand) that Claude Code invokes per the `settings.json` entries above:

- **`canopy-hook-gate`** (PreToolUse, matcher `Bash`) — reads the tool-call payload as JSON on stdin (`{tool_name, tool_input: {command}, cwd, ...}`). For non-`Bash` calls or commands with no `git` token, exits 0 immediately without touching disk. Otherwise it resolves the workspace from `cwd`, splits the command on top-level shell operators, tracks the effective directory through `cd` chains and `git -C`, and judges only the mutating git subcommands (`commit`, `push`, `merge`, `rebase`, `reset`, `cherry-pick`, `add`, `rm`, `mv`, `am`, `revert`, mutating `stash` verbs). **Exit 0** = allow (nothing printed). **Exit 2** = block, with a one-line reason on stderr that Claude Code feeds back to the model.
- **`canopy-hook-context`** (SessionStart) — reads the same payload shape, resolves the workspace from `cwd`, and prints a compact brief to stdout (becomes session context): workspace name, canonical feature, each repo's branch + dirty count, each warm slot's occupant, and a one-line reminder to `canopy switch` before working if the ticket doesn't match. Always exits 0; on any error it prints nothing.

Deny codes (all four block with an explanatory message that also names the fix):

| Code | Meaning | Fix the message names |
|---|---|---|
| `outside_repo` | The mutation's effective directory (after resolving `cd`/`git -C`) isn't inside any workspace repo or slot worktree. | `cd <repo> && git ...`, or use `canopy run`. |
| `trunk_branch_drift` | On **commit/push only**: a canonical-slot repo is on a branch owned by a different registered feature than the current canonical one. | `canopy switch <feature>` (either the branch's owner, or back to canonical). |
| `slot_branch_drift` | On **commit/push only**: a warm-slot repo is on a branch that doesn't match the slot's recorded occupant feature. | `git checkout <expected-branch>` in that worktree, or `canopy doctor`. |
| `push_unknown_branch` | `git push`'s source refspec names a branch that doesn't exist in the effective repo (but does exist in a different one). | Check the branch for *this* repo with `git branch --list` or `canopy context`; likely the wrong repo. |

**Fail-open contract.** The gate only blocks when it's sure the mutation targets the wrong place. It allows (exit 0) on: unparseable shell segments, unresolvable `cd` targets (`$VAR`, `~`, backticks, `cd -`), a `cwd` with no `canopy.toml` above it, non-`Bash` tool calls, commands with no `git` token, and any internal exception — `run_gate` never raises. `checkout`/`switch` are deliberately never gated: they're the recovery action for a drifted branch.

**Escape hatch:** set `CANOPY_HOOKS_DISABLED=1` to make the gate a no-op (checked first, before any parsing).

**Known bypasses** (deliberate fail-open — documented so nobody relies on the gate as a security boundary): env-prefix invocations (`GIT_TRACE=1 git push`, `env git push`); non-literal git (`/usr/bin/git`, `command git`, `sh -c "git push"`, `xargs git push`); subshells/loops/brace-groups (`(cd x && git push)`); unresolvable directories (`cd $DIR`, `git -C "$dir"`, `--git-dir`/`--work-tree` overrides); shlex-unparseable segments; and sessions whose `cwd` is outside the workspace entirely.

## Common patterns

Session start — returning to a feature:

```bash
canopy resume <feature>    # switch-if-needed + fresh brief + bump last-visit anchor
# brief shows: window_hours, since_last_visit counts, current_state, intent_hints
canopy reply <thread_id> --body "Done — fixed in abc123." --resolve  # close a thread
canopy resolve <thread_id>  # close a thread without replying
```

The daily loop:

```bash
canopy triage              # what to work on
canopy state <feature>     # get oriented + see next_actions
canopy switch <feature>    # promote to canonical (only when you need to RUN it)
canopy comments <feature>  # actionable threads only
# ... edit code ...
canopy preflight           # stage + run hooks (dry-run; no commit)
canopy commit -m "..."     # commit across the canonical feature
canopy push                # publish (add --set-upstream on first push)
canopy ship                # open/update one PR per repo
canopy state <feature>     # confirm transition
```

Switching focus mid-flight (slot model):

```bash
# Active rotation: previous focus evacuates into a warm slot, instant to switch back
canopy switch other-feature
canopy switch current-feature   # the warm slot's occupant promotes back to canonical

# Wind-down: previous focus goes cold (feature-tagged stash if dirty)
canopy switch new-feature --release-current

# Inspect slot occupancy + per-slot PR/CI/bots
canopy slots --rich

# Pre-warm a cold feature into a slot without changing canonical
canopy slot load other-feature            # picks lowest free slot
canopy slot load other-feature worktree-2 # pin slot 2

# Free a slot without bringing a new feature in
canopy slot clear worktree-2

# Reclaim slots whose PR merged
canopy reclaim
```

Investigate without changing state:

```bash
canopy state <feature> --json | jq .summary
canopy comments <feature> --json | jq '.repos[].actionable_threads'
canopy conflicts --feature <feature> --json
canopy branch info <feature>
canopy pr <feature>
```
