# AgentDeck — design

A VS Code extension that runs chat sessions against several coding-agent providers from one place, using each provider's own CLI and the user's own subscription.

## Goals

- Start, chat with, and resume sessions for **Claude Code**, **Codex**, and **any ACP agent** (Grok first) from one extension.
- One login per provider, performed by that provider's official CLI. The extension never reads, stores, or forwards credentials.
- Sessions run in the open workspace folder. Agents manage git worktrees themselves if asked to.
- Sessions survive a VS Code reload: the list persists, and opening a session replays its history and continues the conversation.

## Non-goals (v1)

- Multi-agent coordination (one agent dispatching tasks to others).
- Extension-managed worktrees.
- Multiple accounts per provider.
- Cursor (pending a check of its ACP support).
- Sessions that keep running while VS Code is closed.
- Rewind/fork, slash-command catalogs, MCP configuration UI.
- Polished UX. v1 UI is functional; design comes later.

## Constraints

- **Subscription use goes through the official CLI.** Claude runs via `@anthropic-ai/claude-agent-sdk` with `pathToClaudeCodeExecutable` pointing at the user's installed `claude`; the SDK's bundled CLI binaries are not shipped. Codex runs via the user's `codex app-server`. ACP agents run via their own CLI.
- **Runs where the code is.** `extensionKind: ["workspace"]`, so in Remote-SSH/WSL/tunnels the CLIs run on the remote host next to the files.
- **Orca (MIT) is a reference, not a dependency.** Patterns are adapted from `stablyai/orca`; any adapted code carries Orca's license notice in `NOTICE`.

## Architecture

Everything runs in the extension host process. Each chat is a webview editor tab. No sidecar process.

```
Extension host
├─ CliResolver        finds each CLI on the user's login-shell PATH (or a settings override)
├─ AuthService        reports signed-in state; runs each CLI's own login
├─ Providers
│   ├─ ClaudeProvider   Agent SDK → user's claude
│   ├─ CodexProvider    codex app-server, JSON-RPC over stdio
│   └─ AcpProvider      generic ACP client, one instance per AcpAgentSpec (Grok in v1)
├─ SessionManager     create / resume / stop sessions; owns live handles and status
├─ Journal            per-session append-only log of SessionItems (JSONL)
├─ SessionStore       session index in workspaceState
└─ UI
    ├─ SessionsView     sidebar tree: providers (with sign-in state) → sessions (with status)
    └─ ChatPanel        one webview tab per session

webview ⇄ ChatPanel ⇄ SessionManager ⇄ ProviderSession ⇄ CLI process
```

Dependency direction is strictly downward. Providers know nothing about VS Code UI; the webview knows nothing about providers; SessionManager knows nothing provider-specific.

## Core model

### SessionItem

The UI renders a list of items. Providers emit **upserts**: an item with a stable `id`, which replaces any earlier item with the same `id`. Streaming text is an upsert of a growing message. This item-based model (adapted from Orca's journal) keeps the renderer trivial and makes replay a fold over the log.

```ts
type SessionItem =
  | { kind: 'message'; id; role: 'user' | 'assistant'; text: string; streaming: boolean }
  | { kind: 'thought'; id; text: string; streaming: boolean }
  | { kind: 'tool'; id; title: string; toolKind: 'read' | 'edit' | 'execute' | 'search' | 'fetch' | 'other';
      status: 'pending' | 'running' | 'done' | 'failed'; input?: unknown; output?: string; paths?: string[] }
  | { kind: 'diff'; id; path: string; oldText: string | null; newText: string }
  | { kind: 'plan'; id; entries: { text: string; status: 'pending' | 'in_progress' | 'done' }[] }
  | { kind: 'approval'; id; title: string; detail?: string; options: { id: string; label: string }[];
      resolved?: string }
  | { kind: 'question'; id; questions: { question: string; options: string[]; multi: boolean }[];
      answers?: string[][] }
  | { kind: 'turn'; id; state: 'started' | 'ended'; stopReason?: string; usage?: { input: number; output: number } }
  | { kind: 'error'; id; message: string }
```

`toolKind` and the `plan`/`tool` shapes follow ACP's `session/update` vocabulary, so the ACP provider maps nearly one to one.

### Provider contract

```ts
interface Provider {
  readonly id: 'claude' | 'codex' | string        // ACP agents use their spec id, e.g. 'grok'
  readonly label: string
  authStatus(): Promise<AuthStatus>                // 'signed-in' | 'signed-out' | 'not-installed' | 'unknown'
  signIn(ui: SignInUi): Promise<void>
  models(): Promise<{ id: string; label: string }[]>
  permissionModes(): { id: PermissionMode; label: string }[]
  open(opts: { cwd: string; model?: string; mode?: PermissionMode; resumeId?: string }): Promise<ProviderSession>
}

interface ProviderSession {
  readonly nativeId: string                        // Claude session id | Codex thread id | ACP session id
  prompt(text: string): Promise<void>              // resolves when the turn ends
  cancel(): Promise<void>                          // interrupt the current turn
  setModel(id: string): Promise<void>
  setMode(mode: PermissionMode): Promise<void>
  dispose(): Promise<void>                         // stop the CLI process tree
  onItem: Event<SessionItem>
  onExit: Event<{ error?: string }>
  answer(itemId: string, response: string | string[][]): void   // approval option id or question answers
}

type PermissionMode = 'ask' | 'accept-edits' | 'full-access'
```

Approvals and questions are items the provider emits and then waits on; `answer()` settles them. This keeps the permission round-trip inside one channel instead of a separate callback API.

## Providers

### ClaudeProvider

- `query()` from `@anthropic-ai/claude-agent-sdk` in streaming-input mode: the prompt is an async queue the session pushes user messages into, so one CLI process serves the whole session.
- Options (from Orca's tested base): `pathToClaudeCodeExecutable`, `cwd`, `includePartialMessages: true`, `systemPrompt: { type: 'preset', preset: 'claude_code' }`, `settingSources: ['user', 'project', 'local']`, `resume` when resuming, and `permissionMode` mapped `ask→default`, `accept-edits→acceptEdits`. `full-access` passes the CLI flag `--dangerously-skip-permissions` through `extraArgs` (Orca found the SDK's typed bypass emits a flag older binaries reject).
- **Environment:** inherit the login-shell env. If `ANTHROPIC_API_KEY` is set and the user rejected that key in Claude's global config (`customApiKeyResponses.rejected`, matched by the key's last 20 characters), drop it. Otherwise the headless CLI bills the API key instead of the subscription.
- **Permissions:** `canUseTool` emits an `approval` item (Allow once / Allow always / Deny) and resolves with the user's answer. `AskUserQuestion` arrives through `canUseTool` too; it is emitted as a `question` item and answered via `updatedInput`.
- **Translation:** `stream_event` text/thinking deltas → streaming `message`/`thought`; assistant `tool_use` blocks → `tool` (running); user `tool_result` blocks → `tool` (done/failed); `Edit`/`Write`/`MultiEdit` inputs → `diff`; `TodoWrite` → `plan`; `result` → `turn` ended with usage.
- Controls: `interrupt()`, `setModel()`, `setPermissionMode()` on the query object.
- Models: `supportedModels()` from the query object once open; before a session exists, a static list of aliases (`default`, `opus`, `sonnet`, `haiku`).

### CodexProvider

- Spawns `codex app-server` and speaks JSON-RPC 2.0 over stdio (a ~150-line client; no extra dependency). Request/notification types are generated with `codex app-server generate-ts`, pinned to a tested Codex version, and committed.
- Handshake: `initialize` (clientInfo, `experimentalApi: true`) → `initialized` notification.
- Session: `thread/start { cwd, model, approvalPolicy, sandbox }` or `thread/resume { threadId }`; `turn/start` per prompt; `turn/interrupt` to cancel; `thread/read` is not needed because replay comes from the Journal.
- Modes: `ask` → approval policy `on-request` + `workspace-write` sandbox; `accept-edits` → the same, but the provider answers `item/fileChange/requestApproval` with approve itself instead of emitting an `approval` item; `full-access` → approval policy `never` + `danger-full-access` sandbox.
- **Translation:** `item/agentMessage/delta` → streaming `message`; `item/reasoning/summaryTextDelta` → `thought`; `item/started`/`item/completed` for command executions → `tool` (execute) with `item/commandExecution/outputDelta` appended; file-change items and `item/fileChange/patchUpdated` → `diff`; `turn/plan/updated` → `plan`; `turn/started`/`turn/completed` → `turn`; `thread/tokenUsage/updated` → usage on the turn item.
- **Server requests:** `item/commandExecution/requestApproval` and `item/fileChange/requestApproval` → `approval`; `item/tool/requestUserInput` → `question`.
- Models: `model/list`.

### AcpProvider

- Generic client built on `@agentclientprotocol/sdk` (`ClientSideConnection` over the child's stdio). One provider instance per `AcpAgentSpec`:

```ts
type AcpAgentSpec = {
  id: string; label: string
  command: string; args: (o: { fullAccess: boolean }) => string[]
  env?: Record<string, string>
  loginCommand: string[]                              // run in a terminal by signIn()
  authMethod: (advertised: string[], env: NodeJS.ProcessEnv) => string | undefined
}
```

- v1 ships one spec. Grok: `grok agent [--always-approve] stdio`, login `grok login`, auth method `xai.api_key` if `XAI_API_KEY` is set and advertised, else `cached_token`. More agents (OpenCode, Gemini) are new spec entries.
- Flow: `initialize` (client capabilities: no `fs`, no `terminal`, so the agent uses its own tools) → `authenticate` with the spec's method → `session/new { cwd }` or `session/load` when the agent advertises `loadSession` → `session/prompt` per turn → `session/cancel`.
- `session/update` maps almost directly onto `SessionItem`. `session/request_permission` → `approval`, answered with the chosen option id. Unknown extension notifications are ignored (Orca's per-agent "dialects" are deferred until a concrete gap appears).
- If the agent lacks `loadSession`, resume opens a new session and the chat shows the replayed history with a note that the agent's context was not restored.

## Auth

| Provider | Status check | Sign-in |
|---|---|---|
| Claude | `claude auth status` (JSON: `loggedIn`, `authMethod`) | spawn `claude auth login --claudeai` |
| Codex | `account/read` on a short-lived app-server | spawn `codex login` (local) or `codex login --device-auth` (remote) |
| ACP | `initialize` + `authenticate`; an auth-required error means signed out | `loginCommand` in a VS Code terminal |

**Link capture.** Sign-in links are opened with `vscode.env.openExternal`, which reaches the user's local browser even when the extension host is remote. For Claude, the login process gets `BROWSER` set to a small helper script that writes its URL argument to a temp file the extension watches (Claude discards the helper's stdout). For Codex, the link (or device code) is parsed from the process output. A progress notification shows "Waiting for sign-in…" with Cancel, which kills the login process. On exit, status is re-checked.

## CLI resolution

VS Code launched from the Dock does not have the shell's PATH. `CliResolver` runs `$SHELL -ilc 'command -v <cli>'` once per CLI, caches the absolute path, and re-resolves on the "Refresh providers" command. The same login-shell environment is captured once and used as the base env for every child process. Settings `agentdeck.<provider>.path` override resolution.

## Sessions, persistence, and replay

- **SessionStore** (workspaceState): `{ id, providerId, nativeId, title, createdAt, updatedAt, model, mode }[]`. Title is the first prompt's first line, truncated.
- **Journal**: `<storageUri>/sessions/<id>.jsonl`, one upserted `SessionItem` per line, appended as items arrive (streaming upserts are coalesced and flushed at most every 250 ms and at turn end).
- **Opening a session** folds its journal into the item list and renders it. The CLI process is not started until the user sends a prompt; then the provider opens with `resumeId = nativeId`.
- **Status** (shown in the tree and tab title): `idle`, `running`, `needs-input` (pending approval/question), `error`, `stopped`.
- Closing a chat tab keeps the CLI process alive if a turn is running and stops it once the session is idle. "Stop session" stops it immediately.
- On extension deactivate, all CLI processes are stopped.

## Process lifecycle

Children are spawned with `detached: true` on POSIX so the whole process group can be signalled. Stop is SIGTERM to the group, then SIGKILL after 2 s. On Windows, `taskkill /T /F`. This is a deliberate simplification of Orca's exit-proof ladder; revisit if orphaned processes show up in practice.

## Error handling

| Situation | Behaviour |
|---|---|
| CLI not found | Provider node shows "Not installed" with a link to install docs; new-session action disabled. |
| Signed out | Provider node shows "Sign in"; opening a session for it prompts sign-in first. |
| Auth fails mid-session | `error` item with a Sign in button; session status `error`. |
| CLI exits unexpectedly | `error` item with the last 20 lines of stderr; next prompt reopens with resume. |
| Resume target missing (transcript deleted) | Open a fresh native session; `error` item notes the agent's context was lost; history stays visible. |
| Malformed provider message | Logged to the AgentDeck output channel and skipped; the session continues. |

## UI (functional v1)

- **SessionsView** (activity bar): one node per provider showing auth state, with inline actions *New session* and *Sign in*; sessions listed under their provider, newest first, with status icon. Context menu: Open, Rename, Stop, Delete (removes the index entry and journal only).
- **ChatPanel**: webview editor tab per session. Header: provider, model picker, mode picker. Body: item list. Footer: prompt box with Send / Stop. Approval and question items render inline buttons. `diff` items have an "Open diff" action that opens VS Code's native diff editor.
- Webview built with Preact, bundled by esbuild. On reveal it requests the current item list; afterwards it receives incremental upserts.

## Repo layout

```
src/
  extension.ts            activation, wiring
  cli/resolver.ts         login-shell PATH + env capture
  auth/                   AuthService, browser-capture helper
  providers/
    types.ts              Provider, ProviderSession, SessionItem
    claude/               provider, translate.ts
    codex/                provider, rpc.ts, translate.ts, generated/
    acp/                  provider, specs.ts, translate.ts
  sessions/               manager.ts, store.ts, journal.ts
  process/                spawn + process-group stop
  ui/                     sessions-view.ts, chat-panel.ts
webview/                  Preact chat UI
test/
  fixtures/<provider>/    recorded raw provider streams
```

## Testing

- **Translators** (the riskiest code): unit tests that feed recorded raw streams from `test/fixtures/<provider>/` into each `translate.ts` and assert the resulting `SessionItem` upserts. Fixtures are captured once from real CLI runs.
- **ACP provider**: tested end to end against a fake in-repo ACP agent that scripts updates and permission requests.
- **Codex JSON-RPC client**: tested against a scripted fake stdio peer.
- **Journal**: write/fold round-trip, coalescing, truncated last line tolerated.
- **Activation smoke test** with `@vscode/test-electron`.
- **Live smoke script** (opt-in, not CI): for each installed and signed-in CLI, open a session, send a prompt, confirm a `turn` end item, resume, send again.

Tooling: TypeScript, esbuild, vitest, pnpm.
