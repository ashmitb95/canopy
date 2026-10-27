# Orca reference notes

[Orca](https://github.com/stablyai/orca) (MIT) is a multi-agent desktop IDE that runs coding agents on the user's own subscriptions. AgentDeck uses it as a reference for behaviour and scope, not as a dependency. Paths below are relative to the Orca repo as of October 2026 (v1.4.214); a local clone lives at `~/projects/orca`.

## Shape

- Electron app, ~31k TypeScript files. A headless runtime (`orcad`, run by `orca serve`) owns worktrees, agent processes, sessions, and accounts; desktop, web, and mobile apps are clients over a typed RPC (`src/shared/rpc-contract/`).
- The agent layers (`src/main/claude`, `codex`, `acp`, `native-chat`) have no Electron imports but depend heavily on Orca's session and journal types, so lifting them means carrying much of Orca. AgentDeck reimplements the parts it needs.

## Agents with a chat UI

`src/shared/native-chat-agent-support.ts`: Claude (and the OpenClaude fork), Codex, and over ACP Grok, OpenCode (1.x and 2.x), OMP, and Antigravity. Orca's other "30+ agents" run only as terminal apps.

## Claude

- Uses `@anthropic-ai/claude-agent-sdk` with `pathToClaudeCodeExecutable` set to the user's installed `claude`; the SDK's bundled per-platform CLIs are excluded (`pnpm-workspace.yaml` `ignoredOptionalDependencies`).
- Base SDK options (`src/main/claude/claude-structured-launch-resolution.ts`): `includePartialMessages: true`, `systemPrompt: { type: 'preset', preset: 'claude_code' }`, `settingSources: ['user', 'project', 'local']`, `supportedDialogKinds: []`, `extraArgs: { 'replay-user-messages': null }`.
- Permission modes: ask → `default`, accept-edits → `acceptEdits`, auto → `auto`; full access passes `--dangerously-skip-permissions` through `extraArgs` because the SDK's typed bypass emits a flag older CLIs reject.
- `claude-rejected-api-key.ts`: if `ANTHROPIC_API_KEY` is set but the user rejected it in Claude's global config (`customApiKeyResponses.rejected`, keyed by the key's last 20 characters), drop it; headless Claude would otherwise bill the key.
- Streaming input: one CLI process per session fed by a user-message queue (`claude-agent-sdk-user-message-queue.ts`).
- Process teardown is an elaborate exit-proof ladder (`claude-agent-sdk-exit-proof.ts`); AgentDeck uses a simpler process-group stop.

## Codex

- Spawns `codex app-server`; JSON-RPC over stdio. Handshake (`src/main/codex/app-server/codex-app-server-handshake.ts`): `initialize` with `clientInfo` and `capabilities.experimentalApi: true`, then `initialized`.
- Methods and notifications Orca relies on: `thread/start`, `thread/resume`, `thread/read`, `turn/start`, `turn/interrupt`, `turn/steer`, `model/list`, `skills/list`, `account/read`; `item/started`, `item/completed`, `item/agentMessage/delta`, `item/reasoning/summaryTextDelta`, `item/commandExecution/outputDelta`, `item/fileChange/patchUpdated`, `turn/plan/updated`, `thread/tokenUsage/updated`, `account/rateLimits/updated`, `mcpServer/startupStatus/updated`; server requests `item/commandExecution/requestApproval`, `item/fileChange/requestApproval`, `item/tool/requestUserInput`.

## ACP

- Generic client plus per-agent launch specs (`src/main/acp/acp-launch-specs.ts`) and "dialects" for agent-specific extensions (`src/main/acp/acp-dialects/`).
- Grok: `grok agent [--always-approve] [--plugin-dir …] stdio`; auth method `xai.api_key` when `XAI_API_KEY` is set and advertised, else `cached_token`; login `grok login`.
- OpenCode: `opencode acp` with `OPENCODE_CLIENT=acp`.
- Session updates handled include `available_commands_update`, `current_mode_update`, `config_option_update`, `usage_update`, `session_info_update`.

## Sign-in

`src/shared/agent-session-sign-in.ts` lists each agent's login command (`claude auth login`, `codex login`, `grok login`, `opencode auth login`, …).

- Claude (`src/main/claude-accounts/claude-login-session.ts`): runs `claude auth login --claudeai` with `BROWSER` set to a helper script that captures the sign-in URL (Claude discards the helper's stdout, so the helper writes elsewhere); Orca shows the link in its own UI. The CLI does the OAuth and keeps the token.
- Codex (`src/main/codex-accounts/codex-login-session.ts`): `codex login`, or `codex login --device-auth` for signing in from another device; link on stderr, device code on stdout.

## Usage and quota

Orca reads Claude's OAuth token from the macOS keychain and calls `https://api.anthropic.com/api/oauth/usage`; for Codex it calls `https://chatgpt.com/backend-api/wham/usage` (`src/main/rate-limits/`). AgentDeck does not do this: it never handles credentials. It uses what the CLIs report instead (Claude SDK `rate_limit_event`; Codex `account/rateLimits/updated`).

## Chat UI

- ~440 component and hook files in `src/renderer/src/components/native-chat/`. React with shadcn (`components.json` at the repo root).
- Normalized transcript ("journal") item kinds in `src/shared/agent-session-journal-types.ts`: message, tool-call, diff, plan, approval, question, status, turn. AgentDeck's `SessionItem` follows the same idea.
- Composer: TipTap 3 with custom inline nodes for skills, file references, and image references (`native-chat-prompt-document.ts`); large pastes become placeholder tokens; drafts persist per chat.

## Dictation

Not provided by any agent protocol. Orca runs its own speech-to-text (`src/main/speech/`): local sherpa-onnx models (Parakeet, Whisper tiny) downloaded on demand, or OpenAI transcription with the user's key.
