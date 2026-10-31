# Architecture

```
webview/          React chat app (one app for tabs and the sidebar)
   │  messages: src/ui/protocol.ts
src/ui/           VS Code surfaces: chat views, Sessions tree, commands, notifier
src/sessions/     SessionManager: chat lifecycle, queueing, attention events, persistence
   │  ProviderDefinition / ProviderSession: src/core/types.ts
src/providers/    claude/ (Agent SDK), codex/ (app-server), acp/ (every other agent)
src/lanes/        Git-derived lane state, lane memory, switching, coordination
src/notify/       Pure builders for notification text and OS commands
```

`src/extension.ts` wires these together. Only `src/ui/` and `src/extension.ts` import `vscode`; everything else runs in plain Node, so tests and `scripts/` can drive it directly.

## Data flow

1. The composer sends `PromptPart[]` (text, mentions, attachments) to `ChatSurfaces`, which calls `SessionManager`.
2. The manager's `decorate` hook appends the lane brief or delta for the provider only; the transcript keeps the user's message.
3. The provider adapter encodes the parts and drives its CLI.
4. The adapter translates CLI output into `SessionItem`s. The manager journals them and notifies subscribers; `ChatSurfaces` forwards them to the webview.
5. `SessionManager.onAttention` drives notifications (`needs-input`, `turn-ended`, `failed`).

## Rules that constrain changes

| Rule | Why |
|---|---|
| Providers run only through their official CLI; the extension holds no credentials | Auth stays with the vendor. Models, quota, skills, and MCP state therefore come only from what the CLI reports, and quota is shown with its age. |
| The UI renders one item model (`SessionItem`) and shows controls by declared `Capability` | New providers and features meet without special cases. |
| Every chat runs at the workspace root | Provider sessions (Claude's are keyed by folder) always resume; moving a lane never moves a chat. Where to work is an instruction plus a write boundary. |
| Derive Git state, store only intent | Stored descriptions of Git drift. `.agentdeck/` never records where a branch is. |
| The app coordinates; agents never call coordination tools | Orchestration should not spend the agent's context. |
| One writer per lane | Two chats editing one checkout collide. Other prompts queue and wake when the lane frees up. |
| Nothing runs while VS Code is closed | There is no daemon. Sessions resume from provider transcripts and the journal. |
| The CLI starts when a chat opens, not on the first prompt | Pickers and the MCP popover need its facts before the first message. |
| Messages sent during a turn queue until it ends, unless steered | Uniform across providers. |
| Handoffs never advance on their own | Each stage stays a real, reviewable chat. |
| Lanes stay implicit in the UI: no board or lane pages | Controls are added only when a feature needs one. |
| CLIs get `CLAUDE_NOTIFIER_DISABLE=1` | AgentDeck notifies from its own events; this prevents double notifications from those hooks. |

## UI layout

- The chat is one webview: a tab in the secondary sidebar (`agentdeck.chat`), or an editor tab through *Open in Editor*.
- The Sessions tree (`agentdeck.sessions`) is in the primary sidebar, grouped by provider, then lane. Clicking a session opens it in the chat tab.
- **+** is a submenu of per-provider commands, shown by the `agentdeck.installed.<id>` context keys. VS Code allows a submenu once per menu location, so each view has its own.
- Webview menu items that open a VS Code picker must stop the menu returning focus to its trigger (`onCloseAutoFocus`), or the picker closes at once.

## Webview

React, shadcn/ui, AI Elements, and Tailwind v4, loaded as an ES module with code splitting. The composer is TipTap, with `@` mentions, `/` commands, and pills. VS Code webviews have no microphone access, and files dropped on them open as editors, so there is no dictation or drag and drop.

## VS Code facts

- `vscode.window.activeTextEditor` is undefined while a webview has focus; editor context falls back to the last focused file, then any visible file.
- The Agent SDK is ESM and reads `import.meta.url`; the CJS bundle defines it from `__filename` (`esbuild.mjs`).
