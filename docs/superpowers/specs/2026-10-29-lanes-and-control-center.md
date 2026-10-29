# Lanes and the Control Center — design

AgentDeck's specialization. The chat (at parity with AFK Pilot) is a component; the **Control Center** is the primitive that drives it. A **lane** is a unit of work, a feature, that spans one or more repos, owns its chats, and carries its own memory. AgentDeck tracks where each lane's code lives, moves lanes into and out of the main checkouts when asked, keeps moved-out lanes warm, and tells every chat where to work.

This supersedes decision 5 ("agents manage worktrees themselves") with *agents still may, and AgentDeck tracks the result*, and decision 7 ("no coordinator") with a light, app-side coordinator that agents never see.

## Why

- **Main is where code runs.** Env files, local services, installed dependencies, and dev servers live in the main checkout. Worktree-first tools (Conductor, Nimbalyst, Vibe Kanban, Claude Squad, AFK Pilot's worktree sessions) push work into isolated checkouts that often do not run, then ask you to merge it back to try it. Lanes do the opposite: the lane you want to run goes *into* main; the others wait, warm, in worktrees.
- **Features span repos.** `docsum/ui` and `docsum/api` change together. A lane is one feature across both.
- **Agents lose the thread.** Context windows fill, providers change, chats end. A lane carries goal, plan, decisions, and chat summaries, so any new chat, with any provider, starts oriented.
- **Canopy had the right ideas in the wrong place.** Canopy made the *agent* coordinate through MCP tools and kept a state file describing Git that drifted. Here the *app* coordinates, invisibly, in the same process that runs the agents, and derives state from Git.

## Principles

1. **Every chat runs at the workspace root.** The agent's working directory never changes, so provider sessions (Claude's are keyed by folder) always resume. Where to work is an instruction and a permission boundary, not a `cwd`.
2. **Derive everything Git knows; store only intent.** Repos, branches, worktree locations, which lane holds main, dirty state, ahead/behind, merged: all read live from Git and never written down. Goals, plans, notes, summaries, and chat-to-lane links are stored, stamped, and reconciled.
3. **Track, don't manage.** Agents may create worktrees and branches themselves; AgentDeck notices and attaches them. AgentDeck acts on Git only when you ask (switch, warm up, archive).
4. **Opt-in.** A plain chat with no lane works exactly as today. Lanes, workflows, and worktrees appear when you use them.
5. **Never lose work, never surprise.** Uncommitted changes travel with their lane. Anything that cannot complete cleanly stops and shows why. Nothing switches while an affected chat is mid-turn.

## Workspace model

```
docsum/                          ← workspace root: every chat's cwd
├─ .agentdeck/                   ← lane memory and config (intent only)
├─ ui/                           ← repo; main checkout on some branch
│  └─ .worktrees/retry-fix/      ← worktree of branch retry-fix
└─ api/
   └─ .worktrees/retry-fix/
```

- **Repos** are discovered by scanning the root (depth-limited) for Git repositories; if the root itself is a repository (single-repo workspace), it is the only repo and worktrees go in `<root>/.worktrees/`.
- **Worktree folder:** `<repo>/.worktrees/<lane>`. AgentDeck adds `.worktrees/` to the repo's `.git/info/exclude` (never to a committed `.gitignore`).
- **Lane names** are branch names. Branch names containing `/` (e.g. `feat/retry`) map to a folder with `/` replaced by `--` (`.worktrees/feat--retry`).

## Lane model

**Identity.** Lane `X` *is* branch `X` in every repo that has it. A lane may exist in some repos and not others; joining a repo creates the branch there.

**Derived per repo (never stored):**

| State | Meaning |
|---|---|
| `main` | The branch is checked out in the repo's main checkout (this lane holds main) |
| `worktree` | The branch is checked out in a linked worktree (any path; `.worktrees/X` by convention) |
| `branch` | The branch exists with no checkout |
| `absent` | No such branch in this repo |

plus dirty (uncommitted) state, ahead/behind its upstream and its base, and merged-into-base.

**Lane status (derived):** *active* (has a checkout somewhere), *parked* (branches only), *merged* (merged into base in every repo it touches; offer archive), *missing* (a lane with stored memory whose branch no longer exists anywhere; offer re-link or archive).

**The "main / no lane" group.** Chats not on a lane run against whatever each main checkout holds, exactly like today's chats.

## Stored intent: `.agentdeck/`

```
.agentdeck/
├─ config.toml                   ← optional: setup command, env files to copy, repos to ignore, task-type defaults
└─ lanes/<lane>/
   ├─ lane.toml                  ← goal summary, base branch per repo, created, archived?
   ├─ plan.md                    ← the living plan (agents update it)
   ├─ notes.md                   ← append-only decisions and findings
   ├─ chats/<chat-id>.md         ← one summary per chat (handoff brief), append-only
   └─ history.jsonl              ← moves, switches, warm-ups, commits observed
```

- Lives at the workspace root. In a multi-repo workspace the root is not a repo, so nothing here is committed by accident; in a single-repo workspace `.agentdeck/` is added to `.git/info/exclude`.
- Plain Markdown and TOML, readable and editable by you and by agents.
- **Nothing in `.agentdeck/` describes Git state.** If you delete it, lanes still appear (from branches); only their memory is gone.

**Stamping.** Every note entry, plan revision, and chat summary records `when`, `by` (chat id and provider, or `you`), and `at` (each repo's HEAD commit at write time), as a front-matter line or entry prefix: `<!-- 2026-10-29T15:41Z · claude:chat-7f3a · api@3f2c1a ui@91be04 -->`. The brief reports how far each repo has moved since.

**Chat ↔ lane** links live in AgentDeck's session store (`SessionRecord.laneId`), not in `.agentdeck/`.

## The lane brief and the lane delta

**Brief** (first turn of a chat on a lane), built at send time:

```
<lane name="retry-fix">
Goal: make the flaky retry test reliable and add a regression test.
Code: api/ (main checkout, branch retry-fix, 2 uncommitted files) · ui/.worktrees/retry-fix (branch retry-fix, clean)
Plan: .agentdeck/lanes/retry-fix/plan.md (updated 1h ago, api is 2 commits ahead of it)
Notes: .agentdeck/lanes/retry-fix/notes.md (4 entries)
Earlier chats: Research · Grok — timer race in retry() (.agentdeck/lanes/retry-fix/chats/a1.md); Plan · Claude — 3-step plan, step 1 done (…/b2.md)
Rules: edit only the paths above. Do not switch branches in main checkouts. Update plan.md as steps finish; add decisions to notes.md.
</lane>
```

Pointers, not pasted content; the agent reads what it needs. Kept under ~1 KB.

**Delta** (every later turn, only if something changed since this chat's last turn): moves, new commits by others, plan edits by another chat, e.g. "Since your last turn: retry-fix moved from api/ (main) to api/.worktrees/retry-fix; your uncommitted changes came with it. api/ main now belongs to auth-flow — do not edit it."

Both are encoded like editor context (a tagged block appended to the prompt). Queued prompts get the delta computed when they are sent.

## Switching and warming

**Switch lane A into main** (per repo, or all of A's repos at once), while lane B holds main:

1. **Preconditions:** no chat on A or B is mid-turn (wait, or offer Stop). Record dirty state on both sides.
2. **Move B out:** stash B's uncommitted changes in the main checkout (`git stash push -u`), create `repo/.worktrees/B` on branch B, re-apply the stash there.
3. **Bring A in:** if A has a worktree, carry its uncommitted changes the same way, remove that worktree (a branch cannot be checked out twice), check out A in the main checkout, re-apply.
4. **Warm B up** in the background (below).
5. **Record and notify:** append to both lanes' `history.jsonl`; add a transcript notice to every chat on A and B ("↪ auth-flow moved to api/.worktrees/auth-flow · retry-fix took api/ main"); their next prompts carry the delta.

**Failure handling:** each step is checked; a stash that does not re-apply cleanly stops the switch, leaves the stash in place, and shows the conflict with options (resolve in VS Code, revert the switch). No step runs `reset --hard` or deletes a branch. A running dev server is not restarted (later: offer to restart a VS Code task).

**Warm-up** (bootstrap) for a lane checkout outside main: copy the configured env files (`.env*` and others listed in `config.toml`) from the main checkout, then run the configured setup command (e.g. `pnpm install`) in that folder. Progress and failures show on the lane. A warm lane is one whose worktrees exist and whose setup last succeeded.

**Creating a lane:** from the Control Center or a chat ("New lane from this chat"): name, goal, repos to join, and where to start (main, or worktrees). Creating in worktrees runs warm-up.

## Enforcement

Lane rules are instructions *and* permission boundaries:

| Provider | Boundary |
|---|---|
| Claude | `canUseTool` sees each tool's path; edits outside the lane's current paths (or inside a main checkout the lane does not hold) are denied with a message naming the right path. Bash commands are checked for `git checkout`/`switch` in main checkouts. |
| Codex | The turn's `sandboxPolicy.writableRoots` is set to the lane's current paths; writes elsewhere fail in Codex's sandbox. Approval requests for out-of-lane paths are declined. |
| ACP agents | `session/request_permission` carries locations; out-of-lane paths are rejected. |

Read access stays open everywhere: agents may read other lanes and repos for reference.

## Reconciliation

AgentDeck watches each repo's `.git` (HEAD, refs, worktrees) and recomputes derived state on change, debounced. Observed events update lanes: a branch checked out by hand in a terminal changes who holds main; a worktree an agent created is attached to its lane; a merged branch marks the lane *merged*; a deleted branch marks it *missing*. Each observed change is appended to `history.jsonl` and, when it affects a chat's paths, reaches that chat as a delta.

## Workflows inside a lane

A lane can run a workflow: ordered stages, each a real chat with its own provider, model, mode, approvals, and resume. Task types to start: **Research, Plan, Build, Review**, each with a default provider, model, and mode set in `.agentdeck/config.toml` or the Control Center (e.g. Research → Grok, Plan → Claude in Plan mode, Build → Codex in Accept edits, Review → Claude). *Next stage* asks the current chat for its handoff brief (saved as its chat summary), lets you edit it, and starts the next stage with the lane brief plus that handoff. Stages never advance on their own; one stage writes at a time. *Hand off to…* is the one-off version outside a workflow.

## Notifications

AgentDeck notifies natively from its own session events (no hooks): turn finished, needs approval or an answer, failed. Carried over from claude-notifier: per-event sounds and levels, volume, a minimum-duration threshold, auto-mute when the chat is visible and VS Code is focused, the chat name plus what happened ("edited 2 files · ran 5 commands", the command awaiting approval, the question asked), and remote audio for SSH/WSL hosts. Messages lead with the lane and stage: `retry-fix · Build · Codex — needs approval: pnpm db:migrate`. CLIs AgentDeck spawns get `CLAUDE_NOTIFIER_DISABLE=1` so claude-notifier's hooks do not double-notify.

## The Control Center

- **Board:** per repo, which lane holds main; active lanes with their per-repo locations, warm-up state, dirty and ahead/behind; parked lanes; a rail of what needs you (approvals, questions, failed turns, conflicts). Actions: *Switch into main*, *Warm up*, *New chat*, *Start workflow*, *Archive*.
- **Lane view:** goal; per-repo cards (branch, location, dirty, ahead/behind, base); plan and notes (open in editor); the lane's chats with provider, stage, status; activity history; *Review changes* across repos (multi-diff); later *Commit / Push / PR* per repo and *Ship*.
- **Sidebar:** lanes, each with its chats, plus the "main / no lane" group; the chat itself is unchanged.

## Later (carried over from canopy)

PR and review-thread triage on the lane view (with *Address in agent*), issue linking (Linear/GitHub) for lane goals, cross-lane conflict detection, and a lane-wide preflight.

## Open questions

- Two chats on the same lane at once: allowed for reading; for writing, one writer per lane path at a time (queue the second's turns, or warn)?
- Lanes present in only some repos: joining a repo later from main vs from a worktree.
- Root that is a repo *and* contains nested repos (submodules or vendored repos): ignore nested, or treat as separate repos?
- How long to keep `history.jsonl` and chat summaries for archived lanes.
