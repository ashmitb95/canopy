# Core API

What the UI builds on. `createCore` (`src/group/host.ts`) returns everything AgentDeck does, with no UI. The extension and the terminal driver (`scripts/driver.ts`) are hosts of it. Nothing here imports `vscode`.

```ts
const core = await createCore({ root, storage, env, providers })
core.chats   // GroupChats: every chat in the workspace
core.lanes   // LaneCoordinator: create and move lanes
core.manager // SessionManager: one session per agent per chat
core.tracker // LaneTracker: repos, checkouts, lanes, live from Git
core.memory  // LaneMemory: goals, plans, notes in .agentdeck/
await core.dispose()
```

## Chats

`core.chats.create({ lead, roster?, mode?, laneId?, enforce?, verify?, questionsTo? })` returns a `GroupChat`. `list()`, `get(id)`, and `delete(id)` manage the rest. Chats reload from disk, and an interrupted delegate resumes.

| Call | Does |
|---|---|
| `send(text)` | Routes each `@agent` part, the rest to the last agent addressed. Returns each part's `delivery`: `now`, `end-of-turn`, or `queued`. |
| `stopAndSend(queuedId)` | Interrupts the running agent so a queued message goes now. |
| `cancelQueued(id)`, `moveQueued(id, index)` | Edit the queue. |
| `stop()`, `retry()` | Stop the running agent; continue after a stop such as a failure or a limit. |
| `setLead(agent)`, `setLane(lane)` | Change the lead; put every agent on a lane. |
| `answer(agent, itemId, response)` | Answer a permission or a provider's question. |
| `answerQuestion(id, text)` | Answer a question that came to the user. |
| `review()` | Each delegate's diff, report, and recorded facts. |
| `undoDelegation(id)` | Reverse one delegate's changes, keeping later work; refuses on overlap. |
| `undoViolation(id)` | Put back a write that should not have happened. |

`state()` is everything a screen shows: lead, target, running agent, queue, members with status and current activity, roster, delegations with facts, violations, questions for the user, limits, and quotas. `items()` is the timeline across agents.

`onEvent` fires `{ type: 'item', agent, item }` for each streamed item (compact them with `rollingLines` from `src/group/rolling.ts`) and `{ type: 'state', state }` whenever the state changes.

## Lanes

| Call | Does |
|---|---|
| `newLane(name, repos, { worktrees, goal })` | Creates a lane in slots, warmed up, or in the primary checkouts. |
| `moveIntoPrimary(lane, answers?)` | Moves a lane into the primary checkouts as one transaction. Throws `SwitchQuestion` when preflight needs the user (answer with `makeLane` or `takeForeign`), and `SwitchError` when it cannot go ahead. Nothing changes in either case. |
| `moveToWorktree(lane)` | Moves it out; the base branch goes back in. |
| `unfinishedMoves()`, `undoUnfinishedMoves()` | Find and undo a move a crash left unfinished. |
| `boundary(record)` | A chat's write boundary on its lane. |

`laneFromIssue(core, issue)` starts a lane from an issue fetched with `githubIssue` or `linearIssue` (`src/integrations/issues.ts`). `createPullRequest` pushes the branch, never forced, and opens a pull request through `gh`.

## Limits

- Process watching (settling, servers left running) needs `ps` and `lsof`; it is off on Windows, where "done" is taken as reported.
- Remote workspaces have not been tried.
- Catch-up is capped at 16,000 characters per turn; older messages stay in the ledger file, which the agent is told about.
