# Wave 2.3 — `commit` + `push` as canonical-feature primitives

## Mental model

After Wave 2.9, the **canonical feature** is "what's checked out in main and what the user is focused on." Every CLI / MCP operation has a sensible default: when the user says `canopy commit -m "fix"`, they mean "commit across all repos in the canonical feature, scoped to its branches." Same for push.

`commit` and `push` are the two primitives that were queued in Wave 2.3 but never landed. They're orthogonal to switch — commit doesn't change branches, push doesn't change branches — but they read from the same canonical-slot model so they don't need explicit `--feature` arguments.

The mental model is a parallel rebase of `git`:

| Single-repo git | Canopy multi-repo |
|---|---|
| `git commit -am "msg"` | `canopy commit -m "msg"` (all repos in canonical feature, all dirty + tracked) |
| `git commit -m "msg" -- path/foo` | `canopy commit -m "msg" --repo foo --paths src/x.py` (filter to one repo, optional path scope) |
| `git push` | `canopy push` (all repos in canonical feature, current branch each) |
| `git push -u origin HEAD` | `canopy push --set-upstream` (first push for the feature branch) |

**Implicit feature scope.** No `--feature` argument by default. Read `active_feature.json` → use that. Explicit `--feature X` overrides for non-canonical features (rare).

**Multi-repo atomicity.** Per-repo failure rolls back nothing — git commits are local; they're already "atomic per repo." The user gets a structured per-repo result. If 2 of 3 repos commit and 1 fails on hooks, they see exactly that.

---

## Behavioral spec

### `commit`

`canopy commit -m <msg> [--feature X] [--repo R ...] [--paths P ...] [--no-hooks] [--amend]`

| Pre-condition (per repo in scope) | Behavior |
|---|---|
| Repo is on the feature's expected branch (per `lane.branches`) | Stage `--paths` if given, else `git add -u` (all tracked changes); run pre-commit hooks; `git commit -m <msg>`. Returns `{repo, status: "ok", sha, files_changed}`. |
| Repo is on a different branch than expected | `BlockerError(code='wrong_branch', expected: <feature-branch>, actual: <current-branch>, fix_actions: [switch(feature) or commit(--feature=<actual-feature>)])`. |
| Repo has nothing to commit | `{repo, status: "nothing", reason: "no changes"}`. Not a failure. |
| Pre-commit hook failed (and `--no-hooks` not passed) | `{repo, status: "hooks_failed", hook_output: <tail>}`. Stops here for this repo; other repos continue. |
| Repo is in a worktree (warm feature) | Same logic; commit happens in the worktree dir. |
| `--amend` and HEAD has nothing to amend (e.g. just-cloned) | Reject with `BlockerError(code='nothing_to_amend')`. |

**Returns:** `{ feature, results: { <repo>: {status, sha?, files_changed?, reason?, hook_output?} } }`. Same shape as existing `sync` result.

### `push`

`canopy push [--feature X] [--repo R ...] [--set-upstream] [--force-with-lease] [--dry-run]`

| Pre-condition (per repo in scope) | Behavior |
|---|---|
| Branch has upstream + nothing to push | `{repo, status: "up_to_date"}` |
| Branch has upstream + commits to push | `git push` → `{repo, status: "ok", pushed_count: N, ref: "origin/<branch>"}` |
| Branch has no upstream + `--set-upstream` passed | `git push --set-upstream origin <branch>` → `{repo, status: "ok", set_upstream: true}` |
| Branch has no upstream + `--set-upstream` NOT passed | `BlockerError(code='no_upstream', repo, branch, fix_action: 'push --set-upstream')`. The fix-action carries the exact same args + `--set-upstream` so the agent can retry mechanically. |
| Push rejected (non-fast-forward, no `--force-with-lease`) | `{repo, status: "rejected", reason: <git stderr tail>}`. Don't auto-force. |
| Push rejected, `--force-with-lease` passed | `git push --force-with-lease` |

`--dry-run` enumerates what *would* happen per repo without executing.

**Returns:** `{ feature, results: { <repo>: {status, pushed_count?, ref?, reason?, set_upstream?} } }`.

---

## State model changes

None. Both operations are read-only against `features.json` / `active_feature.json` and write only to git. They don't update any canopy state files.

---

## Command surface changes

| Today | After Wave 2.3 |
|---|---|
| `canopy commit` (does not exist) | New CLI command + MCP tool. |
| `canopy push` (does not exist) | New CLI command + MCP tool. |
| `canopy preflight` | Unchanged. Preflight stages + runs hooks but never commits — used as a dry-run before `commit`. |
| `canopy sync` | Unchanged. Sync rebases against default branch; commit/push are orthogonal. |

---

## Files to touch

### New

- `src/canopy/actions/commit.py` — orchestrator. Resolves canonical/explicit feature → list of (repo, branch, worktree_path) → fan out per-repo `_commit_one(repo, branch, ...)`.
- `src/canopy/actions/push.py` — orchestrator. Same shape.
- `tests/test_commit.py` — table-driven cases per row of the commit pre-condition matrix above.
- `tests/test_push.py` — table-driven cases per row of the push matrix above.

### Modified

- `src/canopy/git/repo.py` — add `commit(repo_path, message, paths=None, amend=False, no_hooks=False)` and `push(repo_path, set_upstream=False, force_with_lease=False, dry_run=False)`. These are the only modules calling `subprocess.run(["git", ...])` per project convention; orchestrators MUST go through here.
- `src/canopy/cli/main.py` — `cmd_commit(args)`, `cmd_push(args)`. Dispatch in `commands` dict. Add subparsers (mirror existing patterns from `cmd_sync`).
- `src/canopy/mcp/server.py` — register `@mcp.tool()` wrappers for both: `commit(message, feature=None, repos=None, paths=None, no_hooks=False, amend=False)` and `push(feature=None, repos=None, set_upstream=False, force_with_lease=False, dry_run=False)`.
- `docs/commands.md` — add `commit` + `push` sections.
- `docs/agents.md` — add commit/push to "Common multi-repo operations".
- `~/.claude/skills/using-canopy/SKILL.md` and `src/canopy/agent_setup/skill.md` — flag both as canonical-aware. The agent should use them in preference to `canopy run -- git commit/push`.

---

## Tasks (rough sequence)

### T1 — `git/repo.py` primitives

Implement `commit()` and `push()` as thin wrappers around `subprocess.run` that return structured result dicts (sha, files_changed, pushed_count, etc.) and surface stderr on failure. Hooks run by default; `--no-verify` only when `no_hooks=True`. **Never** pass `--no-gpg-sign` or skip signing — leave sign behavior to the user's git config.

Tests in `tests/test_repo.py` (existing file): cover happy path + nothing-to-commit + hook failure + no-upstream + force-with-lease.

### T2 — `actions/commit.py` orchestrator

Resolve feature scope (canonical via `active_feature.json` if no `--feature` else explicit). Resolve per-repo paths via the existing `lane.repos` + worktree-aware path resolution (same logic `feature_state` uses — see `actions/feature_state.py`). Fan out per-repo with `concurrent.futures.ThreadPoolExecutor` (existing parallelism pattern from `actions/switch.py`). Aggregate into the structured return.

`BlockerError(code='wrong_branch', ...)` raised before any per-repo work fires if any repo's current branch doesn't match `lane.branches[repo]`.

Tests: workspace_with_feature fixture + variants for each pre-condition row.

### T3 — `actions/push.py` orchestrator

Same shape as commit. The interesting cases are no-upstream (returns BlockerError with the exact retry args) and rejected (don't auto-force). `--dry-run` populates the structured return without firing pushes.

Tests: same fixture + variants per row.

### T4 — CLI + MCP wrappers

Thin wrappers over the actions. CLI prints a per-repo summary table on stdout; `--json` returns the structured dict. MCP tool returns `result.to_dict()` directly.

### T5 — Docs + skill updates

`docs/commands.md` gets two sections with example invocations. `docs/agents.md` adds a "Commit / push from the agent" section. Both skills (user-installed + bundled) get the new tools listed in the "preferred over" table.

### T6 — Composition test

Integration test: workspace_with_feature → modify file in both repos → `canopy commit -m "test"` → assert commits present in both → `canopy push --set-upstream` → assert upstream set. Uses real temp git repos (existing `tests/conftest.py` fixture pattern).

---

## Edge cases to remember

- **Pre-commit hooks that modify files.** If a hook re-formats the staged file, the commit may include unexpected diffs. Document this; don't try to detect / re-stage. Match git's native behavior.
- **Detached HEAD.** Treat as `wrong_branch` with `expected: <feature-branch>, actual: 'HEAD detached at <sha>'`. Fix action: checkout the feature branch.
- **Empty message.** Reject at CLI parse (argparse) before calling action.
- **Feature with worktree per repo.** Resolve via `lane.repo_states[repo].worktree_path` (when warm) or `lane.repo_states[repo].abs_path` (when canonical). The same path-resolution helper used by `feature_state` and `feature_diff` should be factored out if not already.
- **Commit signing.** If user has `commit.gpgsign=true` and gpg is broken, commit fails with the gpg error in stderr. Surface verbatim — don't try to disable signing.

---

## Out of scope

- `commit --interactive` / patch-mode staging. Use raw `git -C <repo> add -p` for that.
- Per-repo commit messages. One message, all repos. Cross-repo coupling is the point.
- Squash / rebase / interactive history rewriting. Use `git` directly for those.
- Automatic conflict resolution on push reject. User runs `canopy sync` (rebase) then re-pushes.

---

## After this lands

- The action drawer's "Commit + push" button can be wired to call `commit` then `push` in sequence (or as a composite — see Wave 2.4 plan).
- The CLI workflow becomes: `canopy preflight` → review hooks output → `canopy commit -m "msg"` → `canopy push`. Three commands; no `--feature` needed when the canonical slot is set.
- The dashboard's "Run preflight" button retains its current role (stage + run hooks, no commit). Adding "Commit + push" as a sibling action makes the workflow complete inside one panel.
