# AgentDeck MVP — plan overview

The MVP scope is the table in the [spec](../specs/2026-10-28-agentdeck-design.md#mvp). It is built by the plans below, in order. Each plan ends with working, tested software and is merged before the next starts.

| # | Plan | Delivers | Status |
|---|---|---|---|
| 1 | [Core and Claude](2026-10-28-mvp-1-core-and-claude.md) | Shared types, env, Claude provider on the item model, journal, session store, session manager, recorded fixture, live smoke through the manager | Done |
| 2 | [Chat app foundation](2026-10-28-mvp-2-chat-app.md) | Webview build (React, Tailwind v4, shadcn, AI Elements), theme bridge, chat in editor tabs and the sidebar wired to the session manager, messages, reasoning, composer, approvals, Stop; removes the POC UI | Done |
| 3 | [Chat items and controls](2026-10-28-mvp-3-items-and-controls.md) | Tool cards, diff cards with *Open diff*, plan, model and mode pickers, context meter, MCP popover with sign-in handoff and reconnect, sessions tree, status bar, provider sign-in check | Done |
| 4 | [Codex](2026-10-28-mvp-4-codex.md) | `codex app-server` client, Codex translator with a recorded fixture, Codex sign-in and MCP handoff | Done |
| 5 | [Release](2026-10-28-mvp-5-release.md) | Theme check on Dark Modern, Light Modern, a high-contrast theme, and one third-party theme; packaging; README | Done |
| 6 | [Sidebar layout and in-app provider choice](2026-10-29-6-sidebar-and-provider-choice.md) | Composer fits the sidebar; provider chooser instead of a quick pick | Done |
| 7 | [ACP provider and Grok](2026-10-29-7-acp-and-grok.md) | Generic ACP provider; Grok with a recorded fixture and live smoke | Done |
| 8 | [Chat and sidebar details](2026-10-29-8-chat-and-sidebar-polish.md) | Quota pill, searchable switcher, working timer, turn footers, approval toasts | Done |
| 9 | [Guided sign-in and welcome](2026-10-29-9-guided-sign-in-and-welcome.md) | Sign-in steps for Claude, Codex, and Grok; welcome screen | Done |
| 10 | [Rich composer](2026-10-29-10-rich-composer.md) | `@` files, `/` commands, attachments, pasted images and text | Done |
| 11 | [Questions, plan review, and permissions](2026-10-29-11-questions-and-permissions.md) | Agent questions, plan approval with the next mode, richer approvals with Review changes, Claude Auto mode | Done |
| 18 | [Workspace and lane tracking](2026-10-29-18-lane-tracking.md) | Repos and checkouts read live from Git, lanes derived from branches, chats linked to lanes, Sessions grouped by lane | Done |

## Conventions for whoever executes a plan

- **Work on a branch**, never on `main`. Plan 1 runs on `mvp`.
- **Follow the plan's tasks in order.** Each step says exactly what to write and what to run. If a command's output differs from the plan's *Expected*, stop and investigate before continuing; do not edit tests to make them pass.
- **Code style** matches the existing code: TypeScript, no semicolons, single quotes, two-space indent, `type` aliases over interfaces except for the provider contracts. Comments only where the code cannot say it: a constraint, a CLI quirk, a non-obvious reason. No comments that narrate the development process.
- **Providers never import `vscode`.** Everything under `src/core`, `src/providers`, and `src/sessions` must run under plain Node so vitest and the smoke script can exercise it.
- **Commit after each task** with the message the task gives. Do not add a `Co-Authored-By` trailer.
- **Commands** run from the repo root (`~/projects/agentdeck`). `pnpm test` runs vitest once; `pnpm typecheck` runs `tsc`; `pnpm build` bundles with esbuild.
- **Live checks** (`node dist/smoke.js`, `node dist/record-claude.js`) use the user's real `claude` login and spend a small amount of their subscription quota. Run them only where a task says to.
