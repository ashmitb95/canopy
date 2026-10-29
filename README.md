# AgentDeck

Chat with coding agents — Claude Code, Codex, and Grok — from one place in VS Code, on your own subscriptions.

AgentDeck runs each provider through its official CLI: your installed `claude`, and `codex` (on your PATH or bundled with the official Codex extension). It never reads, stores, or forwards your credentials and never calls provider APIs itself. Sign-in, MCP servers, and their sign-ins stay with each CLI, so anything you set up for the official extensions works here too.

## Features

- **Chats in tabs or the sidebar.** Open as many as you like side by side; the same chat can show in both places.
- **Sessions that last.** Close VS Code, come back, and continue: history is kept per workspace and the agent resumes its own context.
- **The agent's work, readable.** Streaming replies, reasoning, collapsible tool cards, diffs (open them in VS Code's diff editor), and the agent's plan.
- **Approvals.** Allow once, always allow, or deny; Enter and Esc work from the keyboard.
- **Controls.** Switch model and permission mode mid-chat, see how much context is used, and stop a turn.
- **MCP.** See every server's state and tools; sign in to a server that needs it and reconnect without restarting the chat.
- **Your theme.** Every color comes from the active VS Code theme.

## Requirements

- VS Code 1.95 or later.
- For Claude: Claude Code installed and signed in with your claude.ai account (`claude auth status`).
- For Codex: the Codex CLI or the official Codex extension, signed in (`codex login status`).
- For Grok: the Grok CLI from https://x.ai/cli, signed in with `grok login`.

## Install

AgentDeck is not on the Marketplace yet. Build and sideload it:

```sh
pnpm install
pnpm run package
code --install-extension agentdeck-0.1.0.vsix --force
```

Reload VS Code and open AgentDeck from the activity bar.

## Development

Open this folder in VS Code and press F5: an Extension Development Host opens on `playground/` with other extensions disabled.

- `pnpm test` runs the unit tests; `pnpm typecheck` checks the extension and the webview.
- `pnpm build:preview && pnpm screenshot dark` renders the chat UI with sample data to `dist/preview/` (needs Playwright's headless Chromium); `light` and `hc` render the other themes.
- `node dist/smoke.js [claude|codex|grok]` (after `pnpm build`) drives a real session through the session manager: sign-in check, MCP status, an approved edit, memory across turns, and resume after a simulated reload.
- `node dist/record-claude.js`, `node dist/record-codex.js`, and `node dist/record-grok.js` re-record the translator fixtures in `test/fixtures/`.

## Docs

- [Design spec](docs/superpowers/specs/2026-10-28-agentdeck-design.md) — roadmap, architecture, provider contracts, sessions, UI, theming
- [Roadmap](docs/roadmap.md) — chat parity with AFK Pilot, then lanes and the Control Center
- [Lanes and the Control Center](docs/superpowers/specs/2026-10-29-lanes-and-control-center.md) — AgentDeck's specialization
- [Decisions](docs/decisions.md) — what was decided and why
- [MVP plans](docs/superpowers/plans/2026-10-28-mvp-overview.md) — how the MVP was built
- [Look and feel](docs/design/README.md) — the mockups behind the UI
- [Orca reference notes](docs/research/orca.md) — what we learned from Orca's implementation
