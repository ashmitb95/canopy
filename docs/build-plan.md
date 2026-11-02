# Build plan

How the [roadmap](roadmap.md) and [UI spec](ui-spec.md) get built: the plumbing first, then the UI on top of it. Each phase gets its own detailed plan before work starts, and proof-of-concept code in `poc/` is rewritten into `src/` with tests, not copied.

## Principles

- **A headless core.** Orchestration lives in modules that do not import `vscode`, as `src/lanes/` and `src/sessions/` already do. Everything the UI will do is a call on the core, and everything it will show is an event or state from the core.
- **No UI work until phase 7.** The current UI stays as it is and is not extended. It may lag behind or lose features while the core changes; use the last packaged build for day-to-day work until then.
- **Provable without a window.** Every phase ends with `pnpm check` passing and live scripts against real CLIs. Phase 2 adds a terminal driver, so real features can run through the core long before there is a UI for it.

## Phase 0: Ground work (done)

- Merge `poc/group-chat` and `mvp` into `main`.
- Say "primary checkout" in code and docs.
- Claude terms in the provider: stop removing `ANTHROPIC_API_KEY`, and report the sign-in method as a fact.

**Done when:** tests pass on `main`.

## Phase 1: Lanes engine

- Switching as a transaction, from `poc/swap.ts`: preflight, snapshot, swap, verify, rollback, recovery journal.
- Generic worktree slots with occupancy derived from Git; migrate lane-named worktrees already in use.
- New worktree: reuse a free slot, warm it, rerun setup only when a lockfile changes.
- Warm, cold, and parked lanes. Multi-repo lanes whose primary checkouts hold different lanes are designed and handled here.

**Done when:** every preflight state works, including in a real project with a running dev server, driven from scripts.

## Phase 2: Chat core

- One chat over one session per provider; the journal records who produced each item. Existing chats migrate.
- The ledger, read cursors, and catch-up.
- `@mention` routing and delivery by agent state: steer, end of turn, stop and send, paused, queued, finished.
- Turn-taking and the queue.
- The core's event and state API, designed for the screens in the UI spec.
- A terminal driver: chat, mention, answer, and watch the stream from a terminal.

**Done when:** a small real feature is built by mentioning agents by hand through the driver. This is the largest change to existing code.

## Phase 3: Delegation

- One local tool server for all providers, and the `delegate` tool.
- Roster configuration, and the lead's brief.
- The end-turn-and-wake flow. Detect a lead that says it will delegate but does not, and nudge it once.
- Enforced roles: write block, `git status` backstop, undo.
- Handoffs as ledger views: recorded facts, reports with a status line, saved transcripts.
- Narration instruction, and the compact stream from `poc/rolling.ts` as data for the UI.

**Done when:** a lead delegates by roster on a real feature, on all three providers, through the driver. This is the first real test of handoff quality on larger work, and it may change later phases.

## Phase 4: The lead in charge

- Settling: open tool calls, process tree, working directories, a helper ignore list per provider.
- A verification turn for delegates that started background work.
- Lead events and tools: finished, overdue, server left running; message, stop.
- Permissions always to the user. Questions to the lead first, with a limit on rounds and a setting to send them all to the user. Structured questions and requests pending across a restart.
- Quota as a fact on each provider, warnings before delegating, Grok's source if one exists, and a clear state at a limit, with no automatic switch.

**Done when:** a long feature runs with failures, questions, and limits, and the user stays in control from the driver.

## Phase 5: Review data and integrations

- Per-delegate snapshots, diffs, and undo.
- Who-did-what data for review; create a pull request.
- GitHub through `gh`; Linear with an API key in SecretStorage. The credentials rule in `AGENTS.md` changes here. Issues seed the lane.

**Done when:** an issue goes to a reviewed change through the driver.

## Phase 6: Hardening the core

- Failure and restart tests across phases: crash at each step, CLI death, rate limits, bad sign-in.
- Long sessions, large repos, and event bursts.
- Windows and remote: support them or state the lack of it.
- Freeze the core's API for the UI.

**Done when:** a real feature of your choosing runs end to end on the driver without manual repair.

## Phase 7: UI

The whole UI at once, on the frozen API, from the [UI spec](ui-spec.md), in this order:

1. **Shell:** webview sidebar replacing the Sessions tree, with keyboard navigation, context menus, and palettes.
2. **Chat:** avatars, takeover markers, the `@` menu, queue, composer, delegate cards, rolling window, handoff panel, every delegate state.
3. **Lanes:** the Lanes section, lane view, switching, preflight questions, crash recovery.
4. **Setup:** connect agents, roster, workspace, New Worktree.
5. **Review:** who did what, diffs, undo, the issue picker.
6. **Finishing:** every screen in every palette and in high contrast, narrow sidebars, empty and error states, screen readers, and performance.

Revisit the mockups before starting: the plumbing will have taught us things they got wrong. Webview checks use screenshots, with a manual pass in VS Code.

**Done when:** a walkthrough of every screen finds nothing out of spec, and the driver is no longer needed for day-to-day work.

## Phase 8: Release

Rename to Canopy as v5, with old Canopy kept on a `v3` branch and detection of its `.canopy/` and `canopy.toml` files; logo, provider labels and notices for Claude's terms, code and security review, tests inside VS Code, Marketplace and Open VSX listings, CI for provider version bumps, and a single clean commit into the public `ashmitb95/canopy` repository, replacing the old Marketplace listing.

## After release

Claude connection settings (API key, Bedrock), and parallel agents through separate lanes.
