# AgentDeck

Chat with coding agents — Claude, Codex, Grok, and any ACP agent — from one place in VS Code, on your own subscriptions.

AgentDeck runs each provider through its official CLI: your installed `claude`, `codex` (on your PATH or bundled with the official Codex extension), and ACP agents such as `grok`. It never reads, stores, or forwards your credentials and never calls provider APIs itself. Sign-in, MCP servers, and their sign-ins stay with each CLI, so anything you set up for the official extensions works here too.

## Features

- **Chats in the sidebar or in tabs.** A chat tab sits in the secondary sidebar, and any chat can open in the editor. The Sessions list groups chats by provider, then branch.
- **Sessions that last.** Close VS Code, come back, and continue. Fork a conversation or rewind to an earlier message.
- **The agent's work, readable.** Streaming replies, reasoning, tool cards, nested subagent steps, diffs, plans, LaTeX, and Mermaid.
- **Questions and approvals.** Answer questions, review plans, and allow or deny actions from the chat.
- **Controls.** Model, permission mode, and reasoning effort; steer a running turn; queue and edit messages; see context use and compact.
- **Lanes.** Chats on a branch share its goal, plan, and notes. Move a lane into your primary checkout or out to a warm worktree, with its uncommitted work. Only one chat writes per lane, and writes stay inside the lane.
- **Hand-offs.** Pass work to a Research, Plan, Build, or Review chat, with any provider.
- **Notifications.** Native sound and popups when a chat finishes, fails, or needs you.
- **MCP.** See every server's state and tools, and sign in from the chat.
- **Your theme.** Every color comes from the active VS Code theme.

## Requirements

- VS Code 1.106 or later.
- For Claude: Claude Code installed and signed in with your claude.ai account (`claude auth status`).
- For Codex: the Codex CLI or the official Codex extension, signed in (`codex login status`).
- For Grok: the Grok CLI from https://x.ai/cli, signed in with `grok login`.
- Cursor, OpenCode, and Gemini are also supported (not yet tested against the real CLIs), and `agentdeck.customAgents` adds other ACP agents.

## Install

AgentDeck is not on the Marketplace yet. Build and sideload it:

```sh
pnpm install
pnpm run package
code --install-extension agentdeck-0.1.0.vsix --force
```

Reload VS Code and open AgentDeck from the activity bar.

## Development

See [AGENTS.md](AGENTS.md) for commands, verification, and architecture links.
