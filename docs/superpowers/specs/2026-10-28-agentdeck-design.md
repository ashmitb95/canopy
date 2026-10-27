# AgentDeck — design

A VS Code extension that runs chat sessions against many coding-agent providers from one place, using each provider's own CLI and the user's own subscription.

## Roadmap

The full product is five sub-projects. Each gets its own spec, plan, and implementation cycle.

| # | Sub-project | Delivers |
|---|---|---|
| 1 | **Provider platform** | Provider contract, item model, capability model; Claude, Codex, and generic ACP adapters; agent registry that makes adding an ACP agent a config entry |
| 2 | **Sessions** | Sidebar, persistence, resume, status, attention notifications |
| 3 | Onboarding and sign-in | Provider screen with install/sign-in state, guided sign-in per provider |
| 4 | Chat UI parity | Orca-level chat surface: markdown, tool runs, diff cards, pickers, queued messages, attachments, mentions, context ring, subagents, rewind, find |
| 5 | Power features | Quota display, skills browser, MCP status and tools, permission configuration |

**This spec covers sub-projects 1 and 2.** It ends with Claude, Codex, and Grok usable from a persistent session list. Sub-projects 3–5 build on the contracts defined here; the capability model is what lets them add features without per-provider special cases.

Orca (`stablyai/orca`, MIT) is the reference for behaviour and feature scope, not a dependency. Adapted code carries Orca's license notice in `NOTICE`.

## Goals

- Start, chat with, and resume sessions for Claude Code, Codex, and any ACP agent from one extension.
- Adding a new ACP agent is a registry entry plus fixtures, not new adapter code.
- One login per provider, performed by the provider's official CLI. The extension never reads, stores, or forwards credentials, and never calls provider APIs directly. Quota, skills, MCP status, and models come only from what the CLI reports.
- Sessions run in the open workspace folder. Agents manage git worktrees themselves.
- Sessions survive a VS Code reload: the list persists, and opening a session replays its history and continues the conversation.

## Non-goals (this spec)

- Guided onboarding beyond a sign-in action per provider (sub-project 3).
- Chat UI beyond a functional item renderer (sub-project 4).
- Quota display, skills browser, MCP views, permission rule editing (sub-project 5). This spec defines the capability and event plumbing they will use.
- Multi-agent coordination, extension-managed worktrees, multiple accounts per provider, sessions that run while VS Code is closed.

## Lessons carried from the POC

- The installed `claude` CLI (2.1.111) rejects a permission `allow` without `updatedInput`, although the SDK types mark it optional. Always echo the tool input back.
- The Agent SDK is ESM and reads `import.meta.url`; the CJS extension bundle defines it from `__filename`. The SDK is bundled into the extension; its per-platform CLI binaries are excluded.
- `vscode.window.activeTextEditor` is undefined while a webview or panel has focus; editor context falls back to the last focused file, then any visible file.
- Dropping `ANTHROPIC_API_KEY` from the child env keeps Claude on the claude.ai subscription (`apiKeySource: none`).

## Architecture

Everything runs in the extension host. Each chat is a webview editor tab. No sidecar process. `extensionKind: ["workspace"]`, so in remote windows the CLIs run next to the files.

```
Extension host
├─ Env              login-shell PATH/env capture; CLI path resolution
├─ Registry         provider definitions: built-ins (Claude, Codex) + ACP agent specs
├─ Providers
│   ├─ claude/        Agent SDK → user's claude
│   ├─ codex/         codex app-server, JSON-RPC over stdio
│   └─ acp/           generic ACP client, parameterised by AcpAgentSpec
├─ Sessions
│   ├─ manager        create / open / resume / stop; owns live handles and status
│   ├─ journal        per-session append-only SessionItem log
│   └─ store          session index (workspaceState)
├─ EditorContext    current file + selection for prompts
└─ UI
    ├─ sessions-view  sidebar tree
    └─ chat-panel     webview tab per session (React)

webview ⇄ chat-panel ⇄ SessionManager ⇄ ProviderSession ⇄ CLI process
```

Dependencies point downward only. Providers import nothing from `vscode`, so they run under plain Node for tests and the live smoke script.

## Core model

### SessionItem

The UI renders an ordered list of items. Providers emit **upserts**: an item with a stable `id` replaces any earlier item with that `id`. Streaming text is an upsert of a growing message. Replay is a fold over the journal.

```ts
type SessionItem =
  | { kind: 'message'; id; role: 'user' | 'assistant'; text: string; streaming: boolean }
  | { kind: 'thought'; id; text: string; streaming: boolean }
  | { kind: 'tool'; id; title: string; toolKind: ToolKind; status: 'pending' | 'running' | 'done' | 'failed';
      input?: unknown; output?: string; paths?: string[]; parentId?: string }
  | { kind: 'diff'; id; path: string; oldText: string | null; newText: string; parentId?: string }
  | { kind: 'plan'; id; entries: { text: string; status: 'pending' | 'in_progress' | 'done' }[] }
  | { kind: 'approval'; id; title: string; detail?: string; options: { id: string; label: string }[]; resolved?: string }
  | { kind: 'question'; id; questions: { question: string; options: string[]; multi: boolean }[]; answers?: string[][] }
  | { kind: 'turn'; id; state: 'started' | 'ended'; stopReason?: string; durationMs?: number }
  | { kind: 'notice'; id; level: 'info' | 'warning' | 'error'; text: string; action?: 'sign-in' | 'retry' }

type ToolKind = 'read' | 'edit' | 'execute' | 'search' | 'fetch' | 'think' | 'other'
```

`parentId` links a subagent's tools to the tool call that spawned it, so sub-project 4 can group them; this spec stores it but renders flat. Vocabulary follows ACP's `session/update`, so ACP maps almost one to one.

### Session facts

Facts that are state, not transcript, travel separately so the UI can show them outside the message list (and sub-project 5 can build on them):

```ts
type SessionFact =
  | { kind: 'model'; current: string; available?: { id: string; label: string }[] }
  | { kind: 'mode'; current: PermissionMode; available: { id: PermissionMode; label: string }[] }
  | { kind: 'context'; usedTokens: number; maxTokens?: number }
  | { kind: 'commands'; items: { name: string; description?: string; source: 'skill' | 'command' | 'mcp' }[] }
  | { kind: 'mcp'; servers: { name: string; status: 'connected' | 'failed' | 'pending' | 'needs-auth'; tools?: string[] }[] }
```

Facts are last-value-wins per `kind`, kept in memory, and the latest of each is persisted in the session index so a reopened session shows them before the CLI starts.

### Provider state

Quota belongs to the account, not the session: two Claude chats share one 5-hour window. Sessions report quota upward; the registry keeps the latest per provider and every chat for that provider shows it, including chats whose CLI is not running.

```ts
type ProviderState = {
  status: 'signed-in' | 'signed-out' | 'not-installed' | 'unknown'
  version?: string                                 // CLI version, for display and minimum-version warnings
  account?: string                                 // e.g. the email `claude auth status` reports
  quota?: {
    observedAt: string                             // shown as "as of 3 min ago"
    windows: { label: string; usedPercent?: number; resetsAt?: string; status: 'ok' | 'warning' | 'limited' }[]
  }
}
```

Quota is persisted per provider in globalState so it survives reloads, always shown with its age.

### Capabilities

Each provider declares what it supports. The UI shows a control only when the capability is present, so new providers and new features meet without special cases.

```ts
type Capability =
  | 'resume'          // continue a past session's agent context
  | 'interrupt'
  | 'models' | 'setModel'
  | 'modes' | 'setMode'
  | 'images'          // image attachments in prompts
  | 'commands'        // slash commands / skills list
  | 'mcpStatus'
  | 'quota'           // reports account quota through onQuota
  | 'context'         // emits context-usage facts
```

ACP agents get capabilities from their `initialize` response and the session updates they advertise; built-in providers declare theirs statically.

### Provider contract

```ts
interface ProviderDefinition {
  id: string                                       // 'claude' | 'codex' | ACP spec id
  label: string
  cli: { command: string; installUrl: string }
  capabilities: ReadonlySet<Capability>
  minVersion?: string                              // below this, warn (e.g. CLI quirks the adapter does not handle)
  probe(env: Env): Promise<Omit<ProviderState, 'quota'>>
  signIn(env: Env, ui: SignInUi): Promise<void>
  open(opts: { env: Env; cwd: string; model?: string; mode?: PermissionMode; resumeId?: string }): Promise<ProviderSession>
}

interface ProviderSession {
  readonly nativeId: string                        // Claude session id | Codex thread id | ACP session id
  prompt(input: { text: string; context?: EditorContextBlock; images?: ImageAttachment[] }): Promise<void>
  cancel(): Promise<void>
  setModel?(id: string): Promise<void>
  setMode?(mode: PermissionMode): Promise<void>
  answer(itemId: string, response: string | string[][]): void   // approval option id or question answers
  dispose(): Promise<void>
  onItem: Event<SessionItem>
  onFact: Event<SessionFact>
  onQuota: Event<NonNullable<ProviderState['quota']>>
  onExit: Event<{ error?: string }>
}

type PermissionMode = 'ask' | 'accept-edits' | 'full-access'
```

Approvals and questions are items the provider emits and then waits on; `answer()` settles them.

## Providers

### Claude (built-in)

- `query()` from `@anthropic-ai/claude-agent-sdk` in streaming-input mode: one CLI process per session; prompts are pushed into its input queue.
- Options: `pathToClaudeCodeExecutable`, `cwd`, `env` (login-shell env without `ANTHROPIC_API_KEY`), `includePartialMessages: true`, `systemPrompt: { type: 'preset', preset: 'claude_code' }`, `settingSources: ['user', 'project', 'local']`, `resume` when resuming. Modes: `ask→default`, `accept-edits→acceptEdits`, `full-access` via `extraArgs: { 'dangerously-skip-permissions': null }`.
- `canUseTool` → `approval` item (Allow once / Always allow / Deny; "Always allow" returns the call's `suggestions` as `updatedPermissions`). `AskUserQuestion` → `question` item, answered through `updatedInput`.
- Items: `stream_event` text/thinking deltas → `message`/`thought`; `tool_use` → `tool`; `tool_result` → tool done/failed; `Edit`/`Write`/`MultiEdit` input → `diff`; `TodoWrite` → `plan`; `result` → `turn` ended. Messages with `parent_tool_use_id` set `parentId`.
- Facts: `system/init` → model; `supportedModels()` → model list; `rate_limit_event` → `onQuota`; `getContextUsage()` after each turn → context; `supportedCommands()` → commands; `mcpServerStatus()` → mcp.
- Capabilities: all.

### Codex (built-in)

- Spawns `codex app-server`; JSON-RPC 2.0 over stdio with a small in-repo client. Types generated by `codex app-server generate-ts` against a pinned Codex version and committed.
- `initialize` (`experimentalApi: true`) → `initialized`; `thread/start { cwd, model, approvalPolicy, sandbox }` or `thread/resume { threadId }`; `turn/start` per prompt; `turn/interrupt`.
- Modes: `ask` → `on-request` + `workspace-write`; `accept-edits` → same, but file-change approvals are answered by the adapter; `full-access` → `never` + `danger-full-access`.
- Items: `item/agentMessage/delta` → `message`; `item/reasoning/summaryTextDelta` → `thought`; command execution items + `outputDelta` → `tool` (execute); file-change items + `patchUpdated` → `diff`; `turn/plan/updated` → `plan`; `turn/started|completed` → `turn`. Server requests `item/commandExecution/requestApproval`, `item/fileChange/requestApproval` → `approval`; `item/tool/requestUserInput` → `question`.
- Facts: `model/list` → models; `account/rateLimits/updated` → `onQuota`; `thread/tokenUsage/updated` → context; `skills/list` → commands; `mcpServer/startupStatus/updated` → mcp.
- Capabilities: all except `images` until verified.

### ACP agents (registry)

A generic client on `@agentclientprotocol/sdk` (`ClientSideConnection` over stdio), parameterised by a spec:

```ts
type AcpAgentSpec = {
  id: string; label: string
  command: string; installUrl: string
  args: (o: { fullAccess: boolean }) => string[]
  env?: Record<string, string>
  loginCommand: string[]                                   // run in a terminal by signIn()
  authMethod: (advertised: string[], env: NodeJS.ProcessEnv) => string | undefined
  quirks?: AcpQuirks                                       // optional hooks for agent-specific extensions
}
```

- Flow: `initialize` (no `fs`/`terminal` client capabilities; agents use their own tools) → `authenticate` with the spec's method → `session/new { cwd }` or `session/load` if `loadSession` is advertised → `session/prompt` → `session/cancel`.
- `session/update` → items and facts: message/thought chunks, `tool_call`/`tool_call_update`, `plan`; `available_commands_update` → commands; `current_mode_update` → mode; `config_option_update` → model; `usage_update` → context/quota. `session/request_permission` → `approval`.
- `quirks` is the extension point Orca calls "dialects": hooks to map an agent's non-standard notifications. Empty for v1; added per agent when a fixture shows a gap.
- If `loadSession` is absent, resume opens a new session; history stays visible with a notice that the agent's context was not restored.

**Ramp-up path.** Ships with **Grok** (`grok agent [--always-approve] stdio`, login `grok login`, auth `xai.api_key` if `XAI_API_KEY` is set and advertised, else `cached_token`). Next, in order: OpenCode, Gemini CLI, OMP, Antigravity, then Cursor if it supports ACP. Adding one is: a spec entry, a recorded fixture of a real session, a translator test against it, and quirks only if the test shows a gap.

## Editor context

Each prompt carries the current file and selection as a provider-agnostic block appended to the prompt text: `<editor-context file="src/a.ts" selection="12-30">…selected text…</editor-context>` (selection text capped at 200 lines). The file comes from the active editor, else the last focused file, else any visible file. The composer shows what will be attached, with a toggle to drop it for one prompt.

## Sessions

- **Store** (workspaceState): `{ id, providerId, nativeId, title, createdAt, updatedAt, model, mode, facts }[]`. Title is the first prompt's first line, truncated.
- **Journal**: `<storageUri>/sessions/<id>.jsonl`, one upserted item per line. Streaming upserts are coalesced and flushed at most every 250 ms and at turn end. A truncated last line is ignored on read.
- **Open**: fold the journal and render. The CLI starts on the first prompt, with `resumeId = nativeId`.
- **Status**: `idle`, `running`, `needs-input` (pending approval/question), `error`, `stopped`.
- **Prompting while running** queues the message; it is sent when the turn ends. Claude's streaming input and Codex's `turn/steer` can accept it mid-turn, but v1 holds it client-side for uniform behaviour across providers. Queued messages show as pending items and can be removed before they send (editing them is sub-project 4).
- **Attention**: when a session that is not the focused tab enters `needs-input` or finishes a turn, show a VS Code notification with "Open"; the tree badge updates either way.
- Closing a tab keeps a running turn alive and stops the process once idle. On deactivate, all CLI processes stop.

## Sign-in (minimal; sub-project 3 adds the guided flow)

| Provider | Status (`probe`) | Sign-in |
|---|---|---|
| Claude | `claude auth status` (JSON: `loggedIn`, `email`) + `claude --version` | `claude auth login --claudeai`, link captured via a `BROWSER` helper and opened with `vscode.env.openExternal` |
| Codex | `account/read` on a short-lived app-server | `codex login` (local) or `codex login --device-auth` (remote), link/code parsed from output |
| ACP | `initialize` + `authenticate`; auth-required error → signed out | `loginCommand` in a VS Code terminal |

## Env and process lifecycle

- `Env` runs `$SHELL -ilc` once to capture PATH and environment; CLIs resolve against it, overridable per provider in settings. Refreshed by the "Refresh providers" command.
- Children spawn with `detached: true` on POSIX; stop is SIGTERM to the process group, then SIGKILL after 2 s. Windows uses `taskkill /T /F`.

## Error handling

| Situation | Behaviour |
|---|---|
| CLI not found | Provider shows "Not installed" with its install link; new-session disabled. |
| Signed out | Provider shows "Sign in"; new sessions prompt sign-in first. |
| Auth fails mid-session | `notice` (error, action `sign-in`); status `error`. |
| CLI exits unexpectedly | `notice` with the last 20 stderr lines and action `retry`; next prompt reopens with resume. |
| Resume target missing | Fresh native session; `notice` that agent context was lost; history stays. |
| Malformed provider message | Logged to the AgentDeck output channel and skipped. |

## UI (functional; sub-project 4 builds out the chat surface)

Layout reference: the "AgentDeck UX mockups" canvas (first run, chat tab, providers and sign-in, side by side with attention, chat in the sidebar).

- **Sessions tree** (activity bar container): providers with state (version, account, sign-in action); sessions under each provider, newest first, with status icon and a badge on the container for `needs-input`. Context menu: Open in sidebar, Open in tab, Rename, Stop, Delete.
- **Chat surfaces.** One React chat app renders a session in either place:
  - **Sidebar chat** (`WebviewView`): one session at a time, with a top bar holding the session switcher (new chat per provider + recent sessions), *New chat*, *Open in editor*, and overflow; a compact one-line strip for model, mode, context, and quota.
  - **Editor tab** (`WebviewPanel`): one session per tab, full header; tabs can be split to watch sessions side by side.
  - A session can be shown in several surfaces at once. `SessionManager` keeps a subscriber list per session and fans out every upsert and fact; moving a chat between sidebar and tab changes only which surfaces subscribe, never the running session.
  - The view container is contributed to the activity bar; whether a third-party extension can default it to the secondary sidebar (as the official Claude and Codex extensions appear) is verified during implementation, otherwise users drag it there once.
- **Chat content (v1):** item list; approval/question cards; diff items with "Open diff" (native diff editor); queued messages; composer with editor-context chip, Send, Stop. Layout adapts below ~480 px (compact header).
- **Status bar**: running / needs-input counts; click focuses the sessions tree.

### Component stack and theming

- **React + shadcn/ui** (Radix primitives) + **Tailwind v4**, bundled by esbuild into the webview. Orca also uses shadcn, so its chat components are a close reference.
- **AI Elements** (Vercel's shadcn registry of AI chat components) for the chat surface: Conversation, Message (+ actions), Reasoning, Tool, CodeBlock, Plan/Task, Queue, Confirmation, Context, PromptInput, Loader/Shimmer, Suggestion. Components are copied into `webview/components/ai/` like any shadcn component and adapted to `SessionItem` rather than AI SDK message types.
- **Look and feel** is locked by the "AgentDeck UX mockups" canvas: Dark Modern tokens, 26–34 px provider monogram avatars with a per-provider tint, pill status badges, collapsible tool cards with status badges, tinted diff rows, approval cards with keyboard hints, composer with in-toolbar model/mode pickers and context ring.
- **Theme bridge.** shadcn's CSS variables are defined from VS Code theme variables, so every theme (light, dark, high contrast) applies without per-theme code:

| shadcn token | VS Code variable |
|---|---|
| `--background` | `--vscode-editor-background` (tab) / `--vscode-sideBar-background` (sidebar) |
| `--foreground` | `--vscode-foreground` |
| `--card`, `--popover` | `--vscode-editorWidget-background` |
| `--primary` / `--primary-foreground` | `--vscode-button-background` / `--vscode-button-foreground` |
| `--secondary` | `--vscode-button-secondaryBackground` |
| `--muted-foreground` | `--vscode-descriptionForeground` |
| `--accent` | `--vscode-list-hoverBackground` |
| `--border` | `--vscode-widget-border`, falling back to `--vscode-panel-border` |
| `--input` | `--vscode-input-background` |
| `--ring` | `--vscode-focusBorder` |
| `--destructive` | `--vscode-errorForeground` |
| success / warning / info | `--vscode-testing-iconPassed` / `--vscode-editorWarning-foreground` / `--vscode-charts-blue` |
| status pill backgrounds | the status color via `color-mix(in srgb, <color> 14%, transparent)` |
| diff added / removed rows | `--vscode-diffEditor-insertedLineBackground` / `--vscode-diffEditor-removedLineBackground` |
| code block background | `--vscode-textCodeBlock-background` |
| sidebar list selection | `--vscode-list-activeSelectionBackground` / `--vscode-list-activeSelectionForeground` |
| badges | `--vscode-badge-background` / `--vscode-badge-foreground` |

**The IDE's theme is the only source of color.** The hex values in the mockups are Dark Modern stand-ins; the webview defines no colors of its own except the provider tints. Theme switches apply live: VS Code updates the variables in open webviews.

- **Provider tints** (the monogram avatars) are the one brand-ish color: each provider declares a hue, rendered as `color-mix()` against `--background` so it stays legible on light, dark, and high-contrast themes.
- **Syntax highlighting** in code blocks and diffs: webviews cannot read the active theme's token colors, so code is highlighted with Shiki using a bundled light or dark theme chosen from the `vscode-light` / `vscode-dark` / `vscode-high-contrast` body class. Backgrounds and fonts still come from the IDE theme. Matching the user's exact token colors is a later refinement.
- Verified against Dark Modern, Light Modern, one high-contrast theme, and one popular third-party theme before sub-project 4 is considered done.

- **Native proportions**: `--vscode-font-family` / `--vscode-font-size` for UI text, `--vscode-editor-font-family` for code; `--radius` 8 px (shadcn derives 6 px for controls, 10 px for the composer); dense spacing matching VS Code's lists and widgets.
- **Icons**: `@vscode/codicons`, not lucide.
- **High contrast**: `--vscode-contrastBorder` outlines on cards, inputs, and focus states when set.
- **CSP**: scripts by nonce only; Radix sets styles through the CSSOM, which CSP allows; any library that injects `<style>` elements gets the nonce.

## Repo layout

```
src/
  extension.ts
  env.ts
  editor-context.ts
  providers/
    types.ts            ProviderDefinition, ProviderSession, SessionItem, SessionFact, Capability
    registry.ts
    claude/             provider.ts, translate.ts
    codex/              provider.ts, rpc.ts, translate.ts, generated/
    acp/                provider.ts, translate.ts, specs.ts
  sessions/             manager.ts, journal.ts, store.ts
  process/              spawn + group stop
  ui/                   sessions-tree.ts, chat-surfaces.ts (WebviewView + WebviewPanel hosts), status-bar.ts
webview/
  app/                  React chat app (shared by sidebar and tab)
  components/ui/        shadcn components
  components/ai/        AI Elements components, adapted to SessionItem
  theme.css             VS Code → shadcn token bridge
scripts/smoke.ts        live check per installed, signed-in provider
test/fixtures/<provider>/
```

## Testing

- **Translators**: recorded raw streams from real CLI sessions in `test/fixtures/<provider>/` → expected items and facts. Every provider, including each ACP spec, needs a fixture.
- **ACP client**: end to end against a fake in-repo ACP agent (updates, permission requests, auth-required, missing `loadSession`).
- **Codex RPC client**: against a scripted fake stdio peer.
- **Journal**: write/fold round trip, coalescing, truncated last line.
- **Session manager**: status transitions, resume path, attention events, queued prompts, fan-out to multiple surfaces, provider quota aggregation, with a fake provider.
- **Live smoke** (opt-in): for each installed, signed-in provider: open, prompt, approve an edit, second turn remembers the first, resume after dispose.

Tooling: TypeScript, esbuild, vitest, pnpm, `@vscode/vsce` for sideloadable builds.
