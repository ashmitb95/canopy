# Lanes

A lane is a unit of work: branch `X` in every repo that has it. Chats link to a lane through `SessionRecord.laneId`. A chat on no lane behaves like a plain chat.

## Workspace

```
workspace/                  ← every chat's cwd
├─ .agentdeck/              ← stored intent
├─ ui/                      ← repo: primary checkout on some branch
│  └─ .worktrees/wt-1/      ← worktree slot, holding whichever lane is there
└─ api/
```

- A root that is itself a repo is the only repo; otherwise repos are found by a depth-limited scan (`discover.ts`).
- `.worktrees/` goes in `.git/info/exclude`, never in a committed `.gitignore`.

## Derived state

`LaneTracker` watches each repo's Git directory (HEAD, packed-refs, `refs/heads`, `worktrees`) and refreshes, debounced, from `git worktree list --porcelain`, base-branch detection, and `status --porcelain` with `GIT_OPTIONAL_LOCKS=0`. None of this is stored.

## Stored intent: `.agentdeck/`

```
config.toml                 env_files, [setup] per repo, worktrees, max_slots, [task.<id>]
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

`switch.ts` treats a move as a transaction. `preflight` changes nothing and answers ok, ask, or stop; all repos must pass before any moves. `swap` then snapshots both sides to named stashes pinned under `refs/agentdeck/`, writes a journal to the Git directory, detaches the slot, switches the primary checkout, gives the slot the outgoing lane, restores each side's work, and verifies. Any failure restores both sides; leftovers are stashed, never discarded. After a crash, `rollback` undoes the move from the journal.

Worktrees are slots: `<repo>/.worktrees/wt-<n>`. Occupancy comes only from `git worktree list`. A parked lane leaves its slot detached and warm for the next lane, and existing lane-named worktrees migrate on the next move. `max_slots` in `config.toml` sets the limit (default 4). Worktrees elsewhere are tracked but not moved without asking. Primary checkouts can hold different lanes in different repos; each repo moves on its own terms within one all-or-nothing move.

`warmup.ts`: a new slot gets the configured env files copied from the primary checkout, then the repo's setup command. A reused slot reruns setup only when a lockfile changed.

## Coordination

`LaneCoordinator`:

- **One writer:** the manager queues a second chat's prompt and wakes it when the lane frees up.
- **Boundary:** `WriteBoundary { roots, except, outside(path) }`, enforced per provider ([providers.md](providers.md)). Reads stay open.
- **Redirect:** a write outside the boundary is sent to the same file in the lane's checkout. If the repo is not part of the lane yet, it joins first.
- **Auto-link:** after a turn, a chat links to a lane from the paths it edited (`auto-link.ts`).

## Handoffs

`tasks.ts` and *Hand off to…*: Research, Plan, Build, Review, each with a default provider from `[task.<id>]`. A handoff starts a new chat on the lane; nothing advances by itself.

## Not built

Archiving lanes, merged and ahead/behind status, per-lane restart of dev servers, PR and issue links, and a UI for preflight questions and crash recovery.
