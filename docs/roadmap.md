# Roadmap

AgentDeck is a multi-agent, multi-provider orchestrator for large features: different providers do different work, the harness moves the work between them, and the user stays in one conversation.

Planned work, in priority order. [lanes.md](lanes.md) and [architecture.md](architecture.md) describe what exists today.

## 1. Group chat across providers

One chat for a feature, where anyone can lead. Providers cannot share a live session, so a chat is a timeline over one provider session per agent, and AgentDeck owns the shared record. [ui-spec.md](ui-spec.md) shows the experience.

- **Roster:** the lead and a provider per role (research, plan, implement, review), set per workspace and changeable per chat.
- **`@mentions`:** AgentDeck routes them directly, with no model involved.
- **Delegation:** the lead calls a `delegate` tool, served to every provider by one local tool server. Delegates cannot delegate further at first.
- **Turns:** one agent runs at a time in a lane, so writes need no locks. Others wait in a visible queue. Work that must truly run at once uses separate lanes.
- **Enforcement:** roles are enforced. Implement is the only writing role by default. Edit tools and sandboxes block the rest; `git status` after each turn catches writes through shell commands, with a notice and an offer to undo. `.agentdeck/` stays writable.

### Ledger and handoffs

AgentDeck keeps a ledger of each chat and how far each agent has read. Handoffs are views of it, written without user involvement.

| Moment | The agent receives |
|---|---|
| Lead to delegate | The lead's task and "done when", the user's messages verbatim, roster, lane plan, and everything since it last ran |
| Delegate to lead | Facts recorded by AgentDeck (diff, commands, test results) and the delegate's report: status, done, not done, decisions, risks, questions |
| `@mention` | As a delegate; the lead catches up on its next turn |
| Lead switch | A catch-up, work in progress, and that it now leads |

- `delegate` returns at once and the lead's turn ends. AgentDeck starts the lead's next turn with the report, so no long tool call stays open.
- A snapshot before each delegate gives an exact diff and an undo. It must include untracked files, which `git stash create` leaves out, without disturbing the checkout; the proof of concept settles how.
- The complete transcript is saved as a file the lead can read.

### Permissions and questions

- **Permissions and plan approvals:** always the user. A model never grants permission.
- **Clarifying questions:** the lead first, if the chat covers them, with the answer shown and changeable; otherwise the user. A setting sends them all to the user.
- **Questions in plain text:** detected through a required status line in the delegate's report (`done`, `blocked`, or `question`).
- **Loops and limits:** a set number of rounds between two agents stops and asks the user. A lead at its limit passes questions straight to the user. A failed delegate reports to the lead, with no automatic switch to another provider.

### Proof of concept

Before building, prove with real CLIs in temporary repos: `delegate` through the tool server from all three providers, the end-turn-and-wake flow, catch-up quality, enforcement and its backstop, snapshots, permissions and each kind of question, requests pending across a restart, and whether a lead invents answers.

## 2. Reliable lane switching

A branch can be checked out in only one place, so switching is the main source of friction. The harness treats a switch as a transaction: nothing changes until it can finish, and it can always be undone.

1. **Preflight, changing nothing, in every repo:** classify each state below. All repos must pass, or none move.
2. **Wait:** no affected chat is mid-turn. Queue the switch for the end of the turn, and hold new turns.
3. **Snapshot:** stash both sides' uncommitted work, untracked files included, under named stashes (`agentdeck:<lane>:<ts>`), pin each with a ref in `refs/agentdeck/` so a user's `git stash clear` cannot lose it, and write a recovery journal.
4. **Swap:** detach the slot's worktree to free the branch, switch the primary checkout, then check the outgoing lane out in that slot. Folders trade branches, keeping installed dependencies and their paths. Restore each side's work.
5. **Verify and settle:** check both sides, rerun setup only where a lockfile changed, tell affected chats, and offer to restart the dev server.

Any failure restores both sides from the snapshot. On startup, an unfinished journal offers to finish or undo.

| State | Handling |
|---|---|
| Both clean, or uncommitted work that applies cleanly | Automatic |
| Primary checkout on the base branch, clean | Automatic; the base branch needs no worktree |
| Lockfile or env files differ | Automatic, with setup rerun or a notice |
| Primary checkout on the base branch with uncommitted work | Ask: make it a lane, or stash it |
| Untracked file collides with one on the other branch | Ask, naming the files |
| Branch held by a worktree AgentDeck did not create | Ask |
| Agent mid-turn | Wait, or offer Stop |
| Merge, rebase, or cherry-pick in progress, or detached HEAD | Stop and explain |
| Locked worktree, submodule changes | Stop and explain |

### Worktree slots

Worktrees live in generically named folders, `<repo>/.worktrees/wt-<n>`, and hold whichever lane is warm there.

- Paths stay stable across switches, so terminals, editor windows, tool caches, and dev server configs keep working. Branch names with `/` need no mapping, and nothing is renamed.
- **Occupancy is derived from `git worktree list`, never stored.** There is no slots file to drift or repair. A lane takes the lowest number free across its repos, so it keeps one number everywhere when it can.
- A lane leaving a slot leaves the folder detached and warm. The next New Worktree reuses it, with setup rerun only if the lockfile differs.
- The number of slots has a setting. At the limit, AgentDeck asks which slot to free and never evicts by itself. Removing a slot checks for uncommitted work first.
- Slot numbers can map to dev server ports (`wt-1` to a port offset), so warm lanes can run side by side.
- Worktrees that users or agents created keep their names and are tracked as they are. Agents get current paths in the brief, and the UI always shows the lane, not the folder.

To prove first, with no agents or quota: every row above in real repos, multi-repo all-or-nothing, and a failure injected at each step. `src/lanes/switch.ts` today removes the worktree, has no preflight or rollback, and can stop partway.

## 3. Lanes and Sessions redesign

The target is in [ui-spec.md](ui-spec.md).

- A collapsible **Lanes** section above **Sessions** in the primary sidebar, and a full view in an editor tab. Main is the most prominent element; warm lanes are one click from moving into main; cold lanes stay folded away.
- Session rows show state, active provider, current activity, lane, and time: needs input (with the request and inline actions), working, waiting, finished, failed, idle.
- Both become webviews, because a native tree cannot show this. Keyboard navigation and context menus must carry over.
- New status data: a current-activity line summarized from each provider's tool events.
- Show what changed in main to chats on other lanes, on their next turn.
- Park a warm lane as cold, after checking for uncommitted work.

## 4. New Worktree

One action from the Lanes section and the full view: choose an agent, optionally an issue. It creates the branch and worktree, warms it up, and opens the chat. Everything downstream follows from the lane.

To verify: renaming a branch from the first message when no issue was chosen.

## 5. GitHub and Linear

Picking an issue seeds the lane: its goal, a link, and the description and comments in lane memory, which the brief then points every chat at. The app fetches once; agents spend no context on it.

- **GitHub:** through the user's `gh` login. AgentDeck stores no token.
- **Linear:** an API key in SecretStorage first, OAuth later.

## 6. Release

- Claude terms: pass the CLI's environment through instead of removing `ANTHROPIC_API_KEY`, label the provider "Claude Agent" in menus not titled "Agents", avoid "Claude Code" in product names and any implied endorsement, and include notices for the bundled Agent SDK.
- Name and icon, a private repository, fresh history before going public, code and security review, Windows and remote support or a stated lack of it, tests inside VS Code, Marketplace and Open VSX listings, and CI for provider version bumps.

## 7. Claude connection settings (low priority)

Set up subscription, API key, and Bedrock inside AgentDeck, and switch between whichever are configured.

| Connection | What the CLI gets | Where credentials live |
|---|---|---|
| **Subscription** | Its own sign-in; `ANTHROPIC_API_KEY` unset | The CLI, through Anthropic's flow |
| **API key** | `ANTHROPIC_API_KEY`, optional `ANTHROPIC_BASE_URL` | VS Code SecretStorage |
| **Amazon Bedrock** | `CLAUDE_CODE_USE_BEDROCK=1`, `AWS_PROFILE`, optional `AWS_REGION` and model pins | The AWS credential chain, or `AWS_BEARER_TOKEN_BEDROCK` in SecretStorage |

These set environment variables on the spawned CLI only. Each chat shows its connection.

To verify: whether `env` in the CLI's `settings.json` overrides these variables, whether a session resumes across connections, and what a backend lacks (quota on API key and Bedrock, WebSearch on Bedrock).

The hard rule on credentials in [AGENTS.md](../AGENTS.md) changes with this work: never read or store Claude account credentials; API keys the user adds go only in SecretStorage and only to the CLI's environment.
