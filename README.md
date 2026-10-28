# AgentDeck

A VS Code extension for chatting with coding agents — Claude Code, Codex, and ACP agents such as Grok — from one place, on your own subscriptions. Each provider runs through its own official CLI; AgentDeck never handles your credentials.

**Status:** MVP in progress. Claude chats run in editor tabs and in the AgentDeck sidebar, persist across reloads, and resume where they left off. Codex, the sessions list, and the model, mode, and MCP controls are next (see the MVP plans).

## Docs

- [Design spec](docs/superpowers/specs/2026-10-28-agentdeck-design.md) — roadmap, architecture, provider contracts, sessions, UI, theming
- [Decisions](docs/decisions.md) — what was decided and why
- [Look and feel](docs/design/README.md) — mockups that lock the visual direction
- [Orca reference notes](docs/research/orca.md) — what we learned from Orca's implementation
- [MVP plans](docs/superpowers/plans/2026-10-28-mvp-overview.md) — the build order and the step-by-step plans

## Try the proof of concept

Requires Node 20+, pnpm, and the `claude` CLI signed in with a claude.ai account (`claude auth status`).

```sh
pnpm install
pnpm run package
code --install-extension agentdeck-0.0.1.vsix --force
```

Reload VS Code, then open the AgentDeck view in the activity bar, or run **AgentDeck: New Claude Chat in Editor** from the command palette.

`pnpm build:preview && pnpm screenshot dark` renders the chat UI with sample data to `dist/preview/screenshot-dark.png` (needs Playwright's headless Chromium).

For development, open this folder in VS Code and press F5: an Extension Development Host opens on `playground/` with other extensions disabled.

## Live check

`node dist/smoke.js [claude|codex]` (after `pnpm build`) drives a real session through the session manager against a temporary folder: it checks sign-in, lists MCP servers before the first prompt, approves an edit, confirms a second turn remembers the first, and resumes the session after a simulated reload.

`node dist/record-claude.js` re-records the translator fixture in `test/fixtures/claude/` from a real edit turn. Run `pnpm test` afterwards. `node dist/record-codex.js` does the same for Codex in `test/fixtures/codex/`.
