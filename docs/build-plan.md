# Build plan

How the [roadmap](roadmap.md) and [UI spec](ui-spec.md) get built. Each phase delivers its foundation and its UI together, so it can be used and judged when it lands, with one finishing pass at the end. Each phase gets its own detailed plan before work starts, and proof-of-concept code in `poc/` is rewritten into `src/` with tests, not copied.

Every phase ends with `pnpm check` passing, the webview checked by screenshot in light and dark, and a manual pass in VS Code for what screenshots cannot show.

## Phase 0: Ground work

- Private GitHub repository; merge `poc/group-chat` and `mvp` into `main`.
- Say "primary checkout" everywhere, in code and UI.
- Claude terms: stop removing `ANTHROPIC_API_KEY`, label the provider "Claude Agent" outside menus titled "Agents", show the sign-in method, add third-party notices.
- Clearer sign-in state: a repeated rate limit suggests signing in again.

**UI:** small label changes only.
**Done when:** existing features still work, renamed, and the repository has a remote.

## Phase 1: Sidebar and session states

Replace the native Sessions tree with a webview, because the design needs what a tree cannot show.

- Session rows with state, provider, current activity, lane, and time.
- Attention events drive the rows; needs-input rows get inline actions.
- Keyboard navigation and context menus carried over from the tree.
- Palette support, since this surface now follows `agentdeck.palette`.

**UI:** the Sessions half of the sidebar (`Side.dc.html`).
**Done when:** the webview does everything the tree did, and a session's state is readable at a glance. It comes first because every later phase draws on this sidebar.

## Phase 2: Reliable switching and the lane view

- Move switching to the transaction proved in `poc/swap.ts`: preflight, snapshot, swap, verify, rollback, recovery journal.
- Generic worktree slots, with occupancy derived from Git; migrate lane-named worktrees already in use.
- Warm, cold, and parked lanes; rerun setup only when a lockfile changes.

**UI:** the Lanes section, the lane view (`Lanes.dc.html`), the switch action, questions for each state preflight asks about, and an offer to finish or undo after a crash.
**Done when:** every preflight state works in a real project with a running dev server, which the proof of concept did not cover.

## Phase 3: New Worktree and setup

- One-action New Worktree, reusing a free slot.
- First-run setup: connect agents, workspace settings.

**UI:** `NewLane.dc.html`, `Main.dc.html`, and `Workspace.dc.html`. The roster step waits for phase 5.
**Done when:** a new user reaches a working chat on a new lane from setup alone.

## Phase 4: Group chat core

No delegation yet: the user directs every agent with `@mentions`.

- One chat over one session per provider; the journal records who produced each item.
- The ledger, read cursors, and catch-up.
- `@mention` routing and delivery: steer where the provider can, otherwise deliver at the end of the turn, with Stop and send now.
- Turn-taking and the Now and Next queue.
- Session migration, so existing single-provider chats keep working.

**UI:** provider avatars on replies, takeover markers, the `@` menu, the queue, and a composer that says who gets the message and when.
**Done when:** a feature can be built by mentioning agents by hand. This is the largest change to existing code, and the first point where real feature work runs through it.

## Phase 5: Delegation and the roster

- The local tool server for all providers, and the `delegate` tool.
- Roster settings, and the lead's brief.
- The end-turn-and-wake flow. Detect a lead that says it will delegate but does not, and nudge it once.
- Role enforcement with the write block, the `git status` backstop, and undo.
- Handoffs: ledger views, recorded facts, reports with a status line, and saved transcripts.
- Narration instruction for delegates.

**UI:** the roster screen (`Roster.dc.html`), the delegate card, its rolling window (`Rolling.dc.html`), and the handoff panel (`Chat.dc.html`).
**Done when:** a lead delegates by roster on a real feature, on all three providers, and the user can follow it live.

## Phase 6: The lead in charge

- Settling: open tool calls, process tree, working directories, and a helper ignore list per provider.
- A verification turn for delegates that started background work.
- Lead events and tools: finished, overdue, server left running; message, stop.
- Permissions always to the user. Questions to the lead first, with a limit on rounds, and a setting to send them all to the user.
- Requests pending across a restart. Structured questions, and mentions to paused or queued delegates, which the proof of concept did not cover.
- Quota: usage beside each role, warnings before delegating, Grok's source if one exists, and a clear state at a limit with no automatic switch.

**UI:** every delegate state in the spec, Change answer, and overdue and left-running actions.
**Done when:** a long feature runs with failures, questions, and limits, and the user stays in control.

## Phase 7: Review and integrations

- Per-delegate snapshots, diffs, and undo.
- Review before moving to the primary checkout or creating a pull request.
- GitHub through `gh`; Linear with an API key in SecretStorage. The credentials rule in `AGENTS.md` changes here.

**UI:** `Review.dc.html`, the issue picker in New Worktree, and the integrations in Workspace.
**Done when:** an issue goes to a reviewed change without leaving AgentDeck.

## Phase 8: UI finishing pass

Only consistency work; each screen exists by now.

- One review of every screen and state against the spec, in Paper and Paper Dark, every palette, popular themes, and high contrast.
- Narrow sidebars, long names, empty and error states, many lanes, and very long transcripts.
- Keyboard and screen reader pass, including a rolling window that announces only state changes.
- Performance of the rolling window under bursts of events, and of long chats.
- Lanes across repos whose primary checkouts hold different lanes, which is not designed yet: design it first.

**Done when:** a walkthrough of every screen finds nothing out of spec.

## Phase 9: Release

Name and logo, code and security review, Windows and remote support or a stated lack of it, tests inside VS Code, Marketplace and Open VSX listings, CI for provider version bumps, and a fresh history for the public repository.

## After release

Claude connection settings (API key, Bedrock), and parallel agents through separate lanes.

## What this depends on

- The name is needed by phase 9, and sooner for the repository if a working name will not do.
- Anthropic's answer on subscription use can change phase 9 only; the Claude provider stays separate from the rest.
- Handoff quality on large features is the main unknown. Phase 4 and phase 5 are the first real tests of it, and may change later phases.
