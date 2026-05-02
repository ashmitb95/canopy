# Test Run — 2026-05-02 (canopy 0.5.0 against canopy-test)

First end-to-end pass against [`docs/test-plan.md`](test-plan.md). Workspace: `~/projects/canopy-test` (test-api + test-ui, GitHub-backed, Linear MCP wired, 8 features in `features.json`).

**Environment:** canopy 0.5.0 (editable install in `~/projects/canopy/.venv/`), Python 3.14, gh authenticated, Linear MCP token cached at `~/.canopy/mcp-tokens/linear.tokens.json` (last refreshed 2026-04-27).

**Status legend:** ✅ pass · ⚠️ pass with finding · ❌ fail · ⏭️ skipped/blocked · 🟨 in-progress

---

## Section results

| Section | Result | Notes |
|---|---|---|
| §0 Preconditions (5) | ✅ 5/5 | Found pre-existing `__version__` drift (`0.1.0` though M0–M5 shipped) — fixed pre-test in [PR #16](https://github.com/ashmitb95/canopy/pull/16). |
| §1 Doctor (5) | ⚠️ 5/5 with 2 findings | Doctor surfaces 8 real workspace issues (all `auto_fixable: true`); 2 minor CLI bugs noted (F-1, F-2). |
| §2a Linear provider | ⚠️ partial | CLI `canopy issue SIN-5` works but exposes raw Linear state ("Todo") instead of canonical ("todo"). MCP `issue_get` correct. F-5 (no plural CLI). F-4 (headless OAuth). |
| §2b GitHub Issues provider | ❌ CLI broken | MCP `issue_get` works perfectly with provider-swapped config. CLI `canopy issue 5` / `#5` / `owner/repo#5` all fail with `unknown_alias` — alias resolver is Linear-only. **F-7 is the headline bug.** |
| §3 Augments (6) | ✅ 6/6 with F-9 | Workspace `preflight_cmd`, per-repo override (per-repo wins), failing-augment graceful, augment-canopy skill installs. F-9: `--check` only reports default skill. |
| §4 Bot tracking | ⏭️ blocked | Needs CodeRabbit set up on `ashmitb95/canopy-test-api` PRs — external setup. Throwaway issues #5/#6 used + closed. |
| §5 Historian (11) | ✅ 9/11; 2 blocked | switch ↔ memory round-trip works; decision dedup works; pause + render work; `.gitignore` auto-written; compact noop + drop both work. §5.7 (commit --address auto-mirror) + §5.8 (review_comments auto-mirror) blocked behind §4. |

---

## Findings

### F-0: `__version__` drift (FIXED pre-test)

`src/canopy/__init__.py` was stuck at `"0.1.0"` despite M0–M5 shipping. The doctor's `cli_stale` / `mcp_stale` checks compare against this constant — they were silently a no-op for ~6 months of work.

- **Fix:** [PR #16](https://github.com/ashmitb95/canopy/pull/16) — bumped to `0.5.0`, added `CHANGELOG.md`, added a CLAUDE.md guard.
- **Lesson:** version bump should happen in the same PR as the milestone it represents. Going forward, the CLAUDE.md note covers it.

### F-1: "no canopy.toml found" error is unhelpful

Running any workspace-scoped command (e.g. `canopy setup-agent --check`, `canopy state`, `canopy preflight`) from outside a workspace prints `Error: No canopy.toml found in current directory or any parent.` That's technically true, but doesn't tell a new user *what* a workspace is or *why* canopy can't proceed.

- **Repro:** `cd / && canopy setup-agent --check` → terse "No canopy.toml found" error.
- **Decision (per user):** **don't gracefully degrade** (e.g. partial setup-agent reports without MCP). Fail loud and clear with an error message that explains canopy's mental model:
  > Canopy needs to be run from a **canopy workspace** — a non-git directory that contains `canopy.toml` plus the participating repos as subdirectories. Run `canopy init` in such a directory to create one.
- **Severity:** low individually; medium for new-user friction (this is the first error a fresh install hits).
- **Fix:** centralize the "no canopy.toml" error rendering in one place (`cli/render.py` or a small helper in `cli/main.py`) so every command that depends on a workspace prints the same, helpful message — and exits non-zero (see F-2).

### F-2: error path returns exit code 0 ~~(INVALID — measurement error)~~

**Retracted.** Re-verified after the test run: `canopy setup-agent --check` exits 1, and `canopy issue <unresolvable> --json` (BlockerError JSON output) also exits 1. My original `echo $?` was capturing a later step in the bash chain, not the canopy command. Exit codes are already correct.

Lesson for future test runs: capture exit codes inline (`canopy ... ; EC=$?`), not after intervening commands.

### F-3: stale `canopy-mcp` processes accumulate ~~(partially misread)~~

Original observation was 8+ canopy-mcp processes in `ps`. **On closer inspection most are not orphans** — their PPIDs are still alive (live VSCode / Cursor / Claude Desktop windows, each with its own canopy-mcp). One MCP per editor window is normal. The genuine bug is the *true* orphan case: an editor crashes hard, its MCP child gets reparented to PID 1, and nothing reaps it.

- **Fix shipped:** `mcp_orphans` doctor check (severity: info, auto-fixable). Detects PPID=1 canopy-mcp processes, reaps with SIGTERM then SIGKILL after a 2s grace. The check explicitly skips multi-editor-window cases (parent alive → not an orphan, doesn't fire).
- **Lesson for future test runs:** "lots of processes" ≠ "orphans". Check PPID before claiming a bug.

### F-4: Linear MCP from a headless Python invocation hangs

Running `python -c "from canopy.mcp.server import issue_list_my_issues; issue_list_my_issues()"` from a script never returned. Likely the OAuth flow attempts a browser open + waits for the redirect, with no terminal.

- **Severity:** low for users (the MCP client is meant to be invoked through Claude Code / canopy CLI, both of which have stdio); medium for testing (we can't headlessly assert the MCP path works against live Linear).
- **Workaround:** for tests, exercise the `LinearProvider` class directly with mocked `call_tool` (already done in the unit suite).

### F-6: CLI `canopy issue` exposes raw provider state, MCP returns canonical

`linear_get_issue` in `actions/reads.py` (the legacy wrapper backing `cmd_issue`) intentionally exposes `raw.state` for "backward compatibility." Concretely:

| Surface | `state` for SIN-5 |
|---|---|
| `canopy issue SIN-5 --json` | `"Todo"` (raw Linear) |
| `mcp__canopy__issue_get(alias="SIN-5")` | `"todo"` (canonical M5 mapping) |

Same workspace, same issue, two different responses depending on which surface you call. Also: CLI shape is `{alias, issue_id, title, state, url, description, raw}`; MCP shape is `{id, identifier, title, description, state, url, assignee, labels, priority, raw}`. Different fields entirely.

- **Severity:** medium — back-compat reasoning is dated (no current callers actually depend on raw state); the inconsistency is a footgun for anyone scripting against the CLI vs the agent talking via MCP.
- **Fix:** retire the legacy shape; have `cmd_issue` render `Issue.to_dict()` directly (matching the MCP tool). Update `docs/commands.md` accordingly.

### F-7: alias resolver is Linear-only — `canopy issue` broken for GitHub Issues provider

With `[issue_provider] name = "github_issues"` set in canopy.toml and a real GH issue (#5) on the configured repo, **none of these CLI invocations work:**

```
canopy issue 5                                  → BlockerError unknown_alias
canopy issue '#5'                               → BlockerError unknown_alias
canopy issue 'ashmitb95/canopy-test-api#5'      → BlockerError unknown_alias
```

The MCP equivalent (`mcp__canopy__issue_get(alias="5")`) returns the issue correctly — the `GitHubIssuesProvider` itself works. The bug is in `actions/aliases.py:resolve_linear_id`, which is hardcoded to look for Linear-shaped IDs (`SIN-N`) or feature-lane names. It doesn't know that for `github_issues`, a bare number is the canonical id form.

This is a **major M5 integration gap**: M5 added the Provider Protocol + registry, but the alias resolution layer above it is still Linear-shaped. The CLI surface for any non-Linear provider is dead.

- **Severity:** high — `canopy issue` is the primary user surface for the issue provider abstraction; it doesn't work for the second backend M5 was supposed to ship.
- **Workaround:** call MCP tool directly (works in agent contexts; not for CLI users).
- **Fix:** rewrite `resolve_linear_id` (rename to `resolve_issue_id`) to consult the active provider for what shapes it accepts. GitHub Issues: bare number, `#N`, `owner/repo#N`, full URL. Linear: `<TEAM>-<N>`, feature names. Provider can expose a `parse_alias(s) -> str | None` method (returns canonical id if accepted, else None); resolver tries provider first, falls back to feature-name lookup.
- **Adjacent:** Phil's branch has `actions/issue_resolver.py` with auto-detect logic (`SIN-N` → Linear, `owner/repo#N` → GitHub, etc.) — could be ported when his PR rebases onto M5.

### F-2 generalized ~~(INVALID — same measurement error as F-2)~~

Retracted along with F-2. Verified `canopy issue 999 --json` exits 1 on BlockerError output.

### F-10: `gh search issues` query construction is malformed

`GitHubIssuesProvider.list_my_issues` builds a query string with qualifiers (`repo:foo`, `is:open`, `assignee:@me`, `label:"bug"`) and passes it positionally to `gh search issues`. But `gh search issues` treats positional args as search *text*, so the whole string gets quoted and the GitHub API responds with `Invalid search query`.

The unit tests for `list_my_issues` mock `_gh_json` and assert on the constructed args — so they happily passed even though the args were nonsense to the real CLI.

- **Severity:** medium — the entire `canopy issues` / `mcp__canopy__issue_list_my_issues` flow was broken for the GitHub Issues backend on real `gh` invocations.
- **Fix (this PR):** switch to `gh issue list --repo ... --state open --assignee @me --label ...` (the right verb form). Phil's branch already had this pattern.
- **Lesson:** mocking at `_gh_json` proves the call wiring but not the CLI grammar. A small live-call smoke test (skipped if `gh` isn't authenticated) would have caught this.

### F-9: `setup-agent --check` only reports the default skill

`canopy setup-agent --check --json` returns `{skill: {...}, mcp: {...}}` — but `skill` is hardcoded to `using-canopy`. After installing `augment-canopy` via `--skill augment-canopy`, the `--check` output still only reports `using-canopy`'s state.

- **Severity:** low — install side works correctly; `--check` is just incomplete reporting.
- **Fix:** `check_status` should iterate `available_skills()` and return `skills: [...]` parallel to the install-side report.

### F-5: no `canopy issues` (plural) CLI command

The test plan's §2.1 assumed `canopy issues` lists the user's open issues. It doesn't exist — only `canopy issue <alias>` (singular, fetches one). The MCP tool `issue_list_my_issues` exists, but there's no CLI mirror.

Phil's `extension-rewrite` branch added `canopy issues --json` for exactly this reason (his extension calls it via subprocess for the issue picker).

- **Severity:** medium — gap between MCP + CLI surface; the test plan + the agent skill both implicitly assume the CLI form exists.
- **Fix candidates:** (a) add `cmd_issues` in `cli/main.py` calling `issue_list_my_issues`; (b) wait for Phil's PR which already has it.

### Real workspace issues caught by doctor (validation pass for M1)

Doctor reported 8 issues in `~/projects/canopy-test`, all `auto_fixable: true`:

| Code | Severity | What |
|---|---|---|
| `heads_stale` × 2 | warn | `heads.json` out of sync for test-api + test-ui (post-checkout hook didn't fire after manual git ops) |
| `worktree_missing` × 4 | error | `features.json` references worktree paths that don't exist on disk (deleted manually): `demo-parallel/test-{api,ui}`, `sin-5-search/test-ui`, `sin-7-empty-state/test-ui` |
| `preflight_stale` | info | preflight result for `doc-1001-paired` test-api is stale |
| `vsix_duplicates` | info | 4 canopy vsix install dirs found in `~/.vscode/extensions/` |

This is the recovery scenario M1 was built for. Detection works end-to-end against a real workspace. **Did not** run `--fix` yet (4 of these would recreate worktrees on disk; defer until intentional cleanup).

---

## Action items from this run

- [x] **F-7 fix (P0)** — provider-aware alias resolver via `IssueProvider.parse_alias()`. CLI now works for any provider with bare/hash/owner-repo/URL alias forms. Shipped in fix/issue-alias-resolver PR.
- [x] **F-10 fix (incidental)** — `GitHubIssuesProvider.list_my_issues` was using malformed `gh search issues` query (qualifiers got quoted as text → `Invalid search query`). Switched to `gh issue list --repo ... --assignee @me`. Found while smoke-testing F-5; unit tests had mocked the boundary so they didn't catch it. Shipped in same PR.
- [x] **F-5 fix (P2)** — added `cmd_issues` for parity with MCP `issue_list_my_issues`. Shipped in same PR.
- [ ] **F-6 fix (P1)** — make `cmd_issue` render `Issue.to_dict()` directly so CLI + MCP agree. Drop the legacy raw-state shape. Update docs/commands.md. ~30 min.
- [ ] **F-1 fix (P1)** — improve the "no canopy.toml" error message to explain canopy's mental model (workspace = non-git directory holding repos + canopy.toml). ~10 min.
- [ ] **F-5 fix (P2)** — add `cmd_issues` for parity with the MCP `issue_list_my_issues`, OR defer to Phil's PR (which has it).
- [x] **F-3** — doctor `mcp_orphans` check + reaper. Detects PPID=1 canopy-mcp processes; SIGTERM with 2s grace then SIGKILL. Auto-fixable (info severity). Original observation was partially misread — see updated F-3 above.
- [x] **F-4** — `docs/mcp.md` "Heads up — OAuth needs a TTY" callout under the HTTP+OAuth section. Documents the headless-hang failure mode + workaround.
- [ ] **`canopy doctor --fix`** — on a follow-up session, intentionally clean canopy-test's real drift (heads.json + missing worktrees + vsix duplicates) to validate the repair side end-to-end.

## Test-data cleanup

- ✅ Throwaway issues #5 + #6 on `ashmitb95/canopy-test-api` closed at end of run.
- ✅ canopy-test workspace canopy.toml restored to original; README.md edits in test-api/test-ui reset.
- 🟡 Memory file `~/projects/canopy-test/.canopy/memory/sin-7-empty-state.{md,jsonl}` left in place — it's gitignored per M4's auto-write, harmless. Cleanup instruction: `rm -rf ~/projects/canopy-test/.canopy/memory/` if a fully fresh state is wanted.

## Headline takeaway

**The MCP/agent-facing surface is healthy across M0–M5; the CLI/human-facing surface has 2 important bugs (F-6, F-7) and 4 small ones (F-1, F-2, F-5, F-9).** None are catastrophic — agents using the MCP tools get correct, canonical responses. But human users hitting the CLI directly get raw provider strings, broken alias resolution for non-Linear providers, and exit codes that lie about success. The asymmetry was invisible in the unit suite because every tested code path went through the action layer's MCP shape — the CLI rendering bugs only surface when you actually type the commands.

---

## How to interpret this doc

- Findings labeled `F-N` are bugs / gaps surfaced by this test run. Each has severity + suggested fix.
- The "Action items" at the bottom are the to-do list for the next session.
- Pass-with-finding (⚠️) means the surface works but reveals a quality issue worth noting.
- This file is the *test run record*; the static plan to re-run is at [test-plan.md](test-plan.md).
