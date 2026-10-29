# Roadmap

AgentDeck has two jobs:

1. **A chat at parity with AFK Pilot**, the strongest multi-provider coding-agent chat for VS Code, on the user's own subscriptions, with native Claude and Codex protocols and ACP for the rest.
2. **Its specialization: a harness for providers, handoffs, and worktrees**, built on lanes ([design](superpowers/specs/2026-10-29-lanes-and-control-center.md)) — multi-repo feature lanes, a main checkout that lanes move into and out of, warm worktrees, lane memory, workflows, and notifications.

Built so far (plans 1–11, [overview](superpowers/plans/2026-10-28-mvp-overview.md)): Claude, Codex, and Grok; sessions with resume; tabs and sidebar; tool, diff, and plan cards; approvals; model and mode pickers; context meter; quota; MCP status and sign-in; guided sign-in and welcome; searchable switcher; turn footers; approval toasts; rich composer with `@`, `/`, attachments, and images; agent questions, plan review, and richer approvals.

## Phase A — chat parity with AFK Pilot

Checklist against AFK Pilot's features (its README, October 2026). ✓ done · ◐ partial · ○ missing · — not planned.

| Feature | Status | Plan |
|---|---|---|
| Questions from the agent (AskUserQuestion, Codex user input, Grok `x.ai/ask_user_question`) | ✓ | 11 |
| Plan review card (Claude ExitPlanMode, Grok `x.ai/exit_plan_mode`) with the next mode to switch to | ✓ | 11 |
| Permission cards with a native diff preview before approval | ✓ *Review changes* on edit approvals | 11 |
| "Allow `npm` for this session" for commands | ✓ | 11 |
| Modes incl. Claude **Auto**, switchable mid-turn | ✓ | 11 |
| Reasoning effort, live | ○ | 12 |
| Queue: edit, remove, merge further typing; **Steer** (Codex, Grok) | ◐ remove only | 12 |
| Drafts kept per chat; prompt history (↑/↓) | ○ | 12 |
| Subagent cards | ○ (`parentId` stored) | 13 |
| Tool batching and summaries ("Explored 5 items", "Edited 2 files"), inline diffs at real line numbers | ◐ | 13 |
| Workflow / deep-research progress cards | ○ | 13 |
| Context and cost popover (billed totals) and Compact | ◐ meter only | 13 |
| LaTeX and Mermaid rendering | ○ | 13 |
| Fork conversation | ○ | 14 |
| Rewind (conversation, optionally files) | ○ | 14 |
| History: unread result badges, rename and delete inline, 30-day list | ◐ | 14 |
| Add to chat from the Explorer and editor context menu; keybinding | ○ | 14 |
| Default to the Secondary Side Bar | ○ | 14 |
| Keep the machine awake while a turn runs | ○ | 14 |
| Voice dictation | ○ | 15 (spike first) |
| More agents: Cursor (`agent acp`), OpenCode, Gemini CLI, Muse, Antigravity | ◐ Grok | 16 |
| Edit provider config files from settings | ○ | 16 |
| Parallel sessions with status dots | ✓ | — |
| Paste and attach images; `@` files; `/` commands | ✓ | — |
| Model picker, live | ✓ | — |
| Changes / safe-to-walk-away view | ○ | covered by lanes (Phase B) |
| Worktree sessions | ○ | superseded by lanes |
| Image and video generation (Grok `/imagine`) | — | not planned |
| Remote control from a phone | — | not planned |
| Desktop app | — | not planned |

Plans:

- **11 — Questions, plan review, and permissions.** First. Its path checks are also the enforcement layer lanes need.
- **12 — Turn controls:** effort, steering, queue editing, drafts, prompt history.
- **13 — Transcript depth:** subagent and workflow cards, tool batching, context and cost, LaTeX, Mermaid.
- **14 — Session operations:** fork, rewind, unread badges, history actions, Explorer context menu, Secondary Side Bar default, keep-awake.
- **15 — Voice dictation:** spike microphone access in a webview first; fall back to a host-side recorder.
- **16 — More agents:** Cursor, OpenCode, Gemini CLI, Muse, Antigravity as ACP specs with recorded fixtures; provider config editing.

## Phase B — lanes (foundations first, minimal UI)

From the [design](superpowers/specs/2026-10-29-lanes-and-control-center.md):

- **17 — Notifications** (independent, can run any time after 11): native events, claude-notifier's sounds and settings, `CLAUDE_NOTIFIER_DISABLE` for spawned CLIs. ✓ done.
- **18 — Workspace and lane tracking:** repo discovery, derived per-repo lane state, Git watchers and reconciliation, chat ↔ lane links, the "main / no lane" group. ✓ done.
- **19 — Lane memory and briefs:** `.agentdeck/` layout, stamping, chat summaries, the brief and the delta in prompts. ✓ done.
- **20 — Switch and warm-up:** the switch steps with stash carry-over and failure handling, worktree creation, bootstrap, chat notices, lane path enforcement (Claude, Codex writable roots, ACP). ✓ done.
- **21 — Lanes in the chat list:** group chats by lane with per-repo location, group actions, composer lane chip, multi-repo *Review changes*. No board or lane pages (decision 36). ✓ done.
- **22 — Workflows inside lanes:** task types and defaults, stages, handoff briefs, *Hand off to…*. ✓ done (as hand-offs; no stage views, decision 36).
- **Later:** PR and review-thread triage, issue linking, cross-lane conflicts, lane preflight, commit/push/PR per repo.

## Phase C — before others use it

- Weekly dependency check in CI (SDK and TipTap bumps run tests and recorded fixtures; open a PR on green).
- "Newer than tested" notices per provider, and prompts to run a CLI's own update command.
- Windows (the Claude sign-in helper is a shell script; process-group stop is untested) and remote (SSH, WSL, dev containers).
- Tests for the VS Code side (surfaces, commands) with `@vscode/test-electron`.
- A full code and security review; then Marketplace publishing (icon, license, CI, changelog).

## Order

Phase A plans 11 → 12 → 13 → 14, with 17 (notifications) slotted in early since it is independent; then Phase B 18 → 22; 15 and 16 when convenient; Phase C before sharing.
