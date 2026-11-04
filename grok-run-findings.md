# Grok run findings

Notes from reading the Phase 3 handoff and the code on `core`. No code was changed. The live test was not run. `git status` was clean before this file.

## Where the repo is

- Branch `core`, even with `origin/core`.
- Latest commit: `f9b6159` — `fix(acp): read-only agents run reads and commands without waiting for a person`.
- Phases 0, 1, and 2 are done and committed. Phase 3 (delegation) is in `src/group/chat.ts` with unit tests. Its live script has not reported in this session.
- Phase 4 has not started. `poc/settle.ts` is still in `poc/`.

The handoff is `.canopy/handoff.md` (copy at `~/canopy-handoff.md`). The Claude session reader for `281c9f85-9c75-47f3-a4b3-7c9a8444c0aa` skipped 68 unknown records and recovered only a short tail: the Phase 3 rerun had been handed to Grok, then the user interrupted. Treat that transcript as incomplete.

## Claude quota

Claude usage was reported at about 95%. Every built-in arrangement of the live test still uses Claude in one role:

| Argument | Lead | Implement | Review | Claude's role |
|---|---|---|---|---|
| `claude` | claude | codex | grok | Lead. Heaviest. Also the arrangement that puts Codex on the commit and Grok on review. |
| `grok` | grok | claude | codex | Implementer. Heaviest writing role. |
| `codex` | codex | grok | claude | Reviewer. Lightest of the three. |

`scripts/smoke-delegate.ts` accepts one lead name. With no argument it runs all three in sequence. Do not run it with no argument while Claude is this low.

A lead cannot delegate to itself (`That is you` in `GroupChat.handleTool`). Implement and review may be the same agent. A run with no Claude is possible only as an explicit triple the script does not accept today, for example lead `grok`, implement `codex`, review `codex`. That would exercise Grok as a read-only lead and Codex as the writer. It would not exercise Claude at all.

## What `smoke-delegate` checks

`scripts/smoke-delegate.ts`, after `pnpm build`, via `node dist/smoke-delegate.js <lead>`:

- Temp git repo, lane `slugify`, worktrees on, slot `<repo>/.worktrees/wt-1`.
- Chat mode `full-access`. Roster plan = lead, plus implement and review. Verify command `node --test`.
- Prompt: add `slugify.js` and `slugify.test.js`, then get it reviewed.
- Passes only if the lead delegates the build unprompted, the files land in the slot and not the primary checkout, recorded facts name the files, Canopy's own verify passes, review was delegated, no role violation, and the lead spoke last.
- Gives up after 420s. Each arrangement spends real CLI quota.

## Read-only ACP fix (committed, not live-tested)

`src/providers/acp/provider.ts` `permission()`: a boundary with `roots.length === 0` is read-only. Reads and commands are allowed with no person present. An edit is refused. A shell that writes is still caught after the turn by `git status`.

That boundary comes from `GroupChat.readOnlyBoundary`: when roles are enforced, every agent except the implementer gets `{ roots: [] }`. `GroupChats.boundary` returns that value. `createCore` uses `chats.boundary(record) ?? lanes.boundary(record)`, so an implementer (whose read-only boundary is `undefined`) falls through to the lane roots. A reviewer or a read-only lead does not.

`GroupChat.applyRole` then sets ACP agents to `ask` unless they are the implementer. It does not change Claude or Codex. The handoff says this `ask` mode is what stalled a headless Grok review, and likely a Grok lead. The committed fix is supposed to answer those permission requests inside the adapter. It has not been run against a live Grok CLI in this session.

## Codex commit in a worktree slot (seen earlier, not re-run)

The handoff: Codex as implementer hit a permission error on the worktree index lock, so its work stayed uncommitted.

What the code does now:

- With a lane boundary, `sandboxPolicy` in `src/providers/codex/provider.ts` is `workspaceWrite` in every permission mode. `full-access` only turns network on. It does not select `dangerFullAccess` once a boundary exists. An empty `roots` list becomes a read-only sandbox.
- Lane writable roots are the lane checkout plus the lane memory directory (`LaneCoordinator.boundary`). The coordinator test expects exactly `[<repo>/.worktrees/wt-1, <workspace>/.canopy/lanes/<lane>]`.
- The Codex process cwd is the core root, which in this smoke test is the primary checkout (`SessionManager.open` passes `deps.cwd`). The boundary does not add that checkout, and it does not add the git directory.

Where git actually writes, checked with a throwaway repo (created under `/tmp` and removed):

- Worktree git dir: `<repo>/.git/worktrees/wt-1`
- Common git dir: `<repo>/.git`
- Index: `<repo>/.git/worktrees/wt-1/index`

Those paths are outside `<repo>/.worktrees/wt-1`. A sandbox whose only writable root is the slot will deny `index.lock` there. A commit also writes objects and refs under the common git dir, so allowing only the per-worktree git dir would still be short of a successful commit.

Not confirmed: whether Codex `workspaceWrite` also treats the process cwd as writable. This shell has no `codex` on `PATH` (`findCodex` can still pick the binary bundled with the Codex extension). If the cwd is implicitly writable, the primary checkout's `.git` is already inside it, and the index lock would not be outside the sandbox. That case was not checked against the CLI or its schema. The earlier live failure is still only the handoff's report.

macOS detail from the same throwaway repo: `git rev-parse` printed `/private/var/...` while `mktemp` was `/var/...`. Any path comparison has to resolve that symlink.

## Other handoff items, not investigated past the note

- A delegate ended its turn after starting a background test and reported early. Phase 4 settling is the planned answer. `poc/settle.ts` is still outside `src/group/`.
- A reviewer told to run tests does not always do so. The smoke script depends on Canopy running `verify` itself.
- Codex background commands started with `&` disappeared when the command ended. Reports are supposed to show the expected output that is missing. Not traced in this pass.

## Not done

- No live `smoke-delegate` run, in any arrangement.
- No Codex CLI inspection, and no reproduction of the index-lock error.
- No Phase 4 work.
- No commit other than whatever this findings file becomes.
