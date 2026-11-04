# Changelog

## 1.0.3

- Open in Editor opens the chat, not the providers screen.
- Each delegate's card shows only its own work, and new output stays at the bottom of the chat. Phased plans hand each phase the previous phase's report.
- Read-only roles can write the lane's plan.md and notes.md.
- A delegate's permission request shows inside its card, and its permission mode can be changed from the card. "Don't ask again" holds for Grok and other ACP agents.
- MCP servers an agent starts mid-turn no longer hold up a finished delegate, and a card waiting on background work has Stop waiting.
- The sidebar lists only lanes with chats or uncommitted work, with a status line for each; the rest are in the Lane view.

## 1.0.2

- Marketplace readme shows its images and the chat recording.
- Chats in editor tabs, group chats included, and the lane, setup, and review tabs come back after a reload.
- Conversations in the secondary sidebar lists every chat.
- The secondary sidebar's title button shows the lanes, in place of the provider list.

## 1.0.1

- Marketplace readme images resolve to the files already on GitHub.

## 1.0.0

First usable release.

- Chat with Claude Code and Codex from VS Code, in editor tabs or the Canopy sidebar, on your own subscriptions through each official CLI.
- Sessions persist across reloads and resume where they left off; messages sent while the agent works are queued.
- Streaming replies, reasoning, tool cards, diffs that open in VS Code's diff editor, plans, and approvals with keyboard shortcuts.
- Model and permission-mode pickers, a context meter, and an MCP popover with per-server status, sign-in, and reconnect.
- Sessions list with rename, stop, and delete; running and waiting counts in the status bar.
- Follows the active VS Code theme, including high-contrast themes.
- Questions, plan review, and Auto mode; reasoning effort, steering, drafts, and prompt history.
- Fork, rewind, unread markers, and native notifications.
- Lanes: Git-derived tracking, lane memory and briefs, moving lanes between the primary checkout and worktrees, one writer per lane, write boundaries, and hand-offs.
- ACP agents: Grok, Cursor, OpenCode, Gemini, and custom agents.
