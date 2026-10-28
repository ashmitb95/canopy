# Decisions

Settled product and architecture decisions, with the reason for each. The [spec](superpowers/specs/2026-10-28-agentdeck-design.md) is the detailed design; this file is the short "why".

| # | Decision | Why |
|---|---|---|
| 1 | A standalone VS Code extension, not a client of Orca's runtime | Orca's runtime is large and its RPC is internal and fast-moving; a light extension covering the needed features is easier to own. Orca stays a reference ([notes](research/orca.md)). |
| 2 | Subscriptions are used only through each provider's official CLI | Anthropic restricts subscription OAuth tokens in third-party products; driving the user's logged-in CLI keeps auth with the vendor. The extension never reads, stores, or forwards credentials and never calls provider APIs directly. |
| 3 | Claude via the Agent SDK pointed at the user's installed `claude`; Codex via `codex app-server`; everything else via ACP | Native protocols give full fidelity for the two most used providers; ACP makes each further agent a config entry. |
| 4 | One shared item model (`SessionItem`) and a declared capability set per provider | The UI renders one format and shows a control only when the provider supports it, so new providers and new features meet without special cases. |
| 5 | Sessions run in the open workspace folder; agents manage git worktrees themselves | Requiring worktree setup before chatting is the friction to avoid. |
| 6 | One login per provider | Multiple accounts add complexity without a current need. |
| 7 | No multi-agent coordinator for now | The goal is running many providers from one place, not orchestrating them. |
| 8 | Sessions persist and resume across reloads; nothing runs while VS Code is closed | Resume is cheap because providers keep their own transcripts; background running would need a daemon. |
| 9 | Chats render in editor tabs and in the sidebar, from one chat app | Tabs allow side-by-side sessions; the sidebar matches the official Claude and Codex extensions. |
| 10 | Quota, skills, MCP status, and models come only from what the CLI reports | Follows from 2. Trade-off: quota refreshes only while a session runs, so it is shown with its age. |
| 11 | Quota is per provider account, not per session | Two chats on one account share the same limits. |
| 12 | Messages sent while the agent works are queued and sent at turn end | Uniform behaviour across providers. |
| 13 | React + shadcn/ui + AI Elements, Tailwind v4 | Feature-rich chat components (reasoning, tools, plan, queue, confirmation, prompt input); Orca also uses shadcn. |
| 14 | The active VS Code theme is the only source of color | shadcn tokens map to VS Code theme variables, so any theme applies live. Provider tints are the one exception, blended with the background. |
| 15 | Rich composer on TipTap with `@` mentions, `/` commands, and pills; prompts are `PromptPart[]` | Mentions, commands, and attachments survive from composer to provider to transcript; adapters encode parts per provider. |
| 16 | Attachments via *Upload from computer*, workspace picker, and clipboard paste; no drag and drop | VS Code opens dropped files as editors, as in the official extensions. |
| 17 | Voice dictation is an extension feature, not a provider one | No agent protocol offers it; Orca also runs its own speech-to-text. Microphone access from VS Code needs a spike. |
| 18 | Parity target is the official Claude Code and Codex extensions, extended to every capable provider | See the parity table in the spec. |
| 19 | Ship an MVP first: Claude and Codex, sessions, the real UI stack, MCP status with sign-in handoff | A daily-usable build in weeks; building on the final UI stack from the start avoids a throwaway UI. Scope table in the spec. |
| 20 | MCP sign-in is a handoff to the CLI or claude.ai, followed by a reconnect | Follows from 2. The CLIs already share MCP config and tokens with the official extensions, so nothing needs reconnecting in AgentDeck. |
| 21 | The CLI starts when a chat is opened, not on the first prompt | Models and MCP status are available before the first message, which the pickers and the MCP popover need. |
| 22 | Codex runs from `codex` on PATH, else the binary bundled with the newest official Codex extension | Many users have Codex only through its extension; its bundled CLI is the same official binary, and it shares the user's `~/.codex` login. |
| 23 | Codex MCP sign-in goes through `mcpServer/oauth/login`; AgentDeck only opens the returned link | Codex completes the OAuth and keeps the token, which keeps decision 2 intact while giving Codex servers a one-click sign-in. |
| 24 | The webview loads as an ES module with code splitting | Shiki's grammars load on demand, keeping the entry script small. |
| 25 | UI is checked from headless screenshots of a preview build with scripted sessions | Agents and reviewers can verify UI changes without a VS Code window; the manual check covers what the preview cannot (focus, real themes, reloads). |

## Findings from the proof of concept

- The installed `claude` 2.1.111 rejects a permission `allow` without `updatedInput`, although the SDK types mark it optional.
- The Agent SDK is ESM and reads `import.meta.url`; the CJS extension bundle defines it from `__filename`.
- Dropping `ANTHROPIC_API_KEY` from the child environment keeps Claude on the subscription (the session reports `apiKeySource: none`).
- `vscode.window.activeTextEditor` is undefined while a webview or panel has focus; editor context falls back to the last focused file, then any visible file.
