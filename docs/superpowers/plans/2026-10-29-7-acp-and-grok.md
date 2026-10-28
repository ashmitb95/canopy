# Plan 7: ACP provider and Grok — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first. Plans 1–6 are complete.

**Goal:** Add a generic Agent Client Protocol (ACP) provider and Grok as its first agent, so Grok chats run in AgentDeck like Claude and Codex chats: streaming replies and reasoning, tool cards, diffs, approvals, models, context, and resume.

**Architecture:** `acpProvider(spec)` turns an `AcpAgentSpec` (command, install folders, auth method, sign-in check) into a `ProviderDefinition`, so the next ACP agent is a spec entry plus a fixture. `AcpSession` spawns the agent (`grok agent stdio`), speaks JSON-RPC 2.0 through the shared `RpcPeer`, and feeds `session/update` notifications to `AcpTranslator`. Permission requests become approval items; in *Accept edits* and *Full access* the adapter answers them itself, so modes switch without restarting the agent. Resume uses `session/load` with the replayed history muted, since the journal already has it.

**Tech Stack:** as before; no new dependencies (the ACP subset is hand-typed from the protocol and a recorded session).

**What was verified before writing this plan** (2026-10-29, `grok 1.0.70` at `~/.grok/bin/grok`, signed in with `grok login`):
- `initialize { protocolVersion: 1, clientCapabilities: { fs: { readTextFile: false, writeTextFile: false }, terminal: false } }` returns `agentCapabilities.loadSession: true` and `authMethods` `cached_token` and `grok.com`. `authenticate { methodId: 'cached_token' }` succeeds.
- `session/new { cwd, mcpServers: [] }` returns `{ sessionId, models: { currentModelId: 'grok-4.7', availableModels: [{ modelId, name, description, _meta: { totalContextTokens: 256000 } }] }, configOptions }`.
- An edit turn sent `session/update` notifications: `agent_thought_chunk` and `agent_message_chunk` (`content: { type: 'text', text }`), `tool_call` (`toolCallId`, `title` such as `grep`, `rawInput`, `_meta['x.ai/tool'] = { name, kind, label }`), `tool_call_update` (`kind`, `title`, `status: 'completed'`, `content` with `{ type: 'content', content: { type: 'text' } }` or `{ type: 'diff', path, oldText, newText }`), `session_info_update`, and `available_commands_update`.
- The edit asked `session/request_permission { toolCall: { toolCallId, kind: 'edit', title: 'Edit `/path`' }, options: [{ optionId: 'allow-edits-session', kind: 'allow_always' }, { optionId: 'allow-once', kind: 'allow_once' }, { optionId: 'reject-once', kind: 'reject_once' }] }`, answered with `{ outcome: { outcome: 'selected', optionId } }`.
- `session/prompt` resolved at turn end with `{ stopReason: 'end_turn', _meta: { totalTokens } }`.
- Grok also sends many `_x.ai/*` notifications. One of them (`_x.ai/mcp/servers_updated`) carries the user's MCP server configuration **including environment variables such as API keys**. The fixture recorder must keep only `session/update` content and the stop reason.
- Orca's Grok spec: `grok agent [--always-approve] stdio`, login `grok login`, auth `xai.api_key` when `XAI_API_KEY` is set and advertised, else `cached_token`; model switching via `session/set_model`, falling back to `session/set_config_option`.

---

## File structure

| File | Responsibility |
|---|---|
| `src/providers/rpc.ts` | JSON-RPC peer shared by Codex and ACP (moved from `codex/rpc.ts`; adds an optional envelope) |
| `src/providers/acp/spec.ts` | `AcpAgentSpec`, CLI lookup |
| `src/providers/acp/agents.ts` | The Grok spec |
| `src/providers/acp/translate.ts` | `session/update` → `SessionItem`s |
| `src/providers/acp/provider.ts` | `acpProvider(spec)` and `AcpSession` |
| `src/providers/registry.ts` | Adds Grok |
| `webview/app/components/provider-avatar.tsx` | Grok monogram |
| `scripts/record-grok.ts`, `test/fixtures/grok/edit-turn.jsonl` | Recorded fixture |

---

### Task 1: Share the JSON-RPC peer

**Files:**
- Move: `src/providers/codex/rpc.ts` → `src/providers/rpc.ts`; `test/providers/codex-rpc.test.ts` → `test/providers/rpc.test.ts`
- Modify: `src/providers/codex/provider.ts`, `scripts/record-codex.ts` (imports)

- [ ] **Step 1: Move**

```bash
git mv src/providers/codex/rpc.ts src/providers/rpc.ts
git mv test/providers/codex-rpc.test.ts test/providers/rpc.test.ts
```

Fix imports: in `src/providers/rpc.ts`, `import { Emitter } from '../core/emitter'`; in `src/providers/codex/provider.ts`, `import { RpcPeer, type ServerRequest } from '../rpc'`; in `scripts/record-codex.ts`, `import { RpcPeer } from '../src/providers/rpc'`; in `test/providers/rpc.test.ts`, `import { RpcPeer } from '../../src/providers/rpc'`.

Run: `pnpm test && pnpm typecheck` → PASS; clean.

- [ ] **Step 2: Write the failing envelope test**

In `test/providers/rpc.test.ts`, add inside the `describe` block:

```ts
  it('adds the envelope to every outgoing message', async () => {
    const fromServer = new PassThrough()
    const toServer = new PassThrough()
    const peer = new RpcPeer(fromServer, toServer, { envelope: { jsonrpc: '2.0' } })
    const sent: unknown[] = []
    toServer.setEncoding('utf8')
    toServer.on('data', (chunk: string) => sent.push(...chunk.split('\n').filter(Boolean).map((line) => JSON.parse(line))))
    void peer.request('initialize', { protocolVersion: 1 })
    peer.notify('session/cancel', { sessionId: 's' })
    await new Promise((resolve) => setImmediate(resolve))
    expect(sent).toEqual([
      { jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: 1 } },
      { jsonrpc: '2.0', method: 'session/cancel', params: { sessionId: 's' } }
    ])
  })
```

Run: `pnpm test test/providers/rpc.test.ts` → FAIL (no `jsonrpc` field).

- [ ] **Step 3: Implement**

In `src/providers/rpc.ts`:
- change the class doc comment to `/** Newline-delimited JSON-RPC over a child's stdio. Codex omits the "jsonrpc" field; ACP agents expect it via the envelope. */`;
- replace the constructor with:

```ts
  private readonly log: (message: string) => void
  private readonly envelope: Record<string, string>

  constructor(
    input: Readable,
    private readonly output: Writable,
    options: { log?: (message: string) => void; envelope?: Record<string, string> } = {}
  ) {
    this.log = options.log ?? (() => {})
    this.envelope = options.envelope ?? {}
    input.setEncoding('utf8')
    input.on('data', (chunk: string) => this.receive(chunk))
  }
```

- change `write` to `this.output.write(`${JSON.stringify({ ...this.envelope, ...message })}\n`)`.

Run: `pnpm test && pnpm typecheck` → PASS; clean.

- [ ] **Step 4: Commit**

```bash
git add -A src scripts test
git commit -m "refactor: share the JSON-RPC peer and let ACP add the jsonrpc field"
```

---

### Task 2: Agent specs and CLI lookup

**Files:**
- Create: `src/providers/acp/spec.ts`, `src/providers/acp/agents.ts`
- Test: `test/providers/acp-spec.test.ts`

- [ ] **Step 1: Write the failing test**

`test/providers/acp-spec.test.ts`:

```ts
import { chmodSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { grok } from '../../src/providers/acp/agents'
import { findAgentCli } from '../../src/providers/acp/spec'

function executable(path: string): string {
  mkdirSync(join(path, '..'), { recursive: true })
  writeFileSync(path, '#!/bin/sh\n')
  chmodSync(path, 0o755)
  return path
}

describe('ACP agent specs', () => {
  it('finds the CLI on PATH, then in the installer folder', () => {
    const root = mkdtempSync(join(tmpdir(), 'agentdeck-acp-'))
    const installed = executable(join(root, 'home', '.grok', 'bin', 'grok'))
    expect(findAgentCli(grok, { PATH: '' }, join(root, 'home'))).toBe(installed)
    const onPath = executable(join(root, 'bin', 'grok'))
    expect(findAgentCli(grok, { PATH: join(root, 'bin') }, join(root, 'home'))).toBe(onPath)
    expect(findAgentCli(grok, { PATH: '' }, join(root, 'nobody'))).toBeNull()
  })

  it('prefers an API key from the environment, then the cached sign-in', () => {
    expect(grok.authMethod(['cached_token', 'xai.api_key'], { XAI_API_KEY: 'k' })).toBe('xai.api_key')
    expect(grok.authMethod(['cached_token', 'grok.com'], { XAI_API_KEY: 'k' })).toBe('cached_token')
    expect(grok.authMethod(['grok.com'], {})).toBeUndefined()
  })

  it('treats a cached token or an API key as signed in', () => {
    const home = mkdtempSync(join(tmpdir(), 'agentdeck-grok-home-'))
    expect(grok.signedIn({}, home)).toBe(false)
    expect(grok.signedIn({ XAI_API_KEY: 'k' }, home)).toBe(true)
    mkdirSync(join(home, '.grok'))
    writeFileSync(join(home, '.grok', 'auth.json'), '{}')
    expect(grok.signedIn({}, home)).toBe(true)
  })
})
```

Run: `pnpm test test/providers/acp-spec.test.ts` → FAIL (cannot resolve `agents`).

- [ ] **Step 2: Implement**

`src/providers/acp/spec.ts`:

```ts
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { type Env, findOnPath } from '../../env'

/** Everything AgentDeck needs to know about one ACP agent; the protocol handling is shared. */
export type AcpAgentSpec = {
  id: string
  label: string
  command: string
  installUrl: string
  /** Arguments that start the agent's ACP server on stdio. */
  args: string[]
  /** Arguments to the CLI that sign in, run in a terminal. */
  loginArgs: string[]
  /** Where the agent's installer puts the CLI, checked after PATH. */
  installDirs: (home: string) => string[]
  /** Which advertised auth method to use without prompting; undefined skips `authenticate`. */
  authMethod: (advertised: string[], env: Env) => string | undefined
  /** Whether the CLI has a usable sign-in, without starting it. */
  signedIn: (env: Env, home: string) => boolean
}

export function findAgentCli(spec: AcpAgentSpec, env: Env, home: string): string | null {
  const onPath = findOnPath(env, spec.command)
  if (onPath) return onPath
  const name = process.platform === 'win32' ? `${spec.command}.exe` : spec.command
  return spec.installDirs(home).map((dir) => join(dir, name)).find((path) => existsSync(path)) ?? null
}
```

`src/providers/acp/agents.ts`:

```ts
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import type { AcpAgentSpec } from './spec'

export const grok: AcpAgentSpec = {
  id: 'grok',
  label: 'Grok',
  command: 'grok',
  installUrl: 'https://x.ai/cli',
  args: ['agent', 'stdio'],
  loginArgs: ['login'],
  installDirs: (home) => [join(home, '.grok', 'bin')],
  authMethod: (advertised, env) =>
    env.XAI_API_KEY?.trim() && advertised.includes('xai.api_key')
      ? 'xai.api_key'
      : advertised.includes('cached_token')
        ? 'cached_token'
        : undefined,
  signedIn: (env, home) => Boolean(env.XAI_API_KEY?.trim()) || existsSync(join(home, '.grok', 'auth.json'))
}
```

- [ ] **Step 3: Verify and commit**

Run: `pnpm test && pnpm typecheck` → PASS; clean.

```bash
git add src/providers/acp test/providers/acp-spec.test.ts
git commit -m "feat(acp): add agent specs and the Grok entry"
```

---

### Task 3: ACP translator

**Files:**
- Create: `src/providers/acp/translate.ts`
- Test: `test/providers/acp-translate.test.ts`

Rules:
- Text and thought chunks carry no ids. Consecutive chunks of one kind form one item (`<turn>:m<n>`); any other update ends it.
- A tool's title is `<verb> <target>`: the verb is the agent's tool label (Grok's `_meta['x.ai/tool'].label`) or one derived from the ACP `kind`; the target is the ACP title without backticks. A title that already starts with the verb is kept as is.
- `diff` content becomes `diff` items; `content` text becomes the tool output.
- A turn ends from the `session/prompt` result (`endTurn`) or its failure (`failTurn`); `cancelled` reads as interrupted.

- [ ] **Step 1: Write the failing test**

`test/providers/acp-translate.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import { AcpTranslator, type SessionUpdate } from '../../src/providers/acp/translate'

function run(updates: SessionUpdate[], end?: (translator: AcpTranslator) => void) {
  const latest = new Map<string, SessionItem>()
  const translator = new AcpTranslator((item) => latest.set(item.id, item))
  translator.startTurn()
  for (const update of updates) translator.feed(update)
  end?.(translator)
  return [...latest.values()].filter((item) => item.kind !== 'turn')
}

const text = (sessionUpdate: 'agent_message_chunk' | 'agent_thought_chunk', value: string): SessionUpdate => ({
  sessionUpdate,
  content: { type: 'text', text: value }
})
const grokTool = (name: string, kind: string, label: string) => ({ 'x.ai/tool': { name, kind, label } })

describe('AcpTranslator', () => {
  it('joins consecutive chunks into one message and one thought', () => {
    const items = run(
      [text('agent_thought_chunk', 'The '), text('agent_thought_chunk', 'file'), text('agent_message_chunk', 'Re'), text('agent_message_chunk', 'placed.')],
      (translator) => translator.endTurn('end_turn')
    )
    expect(items).toEqual([
      expect.objectContaining({ kind: 'thought', text: 'The file', streaming: false }),
      expect.objectContaining({ kind: 'message', role: 'assistant', text: 'Replaced.', streaming: false })
    ])
  })

  it('starts a new message after a tool call', () => {
    const items = run([
      text('agent_message_chunk', 'Looking.'),
      { sessionUpdate: 'tool_call', toolCallId: 't1', title: 'grep', rawInput: { pattern: 'x' }, _meta: grokTool('grep', 'search', 'Search') },
      text('agent_message_chunk', 'Done.')
    ])
    expect(items.filter((item) => item.kind === 'message').map((item) => item.kind === 'message' && item.role === 'assistant' && item.text)).toEqual([
      'Looking.',
      'Done.'
    ])
  })

  it('builds tool titles from the label and the target', () => {
    const items = run([
      { sessionUpdate: 'tool_call', toolCallId: 't1', title: 'grep', rawInput: { pattern: 'hello' }, _meta: grokTool('grep', 'search', 'Search') },
      { sessionUpdate: 'tool_call_update', toolCallId: 't1', kind: 'search', title: 'hello world' },
      {
        sessionUpdate: 'tool_call_update',
        toolCallId: 't1',
        status: 'completed',
        content: [{ type: 'content', content: { type: 'text', text: 'found 1 matches' } }]
      }
    ])
    expect(items).toEqual([
      {
        kind: 'tool',
        id: 't1',
        title: 'Search hello world',
        toolKind: 'search',
        status: 'done',
        input: { pattern: 'hello' },
        output: 'found 1 matches'
      }
    ])
  })

  it('turns diff content into diff items and keeps edit titles readable', () => {
    const items = run([
      { sessionUpdate: 'tool_call', toolCallId: 't2', title: 'search_replace', _meta: grokTool('search_replace', 'edit', 'Edit') },
      {
        sessionUpdate: 'tool_call_update',
        toolCallId: 't2',
        kind: 'edit',
        title: 'Edit `/w/notes.md`',
        status: 'completed',
        locations: [{ path: '/w/notes.md' }],
        content: [{ type: 'diff', path: '/w/notes.md', oldText: 'hello world', newText: 'goodbye world' }]
      }
    ])
    expect(items).toEqual([
      expect.objectContaining({ kind: 'tool', id: 't2', title: 'Edit /w/notes.md', toolKind: 'edit', status: 'done', paths: ['/w/notes.md'] }),
      { kind: 'diff', id: 't2:diff:0', path: '/w/notes.md', oldText: 'hello world', newText: 'goodbye world' }
    ])
  })

  it('marks failed tools', () => {
    const items = run([
      { sessionUpdate: 'tool_call', toolCallId: 't3', title: 'Run tests', kind: 'execute', status: 'in_progress' },
      { sessionUpdate: 'tool_call_update', toolCallId: 't3', status: 'failed' }
    ])
    expect(items[0]).toMatchObject({ title: 'Run tests', toolKind: 'execute', status: 'failed' })
  })

  it('keeps the plan as one item', () => {
    const items = run([
      { sessionUpdate: 'plan', entries: [{ content: 'Read', priority: 'medium', status: 'completed' }, { content: 'Fix', priority: 'high', status: 'in_progress' }] }
    ])
    expect(items).toEqual([
      {
        kind: 'plan',
        id: 'plan',
        entries: [
          { text: 'Read', status: 'done' },
          { text: 'Fix', status: 'in_progress' }
        ]
      }
    ])
  })

  it('ends turns from the prompt result', () => {
    const latest = new Map<string, SessionItem>()
    const translator = new AcpTranslator((item) => latest.set(item.id, item))
    translator.startTurn()
    translator.endTurn('cancelled')
    expect([...latest.values()]).toEqual([expect.objectContaining({ kind: 'turn', state: 'ended', stopReason: 'interrupted' })])
    translator.startTurn()
    translator.failTurn('Rate limited')
    expect([...latest.values()].at(-1)).toMatchObject({ kind: 'notice', level: 'error', text: 'Rate limited' })
  })

  it('ignores updates it does not show', () => {
    expect(run([{ sessionUpdate: 'available_commands_update' }, { sessionUpdate: 'session_info_update' }])).toEqual([])
  })
})
```

Run: `pnpm test test/providers/acp-translate.test.ts` → FAIL (cannot resolve `translate`).

- [ ] **Step 2: Implement**

`src/providers/acp/translate.ts`:

```ts
import { randomUUID } from 'node:crypto'
import type { AssistantMessage, SessionItem, Thought, ToolItem, ToolKind } from '../../core/types'

type TextBlock = { type: string; text?: string }
type ToolContent =
  | { type: 'content'; content: TextBlock }
  | { type: 'diff'; path: string; oldText?: string | null; newText: string }
  | { type: 'terminal'; terminalId: string }

type ToolFields = {
  toolCallId: string
  title?: string | null
  kind?: string | null
  status?: string | null
  rawInput?: unknown
  content?: ToolContent[] | null
  locations?: { path: string }[] | null
  _meta?: Record<string, unknown> | null
}

export type SessionUpdate =
  | { sessionUpdate: 'agent_message_chunk' | 'agent_thought_chunk'; content: TextBlock }
  | ({ sessionUpdate: 'tool_call' | 'tool_call_update' } & ToolFields)
  | { sessionUpdate: 'plan'; entries: { content: string; priority?: string; status: 'pending' | 'in_progress' | 'completed' }[] }
  | { sessionUpdate: 'available_commands_update' | 'session_info_update' | 'current_mode_update' | 'usage_update' }

/** Tool output kept in the transcript. */
const MAX_OUTPUT = 20_000

const KINDS: Record<string, ToolKind> = {
  read: 'read',
  edit: 'edit',
  delete: 'edit',
  move: 'edit',
  search: 'search',
  execute: 'execute',
  fetch: 'fetch'
}

const VERBS: Record<ToolKind, string> = {
  read: 'Read',
  edit: 'Edit',
  execute: 'Run',
  search: 'Search',
  fetch: 'Fetch',
  mcp: 'MCP',
  other: 'Tool'
}

const STATUS: Record<string, ToolItem['status']> = {
  pending: 'running',
  in_progress: 'running',
  completed: 'done',
  failed: 'failed'
}

/** Turns ACP `session/update` notifications into session items. Facts are the provider's job. */
export class AcpTranslator {
  private readonly items = new Map<string, SessionItem>()
  private turnId = ''
  private chunks = 0
  private stream: AssistantMessage | Thought | undefined
  private interruptRequested = false

  constructor(private readonly emit: (item: SessionItem) => void) {}

  startTurn(): void {
    this.turnId = `turn:${randomUUID()}`
    this.chunks = 0
    this.stream = undefined
    this.interruptRequested = false
    this.upsert({ kind: 'turn', id: this.turnId, state: 'started' })
  }

  interrupted(): void {
    this.interruptRequested = true
  }

  endTurn(stopReason: string): void {
    this.closeStream()
    const reason = stopReason === 'cancelled' || this.interruptRequested ? 'interrupted' : stopReason
    this.upsert({ kind: 'turn', id: this.turnId, state: 'ended', stopReason: reason })
  }

  failTurn(message: string): void {
    this.closeStream()
    this.upsert({ kind: 'turn', id: this.turnId, state: 'ended', stopReason: 'error' })
    this.upsert({ kind: 'notice', id: `${this.turnId}:error`, level: 'error', text: message })
  }

  feed(update: SessionUpdate): void {
    switch (update.sessionUpdate) {
      case 'agent_message_chunk':
        return this.chunk('message', update.content.text ?? '')
      case 'agent_thought_chunk':
        return this.chunk('thought', update.content.text ?? '')
      case 'tool_call':
      case 'tool_call_update':
        this.closeStream()
        return this.tool(update)
      case 'plan':
        this.closeStream()
        return this.upsert({
          kind: 'plan',
          id: 'plan',
          entries: update.entries.map((entry) => ({
            text: entry.content,
            status: entry.status === 'completed' ? 'done' : entry.status
          }))
        })
    }
  }

  private chunk(kind: 'message' | 'thought', text: string): void {
    if (this.stream?.kind !== kind) {
      this.closeStream()
      const id = `${this.turnId}:m${++this.chunks}`
      this.stream =
        kind === 'message'
          ? { kind: 'message', id, role: 'assistant', text: '', streaming: true }
          : { kind: 'thought', id, text: '', streaming: true }
    }
    this.stream = { ...this.stream, text: this.stream.text + text }
    this.upsert(this.stream)
  }

  private closeStream(): void {
    if (!this.stream) return
    this.upsert({ ...this.stream, streaming: false })
    this.stream = undefined
  }

  private tool(update: ToolFields): void {
    const current = this.items.get(update.toolCallId)
    const previous = current?.kind === 'tool' ? current : undefined
    const label = toolLabel(update._meta)
    const kind = KINDS[update.kind ?? label?.kind ?? ''] ?? previous?.toolKind ?? 'other'
    const verb = label?.label ?? previous?.title.split(' ')[0] ?? VERBS[kind]
    const target = update.title?.replaceAll('`', '').trim()
    const title = target ? (target.startsWith(verb) ? target : `${verb} ${target}`) : (previous?.title ?? verb)
    const text = (update.content ?? [])
      .flatMap((block) => (block.type === 'content' && block.content.text ? [block.content.text] : []))
      .join('\n')
    const paths = update.locations?.map((location) => location.path) ?? previous?.paths
    const input = update.rawInput ?? previous?.input
    const output = text ? text.slice(0, MAX_OUTPUT) : previous?.output
    this.upsert({
      kind: 'tool',
      id: update.toolCallId,
      title,
      toolKind: kind,
      status: STATUS[update.status ?? ''] ?? previous?.status ?? 'running',
      ...(input !== undefined ? { input } : {}),
      ...(output ? { output } : {}),
      ...(paths?.length ? { paths } : {})
    })
    ;(update.content ?? []).forEach((block, index) => {
      if (block.type !== 'diff') return
      this.upsert({
        kind: 'diff',
        id: `${update.toolCallId}:diff:${index}`,
        path: block.path,
        oldText: block.oldText ?? null,
        newText: block.newText
      })
    })
  }

  private upsert(item: SessionItem): void {
    this.items.set(item.id, item)
    this.emit(item)
  }
}

/** Grok labels its tools in `_meta['x.ai/tool']`; other agents rely on the ACP kind. */
function toolLabel(meta: Record<string, unknown> | null | undefined): { label?: string; kind?: string } | undefined {
  const tool = meta?.['x.ai/tool'] as { label?: unknown; kind?: unknown } | undefined
  if (!tool) return undefined
  return {
    label: typeof tool.label === 'string' ? tool.label : undefined,
    kind: typeof tool.kind === 'string' ? tool.kind : undefined
  }
}
```

- [ ] **Step 3: Verify and commit**

Run: `pnpm test && pnpm typecheck` → PASS; clean. If a translator test fails, report the received items rather than changing the test.

```bash
git add src/providers/acp/translate.ts test/providers/acp-translate.test.ts
git commit -m "feat(acp): translate session updates into session items"
```

---

### Task 4: ACP provider

**Files:**
- Create: `src/providers/acp/provider.ts`

`AcpSession` is exercised by the fixture test and the live smoke in Task 5; its parts (RPC peer, translator, process control, spec) are unit-tested.

- [ ] **Step 1: Write the provider**

`src/providers/acp/provider.ts`:

```ts
import { type ChildProcess, execFile } from 'node:child_process'
import { homedir } from 'node:os'
import { promisify } from 'node:util'
import { Emitter } from '../../core/emitter'
import type {
  ApprovalItem,
  ApprovalOption,
  ModelOption,
  OpenOptions,
  PermissionMode,
  PromptPart,
  ProviderDefinition,
  ProviderSession,
  ProviderState,
  SessionFact,
  SessionItem
} from '../../core/types'
import type { Env } from '../../env'
import { spawnGroup, stopGroup } from '../../process'
import { encodePrompt } from '../encode'
import { RpcPeer, type ServerRequest } from '../rpc'
import { type AcpAgentSpec, findAgentCli } from './spec'
import { AcpTranslator, type SessionUpdate } from './translate'

const run = promisify(execFile)

const MODE_LIST: readonly PermissionMode[] = ['ask', 'accept-edits', 'full-access']
const STDERR_TAIL = 4000

type AcpModel = { modelId: string; name: string; description?: string | null; _meta?: { totalContextTokens?: number } | null }
type SessionResult = { sessionId?: string; models?: { currentModelId: string; availableModels: AcpModel[] } | null }
type PermissionOption = { optionId: string; name: string; kind: 'allow_once' | 'allow_always' | 'reject_once' | 'reject_always' }
type PermissionRequest = { toolCall: { toolCallId: string; title?: string | null; kind?: string | null }; options: PermissionOption[] }

const selected = (optionId: string) => ({ outcome: { outcome: 'selected', optionId } })
const CANCELLED = { outcome: { outcome: 'cancelled' } }

const APPROVAL_TITLES: Record<string, string> = { edit: 'edit this file', execute: 'run this command', fetch: 'fetch this' }

function home(env: Env): string {
  return env.HOME ?? homedir()
}

export function acpProvider(spec: AcpAgentSpec): ProviderDefinition {
  return {
    id: spec.id,
    label: spec.label,
    cli: { command: spec.command, installUrl: spec.installUrl },
    signInCommand: (env) => [`"${findAgentCli(spec, env, home(env)) ?? spec.command}"`, ...spec.loginArgs].join(' '),
    capabilities: new Set(['resume', 'interrupt', 'models', 'setModel', 'modes', 'setMode', 'context']),
    modes: MODE_LIST,

    async probe(env: Env): Promise<ProviderState> {
      const path = findAgentCli(spec, env, home(env))
      if (!path) return { status: 'not-installed' }
      try {
        const { stdout } = await run(path, ['--version'], { env, timeout: 15_000 })
        const version = stdout.match(/\d+\.\d+\.\d+/)?.[0]
        return { status: spec.signedIn(env, home(env)) ? 'signed-in' : 'signed-out', version }
      } catch {
        return { status: 'unknown' }
      }
    },

    async open(options: OpenOptions): Promise<ProviderSession> {
      const path = findAgentCli(spec, options.env, home(options.env))
      if (!path) throw new Error(`The ${spec.command} CLI was not found.`)
      return AcpSession.start(spec, path, options)
    }
  }
}

class AcpSession implements ProviderSession {
  nativeId = ''
  private readonly items = new Emitter<SessionItem>()
  private readonly facts = new Emitter<SessionFact>()
  private readonly exits = new Emitter<{ error?: string }>()
  readonly onItem = this.items.event
  readonly onFact = this.facts.event
  readonly onExit = this.exits.event
  private readonly translator = new AcpTranslator((item) => this.items.fire(item))
  private readonly approvals = new Map<string, { item: ApprovalItem; optionIds: Map<string, string>; resolve: (result: unknown) => void }>()
  private models: (ModelOption & { contextWindow?: number })[] = []
  private model = ''
  private mode: PermissionMode
  private replaying = false
  private closed = false
  private stderr = ''

  static async start(spec: AcpAgentSpec, path: string, options: OpenOptions): Promise<AcpSession> {
    const child = spawnGroup(path, spec.args, { cwd: options.cwd, env: options.env, stdio: ['pipe', 'pipe', 'pipe'] })
    const rpc = new RpcPeer(child.stdout!, child.stdin!, { envelope: { jsonrpc: '2.0' } })
    const session = new AcpSession(spec, child, rpc, options)
    try {
      await session.handshake()
    } catch (error) {
      session.closed = true
      await stopGroup(child)
      throw error
    }
    // Facts go out after open() resolves, once the caller has subscribed.
    setImmediate(() => void session.announce())
    return session
  }

  private constructor(
    private readonly spec: AcpAgentSpec,
    private readonly child: ChildProcess,
    private readonly rpc: RpcPeer,
    private readonly options: OpenOptions
  ) {
    this.mode = options.mode
    rpc.onNotification(({ method, params }) => {
      // session/load replays the conversation; the journal already holds it.
      if (method === 'session/update' && !this.replaying) this.translator.feed((params as { update: SessionUpdate }).update)
    })
    rpc.onRequest((request) => this.serverRequest(request))
    child.stderr?.setEncoding('utf8')
    child.stderr?.on('data', (chunk: string) => {
      this.stderr = (this.stderr + chunk).slice(-STDERR_TAIL)
    })
    child.on('exit', (code, signal) => {
      rpc.close(new Error(`${spec.command} exited`))
      this.exits.fire({ error: this.closed ? undefined : `${spec.command} exited (${code ?? signal}).\n${this.stderr.trim()}` })
    })
  }

  async prompt(parts: PromptPart[]): Promise<void> {
    this.translator.startTurn()
    this.rpc
      .request<{ stopReason: string; _meta?: { totalTokens?: number } | null }>('session/prompt', {
        sessionId: this.nativeId,
        prompt: [{ type: 'text', text: encodePrompt(parts, this.options.cwd) }]
      })
      .then(
        (result) => {
          this.translator.endTurn(result.stopReason)
          const used = result._meta?.totalTokens
          const window = this.models.find((model) => model.id === this.model)?.contextWindow
          if (used && window) this.facts.fire({ kind: 'context', usedTokens: used, maxTokens: window })
        },
        (error: Error) => {
          if (!this.closed) this.translator.failTurn(error.message)
        }
      )
  }

  async cancel(): Promise<void> {
    this.translator.interrupted()
    for (const id of [...this.approvals.keys()]) this.settle(id, CANCELLED, 'deny')
    this.rpc.notify('session/cancel', { sessionId: this.nativeId })
  }

  async setModel(id: string): Promise<void> {
    try {
      await this.rpc.request('session/set_model', { sessionId: this.nativeId, modelId: id })
    } catch {
      await this.rpc.request('session/set_config_option', { sessionId: this.nativeId, configId: 'model', value: id })
    }
    this.model = id
    this.facts.fire({ kind: 'model', current: id, available: this.models })
  }

  async setMode(mode: PermissionMode): Promise<void> {
    this.mode = mode
    this.facts.fire({ kind: 'mode', current: mode, available: MODE_LIST })
  }

  answer(itemId: string, optionId: string): void {
    const pending = this.approvals.get(itemId)
    if (!pending) return
    const acpOption = pending.optionIds.get(optionId)
    this.settle(itemId, acpOption ? selected(acpOption) : CANCELLED, optionId)
  }

  async dispose(): Promise<void> {
    this.closed = true
    for (const id of [...this.approvals.keys()]) this.settle(id, CANCELLED, 'deny')
    await stopGroup(this.child)
  }

  private async handshake(): Promise<void> {
    const init = await this.rpc.request<{ authMethods?: { id: string }[]; agentCapabilities?: { loadSession?: boolean } }>(
      'initialize',
      {
        protocolVersion: 1,
        clientCapabilities: { fs: { readTextFile: false, writeTextFile: false }, terminal: false },
        clientInfo: { name: 'agentdeck', version: '0.1.0' }
      }
    )
    const method = this.spec.authMethod((init.authMethods ?? []).map((auth) => auth.id), this.options.env)
    if (method) await this.rpc.request('authenticate', { methodId: method })
    const params = { cwd: this.options.cwd, mcpServers: [] }
    let result: SessionResult
    if (this.options.resumeId && init.agentCapabilities?.loadSession) {
      this.replaying = true
      try {
        result = await this.rpc.request<SessionResult>('session/load', { ...params, sessionId: this.options.resumeId })
      } finally {
        this.replaying = false
      }
      this.nativeId = this.options.resumeId
    } else {
      result = await this.rpc.request<SessionResult>('session/new', params)
      this.nativeId = result.sessionId ?? ''
    }
    this.models = (result.models?.availableModels ?? []).map((model) => ({
      id: model.modelId,
      label: model.name,
      description: model.description ?? undefined,
      contextWindow: model._meta?.totalContextTokens
    }))
    this.model = result.models?.currentModelId ?? ''
  }

  private async announce(): Promise<void> {
    if (this.options.model && this.options.model !== this.model) await this.setModel(this.options.model).catch(() => undefined)
    this.facts.fire({ kind: 'mode', current: this.mode, available: MODE_LIST })
    this.facts.fire({ kind: 'model', current: this.model, available: this.models })
  }

  private serverRequest({ method, params }: ServerRequest): Promise<unknown> {
    if (method === 'session/request_permission') return this.permission(params as PermissionRequest)
    return Promise.reject(new Error(`AgentDeck does not handle ${method}.`))
  }

  private permission({ toolCall, options }: PermissionRequest): Promise<unknown> {
    const allow = options.find((option) => option.kind === 'allow_once') ?? options.find((option) => option.kind === 'allow_always')
    const autoAllow = this.mode === 'full-access' || (this.mode === 'accept-edits' && toolCall.kind === 'edit')
    if (autoAllow && allow) return Promise.resolve(selected(allow.optionId))
    const optionIds = new Map<string, string>()
    const choices: ApprovalOption[] = []
    for (const [kind, id, label] of [
      ['allow_once', 'allow', 'Allow once'],
      ['allow_always', 'always', undefined],
      ['reject_once', 'deny', 'Deny']
    ] as const) {
      const option = options.find((candidate) => candidate.kind === kind)
      if (!option) continue
      optionIds.set(id, option.optionId)
      choices.push({ id, label: label ?? option.name })
    }
    const item: ApprovalItem = {
      kind: 'approval',
      id: `approval:${toolCall.toolCallId}`,
      title: `Allow ${this.spec.label} to ${APPROVAL_TITLES[toolCall.kind ?? ''] ?? 'use this tool'}?`,
      detail: toolCall.title?.replaceAll('`', '') ?? undefined,
      options: choices
    }
    return new Promise((resolve) => {
      this.approvals.set(item.id, { item, optionIds, resolve })
      this.items.fire(item)
    })
  }

  private settle(itemId: string, result: unknown, resolved: string): void {
    const pending = this.approvals.get(itemId)
    if (!pending) return
    this.approvals.delete(itemId)
    this.items.fire({ ...pending.item, resolved })
    pending.resolve(result)
  }
}
```

- [ ] **Step 2: Verify and commit**

Run: `pnpm typecheck && pnpm test` → clean; PASS.

```bash
git add src/providers/acp/provider.ts
git commit -m "feat(acp): add the ACP provider"
```

---

### Task 5: Register Grok, record a fixture, run the live smoke

**Files:**
- Modify: `src/providers/registry.ts`, `webview/app/components/provider-avatar.tsx`, `esbuild.mjs`, `README.md`, `docs/decisions.md`
- Create: `scripts/record-grok.ts`, `test/fixtures/grok/edit-turn.jsonl` (generated), `test/providers/grok-fixture.test.ts`

- [ ] **Step 1: Register**

In `src/providers/registry.ts`, add `import { acpProvider } from './acp/provider'` and `import { grok } from './acp/agents'`, and change the list to `[claudeProvider, codexProvider, acpProvider(grok)]`.

In `webview/app/components/provider-avatar.tsx`, add to `PROVIDERS`: `grok: { monogram: 'G', hue: '#a1a1aa' }`.

- [ ] **Step 2: The recorder**

`scripts/record-grok.ts`:

```ts
// Records a real Grok edit turn as a translator fixture.
// Keeps only session/update content and the stop reason: Grok's other notifications carry
// account details and MCP server environments (including API keys).
import { mkdirSync, mkdtempSync, realpathSync, writeFileSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'
import { captureEnv } from '../src/env'
import { spawnGroup, stopGroup } from '../src/process'
import { grok } from '../src/providers/acp/agents'
import { findAgentCli } from '../src/providers/acp/spec'
import { RpcPeer } from '../src/providers/rpc'

const OUT = 'test/fixtures/grok/edit-turn.jsonl'
const KEEP = new Set(['agent_message_chunk', 'agent_thought_chunk', 'tool_call', 'tool_call_update', 'plan'])

async function main(): Promise<void> {
  const env = await captureEnv()
  const cli = findAgentCli(grok, env, env.HOME ?? homedir())
  if (!cli) throw new Error('grok CLI not found')
  const cwd = realpathSync(mkdtempSync(join(tmpdir(), 'agentdeck-record-')))
  writeFileSync(join(cwd, 'notes.md'), '# Notes\n\nhello world\n')

  const child = spawnGroup(cli, grok.args, { cwd, env, stdio: ['pipe', 'pipe', 'inherit'] })
  const rpc = new RpcPeer(child.stdout!, child.stdin!, { envelope: { jsonrpc: '2.0' } })
  const lines: string[] = []
  rpc.onNotification(({ method, params }) => {
    if (method !== 'session/update') return
    const update = { ...(params as { update: Record<string, unknown> }).update }
    if (!KEEP.has(String(update.sessionUpdate))) return
    delete update.rawOutput
    lines.push(JSON.stringify({ update }).replaceAll(cwd, '/work'))
  })
  rpc.onRequest(async ({ method, params }) => {
    if (method !== 'session/request_permission') throw new Error(`unsupported: ${method}`)
    const { options } = params as { options: { optionId: string; kind: string }[] }
    const allow = options.find((option) => option.kind === 'allow_once') ?? options[0]
    return { outcome: { outcome: 'selected', optionId: allow.optionId } }
  })
  const init = await rpc.request<{ authMethods?: { id: string }[] }>('initialize', {
    protocolVersion: 1,
    clientCapabilities: { fs: { readTextFile: false, writeTextFile: false }, terminal: false },
    clientInfo: { name: 'agentdeck', version: '0.1.0' }
  })
  const method = grok.authMethod((init.authMethods ?? []).map((auth) => auth.id), env)
  if (method) await rpc.request('authenticate', { methodId: method })
  const { sessionId } = await rpc.request<{ sessionId: string }>('session/new', { cwd, mcpServers: [] })
  const { stopReason } = await rpc.request<{ stopReason: string }>('session/prompt', {
    sessionId,
    prompt: [{ type: 'text', text: 'In notes.md, replace "hello world" with "goodbye world". Then reply with one short sentence.' }]
  })
  lines.push(JSON.stringify({ stopReason }))
  await stopGroup(child)
  mkdirSync('test/fixtures/grok', { recursive: true })
  writeFileSync(OUT, `${lines.join('\n')}\n`)
  console.log(`wrote ${lines.length} lines to ${OUT}`)
}

main().catch((error) => {
  console.error('RECORD FAILED:', error)
  process.exit(1)
})
```

In `esbuild.mjs`, add `'record-grok': 'scripts/record-grok.ts'` to the extension build's `entryPoints`.

- [ ] **Step 3: Record and check for personal data**

Run: `pnpm build && node dist/record-grok.js`
Expected: `wrote N lines…` with N above 10. This uses the user's Grok sign-in and a little quota.

Then: `grep -c -i -E '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}|API_KEY|auth.json|/Users/|team_id|hostname' test/fixtures/grok/edit-turn.jsonl`
Expected: `0`. If not, do not commit the fixture; stop and report which pattern matched (not the values).

- [ ] **Step 4: Fixture test**

`test/providers/grok-fixture.test.ts`:

```ts
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import { AcpTranslator, type SessionUpdate } from '../../src/providers/acp/translate'

function translateFixture(): SessionItem[] {
  const latest = new Map<string, SessionItem>()
  const translator = new AcpTranslator((item) => latest.set(item.id, item))
  translator.startTurn()
  for (const line of readFileSync('test/fixtures/grok/edit-turn.jsonl', 'utf8').trim().split('\n')) {
    const entry = JSON.parse(line) as { update?: SessionUpdate; stopReason?: string }
    if (entry.update) translator.feed(entry.update)
    if (entry.stopReason) translator.endTurn(entry.stopReason)
  }
  return [...latest.values()]
}

describe('Grok fixture: an edit turn', () => {
  const items = translateFixture()

  it('ends the turn', () => {
    expect(items.find((item) => item.kind === 'turn')).toMatchObject({ state: 'ended', stopReason: 'end_turn' })
  })

  it('replies with finished text', () => {
    const replies = items.filter((item) => item.kind === 'message' && item.role === 'assistant')
    expect(replies.length).toBeGreaterThan(0)
    for (const reply of replies) expect(reply).toMatchObject({ streaming: false, text: expect.stringMatching(/\S/) })
  })

  it('completes its tools', () => {
    const tools = items.filter((item) => item.kind === 'tool')
    expect(tools.length).toBeGreaterThan(0)
    for (const tool of tools) expect(tool).not.toMatchObject({ status: 'running' })
  })

  it('shows the edit as a diff', () => {
    expect(items.some((item) => item.kind === 'diff' && item.newText.includes('goodbye world'))).toBe(true)
  })
})
```

Run: `pnpm test`
Expected: PASS. If *shows the edit as a diff* fails, report how this Grok version reported the edit instead of loosening the test.

- [ ] **Step 5: Live smoke**

First, make the smoke's MCP wait conditional, since ACP agents send no `mcp` fact: in `scripts/smoke.ts`, change `const mcp = waitForFact(first, id, 'mcp')` to `const mcp = provider.capabilities.has('mcpStatus') ? waitForFact(first, id, 'mcp') : undefined` (with the comment `// Only providers that report MCP status send an mcp fact (ACP agents do not).`) and `servers.kind` to `servers?.kind` on the following log line.

Run: `pnpm typecheck && pnpm build && node dist/smoke.js grok`
Expected: `grok: { status: 'signed-in', version: '1.0.70' … }`, an approval for the edit (`approving: Allow Grok to edit this file?`), tool lines, replies, and `SMOKE OK` (including the resume turn after the simulated reload). The `mcp` lines print `[]` for Grok, which does not report MCP status through ACP; that is expected. If the resume turn loses context, report it: `session/load` replay muting is the likely place to look.

- [ ] **Step 6: Docs**

In `README.md`:
- in the intro paragraph, change "Claude Code and Codex" to "Claude Code, Codex, and Grok";
- in *Requirements*, add: `- For Grok: the Grok CLI from https://x.ai/cli, signed in with \`grok login\`.`;
- in *Development*, change `node dist/smoke.js [claude|codex]` to `node dist/smoke.js [claude|codex|grok]` and add `node dist/record-grok.js` to the recorder line.

Append to the decisions table in `docs/decisions.md` (next number after the last row):

```markdown
| 27 | ACP agents share one provider; each agent is an `AcpAgentSpec` (command, install folders, auth method, sign-in check). Grok is the first | Adding OpenCode, Gemini, or Cursor's `agent acp` becomes a spec entry plus a fixture. |
| 28 | ACP permission modes are enforced by the adapter (it answers permission requests in *Accept edits* and *Full access*) | Modes switch mid-session without restarting the agent with flags such as Grok's `--always-approve`. |
```

- [ ] **Step 7: Package and commit**

Run: `pnpm typecheck && pnpm test && pnpm run package`
Expected: clean; PASS; packaged.

```bash
git add src webview scripts esbuild.mjs test README.md docs/decisions.md
git commit -m "feat: add Grok over ACP with a recorded fixture and live smoke"
```

- [ ] **Step 8: Hand off**

Ask the user to reinstall (`code --install-extension agentdeck-0.1.0.vsix --force`), reload, and check: the chooser lists Grok as signed in; a Grok chat streams reasoning and replies, shows tool cards and the edit diff, asks before editing in *Ask before edits* and not in *Accept edits*; the model picker lists Grok's models; the chat resumes after a reload.
