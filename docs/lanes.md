# Lanes

A lane is a unit of work: branch `X` in every repo that has it. Chats link to a lane through `SessionRecord.laneId`. A chat on no lane behaves like a plain chat.

## Workspace

```
workspace/                  ← every chat's cwd
├─ .agentdeck/              ← stored intent
├─ ui/                      ← repo: primary checkout on some branch
│  └─ .worktrees/retry-fix/ ← worktree of branch retry-fix
└─ api/
```

- A root that is itself a repo is the only repo; otherwise repos are found by a depth-limited scan (`discover.ts`).
- `.worktrees/` goes in `.git/info/exclude`, never in a committed `.gitignore`.
- In folder names, `/` in a branch becomes `--`.

## Derived state

`LaneTracker` watches each repo's Git directory (HEAD, packed-refs, `refs/heads`, `worktrees`) and refreshes, debounced, from `git worktree list --porcelain`, base-branch detection, and `status --porcelain` with `GIT_OPTIONAL_LOCKS=0`. None of this is stored.

## Stored intent: `.agentdeck/`

```
config.toml                 env_files, [setup] per repo, worktrees, [task.<id>]
lanes/<lane>/
  lane.toml                 goal, created, worktrees
  plan.md
  notes.md
  chats/<id>.md             stamped chat summaries
  history.jsonl             moves and other events
```

TOML is a small subset (`toml.ts`): `key = <JSON>` lines and `[table]` headers. Entries are stamped `<!-- iso · provider:chat8 · repo@sha7 -->`.

## Briefs

`lane-context.ts` appends a tagged block to what the provider receives: a brief with pointers on a chat's first turn, then a delta when something changed. `record.laneSeen` holds what the chat has seen. The transcript keeps the user's own message.

## Moving lanes

`switch.ts`: `moveIntoPrimary`, `moveToWorktree`, `joinRepo`. Uncommitted work travels in uniquely named stashes (`agentdeck:<lane>:<ts>`). Nothing moves while an affected chat is mid-turn. A stash that does not re-apply stops the move and stays in place.

`warmup.ts`: a new worktree gets the configured env files copied from the primary checkout, then the repo's setup command.

## Coordination

`LaneCoordinator`:

- **One writer:** the manager queues a second chat's prompt and wakes it when the lane frees up.
- **Boundary:** `WriteBoundary { roots, except, outside(path) }`, enforced per provider ([providers.md](providers.md)). Reads stay open.
- **Redirect:** a write outside the boundary is sent to the same file in the lane's checkout. If the repo is not part of the lane yet, it joins first.
- **Auto-link:** after a turn, a chat links to a lane from the paths it edited (`auto-link.ts`).

## Handoffs

`tasks.ts` and *Hand off to…*: Research, Plan, Build, Review, each with a default provider from `[task.<id>]`. A handoff starts a new chat on the lane; nothing advances by itself.

## Not built

Archiving lanes, merged and ahead/behind status, per-lane restart of dev servers, PR and issue links.
