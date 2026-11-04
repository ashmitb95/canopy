# Providers

A provider is a `ProviderDefinition` (`src/core/types.ts`): declared `capabilities` and `modes`, `probe()` for install and sign-in state, and `open()` for a `ProviderSession`. `src/providers/registry.ts` lists them.

Adapters translate CLI output to `SessionItem`s and encode `PromptPart[]` back. Prompts to the user (questions, approvals, plan review) go through `PromptHolder`, and encoders in `prompts.ts` turn each `PromptResponse` into that CLI's reply. `WriteBoundary` (`boundary.ts`) enforces lanes.

## Claude (`claude/`)

Agent SDK pointed at the newest official CLI: `claude` on PATH or the one in the Claude Code extension, whichever reports the higher version.

- The CLI's environment passes through untouched, so the CLI decides how it signs in. The session reports the method as a `signIn` fact, and posts a notice when usage is billed to an API key.
- A permission `allow` must include `updatedInput`, although the SDK types mark it optional.
- Boundary: a PreToolUse hook, which runs in every mode and also blocks `git checkout` and `git switch`.
- Effort: `applyFlagSettings({ effortLevel })`. Steering: push into the streaming input.
- Fork: `forkSession`. Rewind: `enableFileCheckpointing` and `rewindFiles`, then restart with `resume`, `resumeSessionAt`, and `forkSession: true`.

## Codex (`codex/`)

`codex app-server` over JSON-RPC, from PATH or the binary bundled with the newest official Codex extension.

- Boundary: `writableRoots`.
- Effort: `turn/start.effort`. Steering: `turn/steer { threadId, expectedTurnId, input }`.
- Compact: `thread/compact/start`. Fork: `thread/fork`. Rewind: `thread/revert { beforeTurnId }`.
- MCP sign-in: `mcpServer/oauth/login`; Canopy only opens the returned link.
- Print the schema with `codex app-server generate-json-schema --out <dir>` (add `--experimental` for unstable methods).

## ACP agents (`acp/`)

One provider implementation; each agent is an `AcpAgentSpec` in `acp/agents.ts`.

- Permission modes are enforced by the adapter, which answers permission requests itself in *Accept edits* and *Full access*, so modes switch without restarting the agent.
- Boundary: write permission requests outside the lane are rejected, and a notice is posted.
- Cursor runs as `cursor-agent acp`, because Grok's CLI also installs a binary named `agent`. Its blocking `cursor/ask_question` and `cursor/create_plan` get a JSON-RPC error until their formats are verified.
- Users can add agents with the `canopy.customAgents` setting.

Live-checked: Grok. Not yet run against a real CLI: Cursor, OpenCode, Gemini.

## Adding an ACP agent

1. Add an `AcpAgentSpec` to `acp/agents.ts` and to `buildProviders` in `registry.ts`.
2. In `package.json`, add a hidden `canopy.newChat.<id>` command and an entry in both `canopy.newChatMenu.*` submenus, shown when `canopy.installed.<id>`.
3. Add a case to `test/providers/acp-agents.test.ts`.
4. Run `node dist/smoke.js <id>` against the real CLI, and record a fixture.
