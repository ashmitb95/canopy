# MVP plan 1: Core and Claude — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first.

**Goal:** Build the extension-host core that every later plan uses: shared types, environment capture, the Claude provider on the shared item model, the per-session journal and store, and the session manager. It is proven by unit tests and a live smoke run that resumes a Claude session after a simulated reload.

**Architecture:** Providers turn a CLI's native stream into `SessionItem` upserts and `SessionFact`s behind the `ProviderSession` contract (spec: *Core model*, *Provider contract*). `SessionManager` owns sessions: it persists items to a JSONL journal, records to a `Memento`, queues prompts while a turn runs, tracks status, and fans events out to any number of subscribers. Nothing in this plan imports `vscode`; the existing POC UI (`src/extension.ts`, `src/claude-session.ts`, `media/`) keeps working untouched and is replaced in plan 2.

**Tech Stack:** TypeScript 5.9, `@anthropic-ai/claude-agent-sdk` 0.3.284 (driving the user's installed `claude`), vitest 4, esbuild, pnpm.

---

## File structure

| File | Responsibility |
|---|---|
| `src/core/emitter.ts` | Minimal event emitter (`Emitter`, `Event`, `Disposable`) so core code needs no `vscode` |
| `src/core/types.ts` | `PromptPart`, `SessionItem` and its variants, `SessionFact`, `PermissionMode`, `ProviderDefinition`, `ProviderSession` |
| `src/env.ts` | Capture the login-shell `PATH`; find a CLI on `PATH` |
| `src/providers/claude/encode.ts` | `PromptPart[]` → the text Claude receives |
| `src/providers/claude/tools.ts` | Tool name → kind, title, paths, approval detail |
| `src/providers/claude/translate.ts` | SDK messages → `SessionItem`s (stream text, thinking, tools, diffs, plan, turns) |
| `src/providers/claude/provider.ts` | `claudeProvider` definition and the `ClaudeSession` (query lifecycle, approvals, facts, MCP) |
| `src/sessions/journal.ts` | Append-only JSONL item log with coalesced writes; fold on read |
| `src/sessions/store.ts` | Session records in a `Memento` |
| `src/sessions/manager.ts` | Session lifecycle, status, queue, approvals, persistence, resume, fan-out |
| `test/memory-memento.ts` | In-memory `Memento` for tests and the smoke script |
| `test/fake-provider.ts` | Scriptable `ProviderDefinition` for manager tests |
| `test/**/*.test.ts` | Unit tests |
| `test/fixtures/claude/edit-turn.jsonl` | Recorded SDK messages from a real Claude edit turn |
| `scripts/record-claude.ts` | Records that fixture |
| `scripts/smoke.ts` | Live check through `SessionManager` (replaces the POC smoke) |

---

### Task 1: Test tooling

**Files:**
- Modify: `package.json` (scripts, devDependencies)
- Modify: `tsconfig.json` (`include`)

- [ ] **Step 1: Install vitest**

Run: `pnpm add -D vitest@4.1.6`
Expected: `devDependencies` in `package.json` gains `"vitest": "4.1.6"` (pnpm may write `^4.1.6`; change it to the exact `4.1.6` to match the other pins). If pnpm adds a placeholder line under `allowBuilds` in `pnpm-workspace.yaml` (text like `set this to true or false`), delete that line.

- [ ] **Step 2: Add the test script**

In `package.json` `scripts`, add after `"typecheck"`:

```json
    "test": "vitest run",
```

- [ ] **Step 3: Type-check tests too**

In `tsconfig.json`, change `"include": ["src", "scripts"]` to:

```json
  "include": ["src", "scripts", "test"]
```

- [ ] **Step 4: Verify the tooling runs**

Run: `pnpm test`
Expected: vitest reports `No test files found` and exits with code 1. That is correct at this point.

Run: `pnpm typecheck`
Expected: no output, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.json
git commit -m "build: add vitest"
```

---

### Task 2: Core types and emitter

**Files:**
- Create: `src/core/emitter.ts`
- Create: `src/core/types.ts`
- Test: `test/core/emitter.test.ts`

- [ ] **Step 1: Write the failing test**

`test/core/emitter.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { Emitter } from '../../src/core/emitter'

describe('Emitter', () => {
  it('delivers values to listeners until they are disposed', () => {
    const emitter = new Emitter<number>()
    const seen: number[] = []
    const subscription = emitter.event((value) => seen.push(value))
    emitter.fire(1)
    subscription.dispose()
    emitter.fire(2)
    expect(seen).toEqual([1])
  })

  it('supports several listeners', () => {
    const emitter = new Emitter<string>()
    const seen: string[] = []
    emitter.event((value) => seen.push(`a:${value}`))
    emitter.event((value) => seen.push(`b:${value}`))
    emitter.fire('x')
    expect(seen).toEqual(['a:x', 'b:x'])
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm test`
Expected: FAIL, cannot resolve `../../src/core/emitter`.

- [ ] **Step 3: Write the emitter**

`src/core/emitter.ts`:

```ts
export type Disposable = { dispose(): void }

export type Event<T> = (listener: (value: T) => void) => Disposable

/** A minimal event emitter, so providers and sessions stay free of the vscode module. */
export class Emitter<T> {
  private readonly listeners = new Set<(value: T) => void>()

  readonly event: Event<T> = (listener) => {
    this.listeners.add(listener)
    return { dispose: () => this.listeners.delete(listener) }
  }

  fire(value: T): void {
    for (const listener of [...this.listeners]) listener(value)
  }
}
```

- [ ] **Step 4: Write the core types**

`src/core/types.ts` (types only; later tasks use every one of them):

```ts
import type { Env } from '../env'
import type { Event } from './emitter'

export type PromptPart =
  | { type: 'text'; text: string }
  | { type: 'file'; path: string; range?: [number, number] }

export type ToolKind = 'read' | 'edit' | 'execute' | 'search' | 'fetch' | 'mcp' | 'other'

export type PlanEntry = { text: string; status: 'pending' | 'in_progress' | 'done' }

export type ApprovalOption = { id: string; label: string }

export type AssistantMessage = { kind: 'message'; id: string; role: 'assistant'; text: string; streaming: boolean }
export type UserMessage = { kind: 'message'; id: string; role: 'user'; parts: PromptPart[] }
export type Thought = { kind: 'thought'; id: string; text: string; streaming: boolean }
export type ToolItem = {
  kind: 'tool'
  id: string
  title: string
  toolKind: ToolKind
  status: 'running' | 'done' | 'failed'
  input?: unknown
  output?: string
  paths?: string[]
  parentId?: string
}
export type DiffItem = { kind: 'diff'; id: string; path: string; oldText: string | null; newText: string; parentId?: string }
export type PlanItem = { kind: 'plan'; id: string; entries: PlanEntry[] }
export type ApprovalItem = {
  kind: 'approval'
  id: string
  title: string
  detail?: string
  options: ApprovalOption[]
  resolved?: string
}
export type TurnItem = { kind: 'turn'; id: string; state: 'started' | 'ended'; stopReason?: string; durationMs?: number }
export type NoticeItem = {
  kind: 'notice'
  id: string
  level: 'info' | 'warning' | 'error'
  text: string
  action?: 'sign-in' | 'retry'
}

/** One transcript entry. An item whose id was seen before replaces the earlier one in place. */
export type SessionItem =
  | AssistantMessage
  | UserMessage
  | Thought
  | ToolItem
  | DiffItem
  | PlanItem
  | ApprovalItem
  | TurnItem
  | NoticeItem

export type PermissionMode = 'ask' | 'accept-edits' | 'plan' | 'full-access'

export type McpServer = {
  name: string
  status: 'connected' | 'failed' | 'needs-auth' | 'pending' | 'disabled'
  /** Where the server is configured, e.g. user, project, local, claudeai. */
  scope?: string
  error?: string
  tools: string[]
}

/** Session state shown outside the transcript. The latest fact of each kind wins. */
export type SessionFact =
  | { kind: 'model'; current: string; available: { id: string; label: string }[] }
  | { kind: 'mode'; current: PermissionMode; available: readonly PermissionMode[] }
  | { kind: 'context'; usedTokens: number; maxTokens: number }
  | { kind: 'mcp'; servers: McpServer[] }

export type Capability = 'resume' | 'interrupt' | 'models' | 'setModel' | 'modes' | 'setMode' | 'mcpStatus' | 'context'

export type ProviderState = {
  status: 'signed-in' | 'signed-out' | 'not-installed' | 'unknown'
  version?: string
  account?: string
}

export type OpenOptions = { env: Env; cwd: string; mode: PermissionMode; model?: string; resumeId?: string }

export interface ProviderDefinition {
  readonly id: string
  readonly label: string
  readonly cli: { command: string; installUrl: string }
  /** Shell command the UI runs in a terminal to sign in. */
  readonly signInCommand: string
  readonly capabilities: ReadonlySet<Capability>
  readonly modes: readonly PermissionMode[]
  probe(env: Env): Promise<ProviderState>
  open(options: OpenOptions): Promise<ProviderSession>
}

/**
 * A running provider CLI for one session. It emits nothing until `open()` has resolved, so the
 * caller can subscribe first: initial facts come from asynchronous work.
 */
export interface ProviderSession {
  readonly nativeId: string
  /** Starts a turn. Resolves once the prompt is handed to the CLI; a `turn` item marks its end. */
  prompt(parts: PromptPart[]): Promise<void>
  cancel(): Promise<void>
  setModel?(id: string): Promise<void>
  setMode?(mode: PermissionMode): Promise<void>
  /** Settles a pending approval item with one of its option ids. */
  answer(itemId: string, optionId: string): void
  refreshMcp?(): Promise<void>
  reconnectMcp?(server: string): Promise<void>
  dispose(): Promise<void>
  readonly onItem: Event<SessionItem>
  readonly onFact: Event<SessionFact>
  readonly onExit: Event<{ error?: string }>
}
```

`src/env.ts` does not exist yet, so `pnpm typecheck` fails until Task 3. vitest does not type-check, so the test still runs.

- [ ] **Step 5: Run the test to verify it passes**

Run: `pnpm test`
Expected: PASS, 2 tests.

- [ ] **Step 6: Commit**

```bash
git add src/core test/core
git commit -m "feat(core): add session item, fact, and provider contracts"
```

---

### Task 3: Environment capture

**Files:**
- Create: `src/env.ts`
- Test: `test/env.test.ts`

- [ ] **Step 1: Write the failing test**

`test/env.test.ts`:

```ts
import { chmodSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { delimiter, join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { captureEnv, findOnPath } from '../src/env'

describe('findOnPath', () => {
  it('finds a command in a later PATH entry', () => {
    const dir = mkdtempSync(join(tmpdir(), 'agentdeck-env-'))
    const cli = join(dir, 'fake-cli')
    writeFileSync(cli, '#!/bin/sh\n')
    chmodSync(cli, 0o755)
    expect(findOnPath({ PATH: `${join(dir, 'missing')}${delimiter}${dir}` }, 'fake-cli')).toBe(cli)
  })

  it('returns null when the command is absent', () => {
    expect(findOnPath({ PATH: tmpdir() }, 'agentdeck-no-such-cli')).toBeNull()
  })
})

describe('captureEnv', () => {
  it('copies the base environment, dropping undefined values', async () => {
    const env = await captureEnv({ PATH: '/bin', FOO: '1', EMPTY: undefined })
    expect(env).toEqual({ PATH: '/bin', FOO: '1' })
  })
})
```

The `captureEnv` test passes no `SHELL`, so it never spawns a shell.

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm test`
Expected: FAIL, cannot resolve `../src/env`.

- [ ] **Step 3: Implement**

`src/env.ts`:

```ts
import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { delimiter, join } from 'node:path'
import { promisify } from 'node:util'

const run = promisify(execFile)

/** Environment for spawning provider CLIs. */
export type Env = Record<string, string>

const MARKER = '__AGENTDECK_PATH__'

/** GUI-launched VS Code lacks the shell's PATH, so read it from a login shell. */
export async function captureEnv(base: NodeJS.ProcessEnv = process.env): Promise<Env> {
  const env: Env = {}
  for (const [key, value] of Object.entries(base)) {
    if (value !== undefined) env[key] = value
  }
  const shell = base.SHELL
  if (shell && process.platform !== 'win32') {
    try {
      // Shell startup files may print; the marker separates their output from the PATH.
      const { stdout } = await run(shell, ['-ilc', `printf "${MARKER}%s" "$PATH"`], { timeout: 10_000 })
      const path = stdout.split(MARKER).pop()?.trim()
      if (path) env.PATH = path
    } catch {
      // Fall back to the extension host's PATH.
    }
  }
  return env
}

export function findOnPath(env: Env, command: string): string | null {
  const name = process.platform === 'win32' ? `${command}.exe` : command
  for (const dir of (env.PATH ?? '').split(delimiter)) {
    const candidate = join(dir, name)
    if (dir && existsSync(candidate)) return candidate
  }
  return null
}
```

- [ ] **Step 4: Run tests and typecheck**

Run: `pnpm test && pnpm typecheck`
Expected: PASS (5 tests); typecheck clean.

- [ ] **Step 5: Commit**

```bash
git add src/env.ts test/env.test.ts
git commit -m "feat(core): capture login-shell PATH and resolve CLIs"
```

---

### Task 4: Claude prompt encoding

**Files:**
- Create: `src/providers/claude/encode.ts`
- Test: `test/providers/claude-encode.test.ts`

The editor-context format comes from the spec's *Editor context* section.

- [ ] **Step 1: Write the failing test**

`test/providers/claude-encode.test.ts`:

```ts
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { encodePrompt } from '../../src/providers/claude/encode'

function workspace(): string {
  const cwd = mkdtempSync(join(tmpdir(), 'agentdeck-encode-'))
  mkdirSync(join(cwd, 'src'))
  const lines = Array.from({ length: 300 }, (_, i) => `line ${i + 1}`)
  writeFileSync(join(cwd, 'src', 'a.ts'), lines.join('\n'))
  return cwd
}

describe('encodePrompt', () => {
  it('joins text parts with a blank line', () => {
    expect(encodePrompt([{ type: 'text', text: 'one' }, { type: 'text', text: 'two' }], '/w')).toBe('one\n\ntwo')
  })

  it('references a file relative to the workspace', () => {
    const cwd = workspace()
    expect(encodePrompt([{ type: 'file', path: join(cwd, 'src', 'a.ts') }], cwd)).toBe(
      '<editor-context file="src/a.ts" />'
    )
  })

  it('includes the selected lines', () => {
    const cwd = workspace()
    expect(encodePrompt([{ type: 'file', path: join(cwd, 'src', 'a.ts'), range: [2, 3] }], cwd)).toBe(
      '<editor-context file="src/a.ts" selection="2-3">\nline 2\nline 3\n</editor-context>'
    )
  })

  it('caps the selection at 200 lines', () => {
    const cwd = workspace()
    const encoded = encodePrompt([{ type: 'file', path: join(cwd, 'src', 'a.ts'), range: [1, 300] }], cwd)
    expect(encoded).toContain('line 200\n</editor-context>')
    expect(encoded).not.toContain('line 201')
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm test test/providers/claude-encode.test.ts`
Expected: FAIL, cannot resolve `encode`.

- [ ] **Step 3: Implement**

`src/providers/claude/encode.ts`:

```ts
import { readFileSync } from 'node:fs'
import { relative, resolve } from 'node:path'
import type { PromptPart } from '../../core/types'

const MAX_SELECTION_LINES = 200

/** Claude takes one text prompt; files become editor-context blocks after the user's text. */
export function encodePrompt(parts: PromptPart[], cwd: string): string {
  return parts.map((part) => (part.type === 'text' ? part.text : editorContext(part.path, part.range, cwd))).join('\n\n')
}

function editorContext(path: string, range: [number, number] | undefined, cwd: string): string {
  const absolute = resolve(cwd, path)
  const file = relative(cwd, absolute)
  if (!range) return `<editor-context file="${file}" />`
  const [start, end] = range
  let text = ''
  try {
    const lines = readFileSync(absolute, 'utf8').split('\n')
    text = lines.slice(start - 1, Math.min(end, start - 1 + MAX_SELECTION_LINES)).join('\n')
  } catch {
    // The file may have been deleted since it was selected; the reference alone still helps.
  }
  return `<editor-context file="${file}" selection="${start}-${end}">\n${text}\n</editor-context>`
}
```

- [ ] **Step 4: Run tests**

Run: `pnpm test && pnpm typecheck`
Expected: PASS; typecheck clean.

- [ ] **Step 5: Commit**

```bash
git add src/providers/claude/encode.ts test/providers/claude-encode.test.ts
git commit -m "feat(claude): encode prompt parts with editor context"
```

---

### Task 5: Claude tool descriptions

**Files:**
- Create: `src/providers/claude/tools.ts`
- Test: `test/providers/claude-tools.test.ts`

- [ ] **Step 1: Write the failing test**

`test/providers/claude-tools.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { approvalDetail, toolKind, toolPaths, toolTitle } from '../../src/providers/claude/tools'

describe('Claude tool descriptions', () => {
  it('classifies tools', () => {
    expect(toolKind('Read')).toBe('read')
    expect(toolKind('Edit')).toBe('edit')
    expect(toolKind('Bash')).toBe('execute')
    expect(toolKind('Grep')).toBe('search')
    expect(toolKind('WebFetch')).toBe('fetch')
    expect(toolKind('mcp__notion__search')).toBe('mcp')
    expect(toolKind('Task')).toBe('other')
  })

  it('titles a tool with its target', () => {
    expect(toolTitle('Bash', { command: 'pnpm test' })).toBe('Bash pnpm test')
    expect(toolTitle('Read', { file_path: '/w/a.ts' })).toBe('Read /w/a.ts')
    expect(toolTitle('Task', { prompt: 'x' })).toBe('Task')
  })

  it('titles an MCP tool as server and tool', () => {
    expect(toolTitle('mcp__notion__search_pages', {})).toBe('notion · search_pages')
  })

  it('shortens long targets', () => {
    expect(toolTitle('Bash', { command: 'x'.repeat(200) })).toHaveLength('Bash '.length + 120)
  })

  it('lists file paths a tool touches', () => {
    expect(toolPaths({ file_path: '/w/a.ts' })).toEqual(['/w/a.ts'])
    expect(toolPaths({ notebook_path: '/w/n.ipynb' })).toEqual(['/w/n.ipynb'])
    expect(toolPaths({ command: 'ls' })).toBeUndefined()
  })

  it('describes what an approval would allow', () => {
    expect(approvalDetail({ command: 'rm -rf build' })).toBe('rm -rf build')
    expect(approvalDetail({ file_path: '/w/a.ts', content: 'x' })).toBe('/w/a.ts')
    expect(approvalDetail({ query: 'q' })).toBe('{\n  "query": "q"\n}')
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm test test/providers/claude-tools.test.ts`
Expected: FAIL, cannot resolve `tools`.

- [ ] **Step 3: Implement**

`src/providers/claude/tools.ts`:

```ts
import type { ToolKind } from '../../core/types'

const KINDS: Record<string, ToolKind> = {
  Read: 'read',
  NotebookRead: 'read',
  Edit: 'edit',
  MultiEdit: 'edit',
  Write: 'edit',
  NotebookEdit: 'edit',
  Bash: 'execute',
  Grep: 'search',
  Glob: 'search',
  WebFetch: 'fetch',
  WebSearch: 'fetch'
}

const TARGET_KEYS = ['file_path', 'notebook_path', 'command', 'pattern', 'url', 'query']
const MAX_TARGET = 120

export function toolKind(name: string): ToolKind {
  if (name.startsWith('mcp__')) return 'mcp'
  return KINDS[name] ?? 'other'
}

export function toolTitle(name: string, input: Record<string, unknown>): string {
  if (name.startsWith('mcp__')) {
    const [, server, ...tool] = name.split('__')
    return `${server} · ${tool.join('__')}`
  }
  const target = firstString(input, TARGET_KEYS)
  return target ? `${name} ${target.slice(0, MAX_TARGET)}` : name
}

export function toolPaths(input: Record<string, unknown>): string[] | undefined {
  const path = firstString(input, ['file_path', 'notebook_path'])
  return path ? [path] : undefined
}

export function approvalDetail(input: Record<string, unknown>): string {
  return firstString(input, ['command', 'file_path', 'notebook_path', 'url']) ?? JSON.stringify(input, null, 2).slice(0, 2000)
}

function firstString(input: Record<string, unknown>, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = input[key]
    if (typeof value === 'string') return value
  }
  return undefined
}
```

- [ ] **Step 4: Run tests**

Run: `pnpm test && pnpm typecheck`
Expected: PASS; typecheck clean.

- [ ] **Step 5: Commit**

```bash
git add src/providers/claude/tools.ts test/providers/claude-tools.test.ts
git commit -m "feat(claude): describe tools by kind, title, and paths"
```

---

### Task 6: Claude translator

**Files:**
- Create: `src/providers/claude/translate.ts`
- Test: `test/providers/claude-translate.test.ts`

The SDK runs with `includePartialMessages: true`, so assistant text and thinking arrive as `stream_event`s. Final `assistant` messages are used only for their `tool_use` blocks (the CLI sends one content block per assistant message, so block indexes there are not usable as ids). Subagent output (`parent_tool_use_id` set) contributes tools with `parentId`, never text.

- [ ] **Step 1: Write the failing test**

`test/providers/claude-translate.test.ts`:

```ts
import type { SDKMessage } from '@anthropic-ai/claude-agent-sdk'
import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import { ClaudeTranslator } from '../../src/providers/claude/translate'

const sdk = (message: object): SDKMessage => ({ uuid: 'u', session_id: 's', ...message }) as unknown as SDKMessage
const stream = (event: object, parent: string | null = null) =>
  sdk({ type: 'stream_event', event, parent_tool_use_id: parent })
const assistant = (content: object[], parent: string | null = null) =>
  sdk({ type: 'assistant', message: { id: 'msg_x', role: 'assistant', content }, parent_tool_use_id: parent })
const toolResult = (id: string, content: unknown, isError = false) =>
  sdk({
    type: 'user',
    message: { role: 'user', content: [{ type: 'tool_result', tool_use_id: id, content, is_error: isError }] },
    parent_tool_use_id: null
  })

function run(messages: SDKMessage[], setup?: (translator: ClaudeTranslator) => void) {
  const items: SessionItem[] = []
  const translator = new ClaudeTranslator((item) => items.push(item))
  setup?.(translator)
  for (const message of messages) translator.feed(message)
  const latest = new Map<string, SessionItem>()
  for (const item of items) latest.set(item.id, item)
  return { items, final: [...latest.values()] }
}

describe('ClaudeTranslator', () => {
  it('streams assistant text into one upserted message', () => {
    const { items, final } = run([
      stream({ type: 'message_start', message: { id: 'msg_1' } }),
      stream({ type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } }),
      stream({ type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: 'Hello' } }),
      stream({ type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: ' world' } }),
      stream({ type: 'content_block_stop', index: 0 })
    ])
    expect(items[2]).toEqual({ kind: 'message', id: 'msg_1:0', role: 'assistant', text: 'Hello world', streaming: true })
    expect(final).toEqual([{ kind: 'message', id: 'msg_1:0', role: 'assistant', text: 'Hello world', streaming: false }])
  })

  it('streams thinking into a thought', () => {
    const { final } = run([
      stream({ type: 'message_start', message: { id: 'msg_1' } }),
      stream({ type: 'content_block_start', index: 0, content_block: { type: 'thinking', thinking: '' } }),
      stream({ type: 'content_block_delta', index: 0, delta: { type: 'thinking_delta', thinking: 'Let me look' } }),
      stream({ type: 'content_block_stop', index: 0 })
    ])
    expect(final).toEqual([{ kind: 'thought', id: 'msg_1:0', text: 'Let me look', streaming: false }])
  })

  it('ignores subagent text', () => {
    const { items } = run([
      stream({ type: 'message_start', message: { id: 'msg_sub' } }, 'toolu_task'),
      stream({ type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } }, 'toolu_task'),
      stream({ type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: 'x' } }, 'toolu_task')
    ])
    expect(items).toEqual([])
  })

  it('turns an Edit into a running tool and a diff, then completes it', () => {
    const input = { file_path: '/w/notes.md', old_string: 'hello', new_string: 'goodbye' }
    const { final } = run([
      assistant([{ type: 'tool_use', id: 'toolu_1', name: 'Edit', input }]),
      toolResult('toolu_1', 'The file was updated.')
    ])
    expect(final).toEqual([
      {
        kind: 'tool',
        id: 'toolu_1',
        title: 'Edit /w/notes.md',
        toolKind: 'edit',
        status: 'done',
        input,
        output: 'The file was updated.',
        paths: ['/w/notes.md'],
        parentId: undefined
      },
      { kind: 'diff', id: 'toolu_1:diff', path: '/w/notes.md', oldText: 'hello', newText: 'goodbye', parentId: undefined }
    ])
  })

  it('shows a Write as a diff from nothing', () => {
    const { final } = run([
      assistant([{ type: 'tool_use', id: 'toolu_2', name: 'Write', input: { file_path: '/w/new.md', content: 'hi' } }])
    ])
    expect(final[1]).toEqual({ kind: 'diff', id: 'toolu_2:diff', path: '/w/new.md', oldText: null, newText: 'hi', parentId: undefined })
  })

  it('marks failed tools and joins block results', () => {
    const { final } = run([
      assistant([{ type: 'tool_use', id: 'toolu_3', name: 'Bash', input: { command: 'false' } }]),
      toolResult('toolu_3', [{ type: 'text', text: 'exit 1' }, { type: 'image' }], true)
    ])
    expect(final[0]).toMatchObject({ status: 'failed', output: 'exit 1\n[image]' })
  })

  it('links subagent tools to their parent', () => {
    const { final } = run([
      assistant([{ type: 'tool_use', id: 'toolu_4', name: 'Read', input: { file_path: '/w/a' } }], 'toolu_task')
    ])
    expect(final[0]).toMatchObject({ id: 'toolu_4', parentId: 'toolu_task' })
  })

  it('turns TodoWrite into the session plan', () => {
    const todos = [
      { content: 'Read code', status: 'completed' },
      { content: 'Fix bug', status: 'in_progress' },
      { content: 'Test', status: 'pending' }
    ]
    const { final } = run([assistant([{ type: 'tool_use', id: 'toolu_5', name: 'TodoWrite', input: { todos } }])])
    expect(final[1]).toEqual({
      kind: 'plan',
      id: 'plan',
      entries: [
        { text: 'Read code', status: 'done' },
        { text: 'Fix bug', status: 'in_progress' },
        { text: 'Test', status: 'pending' }
      ]
    })
  })

  it('opens and closes a turn', () => {
    const { final } = run(
      [sdk({ type: 'result', subtype: 'success', is_error: false, duration_ms: 1200, result: 'ok' })],
      (translator) => translator.startTurn()
    )
    expect(final).toHaveLength(1)
    expect(final[0]).toMatchObject({ kind: 'turn', state: 'ended', stopReason: 'success', durationMs: 1200 })
  })

  it('reports a failed turn', () => {
    const { final } = run(
      [sdk({ type: 'result', subtype: 'success', is_error: true, duration_ms: 5, result: 'API Error: overloaded' })],
      (translator) => translator.startTurn()
    )
    expect(final[1]).toMatchObject({ kind: 'notice', level: 'error', text: 'API Error: overloaded' })
  })

  it('does not report an interrupted turn as an error', () => {
    const { final } = run(
      [sdk({ type: 'result', subtype: 'error_during_execution', is_error: true, duration_ms: 5 })],
      (translator) => {
        translator.startTurn()
        translator.interrupted()
      }
    )
    expect(final).toHaveLength(1)
    expect(final[0]).toMatchObject({ kind: 'turn', state: 'ended', stopReason: 'interrupted' })
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm test test/providers/claude-translate.test.ts`
Expected: FAIL, cannot resolve `translate`.

- [ ] **Step 3: Implement**

`src/providers/claude/translate.ts`:

```ts
import { randomUUID } from 'node:crypto'
import type { SDKMessage } from '@anthropic-ai/claude-agent-sdk'
import type { AssistantMessage, PlanEntry, SessionItem, Thought, ToolItem } from '../../core/types'
import { toolKind, toolPaths, toolTitle } from './tools'

type Message<T extends SDKMessage['type']> = Extract<SDKMessage, { type: T }>

/** Tool output kept in the transcript; a Read result can be a whole file. */
const MAX_OUTPUT = 20_000

/** Turns Claude Agent SDK messages into session items. Facts are the provider's job. */
export class ClaudeTranslator {
  private messageId = ''
  private readonly streaming = new Map<number, AssistantMessage | Thought>()
  private readonly tools = new Map<string, ToolItem>()
  private turnId = ''
  private interruptRequested = false

  constructor(private readonly emit: (item: SessionItem) => void) {}

  startTurn(): void {
    this.turnId = `turn:${randomUUID()}`
    this.interruptRequested = false
    this.emit({ kind: 'turn', id: this.turnId, state: 'started' })
  }

  interrupted(): void {
    this.interruptRequested = true
  }

  feed(message: SDKMessage): void {
    switch (message.type) {
      case 'stream_event':
        return this.streamEvent(message)
      case 'assistant':
        return this.assistant(message)
      case 'user':
        return this.toolResults(message)
      case 'result':
        return this.result(message)
    }
  }

  private streamEvent(message: Message<'stream_event'>): void {
    if (message.parent_tool_use_id) return
    const event = message.event
    switch (event.type) {
      case 'message_start':
        this.messageId = event.message.id
        this.streaming.clear()
        return
      case 'content_block_start': {
        const id = `${this.messageId}:${event.index}`
        if (event.content_block.type === 'text') {
          this.stream(event.index, { kind: 'message', id, role: 'assistant', text: '', streaming: true })
        } else if (event.content_block.type === 'thinking') {
          this.stream(event.index, { kind: 'thought', id, text: '', streaming: true })
        }
        return
      }
      case 'content_block_delta': {
        const item = this.streaming.get(event.index)
        if (!item) return
        if (event.delta.type === 'text_delta' && item.kind === 'message') item.text += event.delta.text
        else if (event.delta.type === 'thinking_delta' && item.kind === 'thought') item.text += event.delta.thinking
        else return
        this.emit({ ...item })
        return
      }
      case 'content_block_stop': {
        const item = this.streaming.get(event.index)
        if (!item) return
        item.streaming = false
        this.emit({ ...item })
        return
      }
    }
  }

  private stream(index: number, item: AssistantMessage | Thought): void {
    this.streaming.set(index, item)
    this.emit({ ...item })
  }

  private assistant(message: Message<'assistant'>): void {
    const parentId = message.parent_tool_use_id ?? undefined
    for (const block of message.message.content) {
      if (block.type === 'tool_use') this.toolUse(block.id, block.name, block.input as Record<string, unknown>, parentId)
    }
  }

  private toolUse(id: string, name: string, input: Record<string, unknown>, parentId: string | undefined): void {
    const tool: ToolItem = {
      kind: 'tool',
      id,
      title: toolTitle(name, input),
      toolKind: toolKind(name),
      status: 'running',
      input,
      paths: toolPaths(input),
      parentId
    }
    this.tools.set(id, tool)
    this.emit(tool)
    const path = typeof input.file_path === 'string' ? input.file_path : undefined
    if (name === 'Edit' && path) {
      const oldText = String(input.old_string ?? '')
      this.emit({ kind: 'diff', id: `${id}:diff`, path, oldText, newText: String(input.new_string ?? ''), parentId })
    } else if (name === 'Write' && path) {
      this.emit({ kind: 'diff', id: `${id}:diff`, path, oldText: null, newText: String(input.content ?? ''), parentId })
    } else if (name === 'TodoWrite' && Array.isArray(input.todos)) {
      this.emit({ kind: 'plan', id: 'plan', entries: planEntries(input.todos) })
    }
  }

  private toolResults(message: Message<'user'>): void {
    const content = message.message.content
    if (typeof content === 'string') return
    for (const block of content) {
      if (block.type !== 'tool_result') continue
      const tool = this.tools.get(block.tool_use_id)
      if (!tool) continue
      const done: ToolItem = { ...tool, status: block.is_error ? 'failed' : 'done', output: resultText(block.content) }
      this.tools.set(tool.id, done)
      this.emit(done)
    }
  }

  private result(message: Message<'result'>): void {
    const turnId = this.turnId || `turn:${randomUUID()}`
    const stopReason = this.interruptRequested ? 'interrupted' : message.subtype
    this.emit({ kind: 'turn', id: turnId, state: 'ended', stopReason, durationMs: message.duration_ms })
    if (message.is_error && !this.interruptRequested) {
      const text = message.subtype === 'success' ? message.result : `The turn ended with ${message.subtype}.`
      this.emit({ kind: 'notice', id: `${turnId}:error`, level: 'error', text })
    }
    this.turnId = ''
  }
}

function planEntries(todos: unknown[]): PlanEntry[] {
  return (todos as { content?: unknown; status?: unknown }[]).map((todo) => ({
    text: String(todo.content ?? ''),
    status: todo.status === 'completed' ? 'done' : todo.status === 'in_progress' ? 'in_progress' : 'pending'
  }))
}

function resultText(content: unknown): string {
  const text =
    typeof content === 'string'
      ? content
      : Array.isArray(content)
        ? (content as { type: string; text?: string }[])
            .map((part) => (part.type === 'text' ? (part.text ?? '') : `[${part.type}]`))
            .join('\n')
        : ''
  return text.slice(0, MAX_OUTPUT)
}
```

- [ ] **Step 4: Run tests and typecheck**

Run: `pnpm test && pnpm typecheck`
Expected: PASS; typecheck clean. If `tsc` reports that a stream-event or content-block type has no member used above (for example `thinking_delta`), check the type in `node_modules/@anthropic-ai/sdk/resources/messages/messages.d.ts` and adjust the narrowing, not the behaviour.

- [ ] **Step 5: Commit**

```bash
git add src/providers/claude/translate.ts test/providers/claude-translate.test.ts
git commit -m "feat(claude): translate SDK messages into session items"
```

---

### Task 7: Journal

**Files:**
- Create: `src/sessions/journal.ts`
- Test: `test/sessions/journal.test.ts`

- [ ] **Step 1: Write the failing test**

`test/sessions/journal.test.ts`:

```ts
import { appendFileSync, mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import { Journal } from '../../src/sessions/journal'

const path = () => join(mkdtempSync(join(tmpdir(), 'agentdeck-journal-')), 'sessions', 's.jsonl')
const text = (id: string, value: string): SessionItem => ({ kind: 'message', id, role: 'assistant', text: value, streaming: false })

describe('Journal', () => {
  it('folds upserts in first-seen order', () => {
    const file = path()
    const journal = new Journal(file)
    journal.append(text('a', '1'))
    journal.append(text('b', '1'))
    journal.flush()
    journal.append(text('a', '2'))
    journal.flush()
    expect(Journal.read(file)).toEqual([text('a', '2'), text('b', '1')])
  })

  it('coalesces repeated upserts between flushes', () => {
    const file = path()
    const journal = new Journal(file)
    for (const value of ['H', 'He', 'Hel']) journal.append(text('a', value))
    journal.flush()
    expect(readFileSync(file, 'utf8').trim().split('\n')).toHaveLength(1)
  })

  it('flushes on its own after the delay', async () => {
    const file = path()
    const journal = new Journal(file, 10)
    journal.append(text('a', '1'))
    await new Promise((resolve) => setTimeout(resolve, 40))
    expect(Journal.read(file)).toEqual([text('a', '1')])
  })

  it('ignores a truncated last line', () => {
    const file = path()
    const journal = new Journal(file)
    journal.append(text('a', '1'))
    journal.flush()
    appendFileSync(file, '{"kind":"message","id":"b","ro')
    expect(Journal.read(file)).toEqual([text('a', '1')])
  })

  it('reads a missing journal as empty', () => {
    expect(Journal.read(path())).toEqual([])
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm test test/sessions/journal.test.ts`
Expected: FAIL, cannot resolve `journal`.

- [ ] **Step 3: Implement**

`src/sessions/journal.ts`:

```ts
import { appendFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs'
import { dirname } from 'node:path'
import type { SessionItem } from '../core/types'

/** Append-only log of item upserts. Streaming produces many upserts per item, so writes are coalesced. */
export class Journal {
  private readonly pending = new Map<string, SessionItem>()
  private timer: NodeJS.Timeout | undefined

  constructor(
    private readonly path: string,
    private readonly delayMs = 250
  ) {}

  append(item: SessionItem): void {
    this.pending.set(item.id, item)
    this.timer ??= setTimeout(() => this.flush(), this.delayMs)
  }

  flush(): void {
    clearTimeout(this.timer)
    this.timer = undefined
    if (this.pending.size === 0) return
    const lines = [...this.pending.values()].map((item) => `${JSON.stringify(item)}\n`).join('')
    this.pending.clear()
    mkdirSync(dirname(this.path), { recursive: true })
    appendFileSync(this.path, lines)
  }

  /** The latest version of every item, in the order items first appeared. */
  static read(path: string): SessionItem[] {
    if (!existsSync(path)) return []
    const items = new Map<string, SessionItem>()
    for (const line of readFileSync(path, 'utf8').split('\n')) {
      if (!line) continue
      try {
        const item = JSON.parse(line) as SessionItem
        items.set(item.id, item)
      } catch {
        // A crash mid-write leaves a partial last line.
      }
    }
    return [...items.values()]
  }
}
```

- [ ] **Step 4: Run tests**

Run: `pnpm test && pnpm typecheck`
Expected: PASS; typecheck clean.

- [ ] **Step 5: Commit**

```bash
git add src/sessions/journal.ts test/sessions/journal.test.ts
git commit -m "feat(sessions): add the JSONL session journal"
```

---

### Task 8: Session store

**Files:**
- Create: `src/sessions/store.ts`
- Create: `test/memory-memento.ts`
- Test: `test/sessions/store.test.ts`

- [ ] **Step 1: Write the in-memory Memento**

`test/memory-memento.ts`:

```ts
import type { Memento } from '../src/sessions/store'

/** Stands in for VS Code's workspaceState. */
export class MemoryMemento implements Memento {
  private readonly values = new Map<string, unknown>()

  get<T>(key: string): T | undefined {
    return this.values.get(key) as T | undefined
  }

  async update(key: string, value: unknown): Promise<void> {
    this.values.set(key, structuredClone(value))
  }
}
```

- [ ] **Step 2: Write the failing test**

`test/sessions/store.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { type SessionRecord, SessionStore } from '../../src/sessions/store'
import { MemoryMemento } from '../memory-memento'

const record = (id: string, updatedAt: string): SessionRecord => ({
  id,
  providerId: 'claude',
  title: id,
  createdAt: updatedAt,
  updatedAt,
  mode: 'ask',
  hasTurns: false,
  facts: {}
})

describe('SessionStore', () => {
  it('lists records newest first', async () => {
    const store = new SessionStore(new MemoryMemento())
    await store.put(record('old', '2026-01-01T00:00:00.000Z'))
    await store.put(record('new', '2026-02-01T00:00:00.000Z'))
    expect(store.list().map((r) => r.id)).toEqual(['new', 'old'])
  })

  it('replaces a record with the same id', async () => {
    const store = new SessionStore(new MemoryMemento())
    await store.put(record('a', '2026-01-01T00:00:00.000Z'))
    await store.put({ ...record('a', '2026-01-01T00:00:00.000Z'), title: 'Renamed' })
    expect(store.list()).toHaveLength(1)
    expect(store.get('a')?.title).toBe('Renamed')
  })

  it('deletes records', async () => {
    const store = new SessionStore(new MemoryMemento())
    await store.put(record('a', '2026-01-01T00:00:00.000Z'))
    await store.delete('a')
    expect(store.get('a')).toBeUndefined()
  })

  it('returns copies', async () => {
    const store = new SessionStore(new MemoryMemento())
    await store.put(record('a', '2026-01-01T00:00:00.000Z'))
    store.get('a')!.title = 'Mutated'
    expect(store.get('a')?.title).toBe('a')
  })
})
```

- [ ] **Step 3: Run it to verify it fails**

Run: `pnpm test test/sessions/store.test.ts`
Expected: FAIL, cannot resolve `store`.

- [ ] **Step 4: Implement**

`src/sessions/store.ts`:

```ts
import type { PermissionMode, SessionFact } from '../core/types'

/** The subset of VS Code's Memento the store uses. */
export interface Memento {
  get<T>(key: string): T | undefined
  update(key: string, value: unknown): PromiseLike<void>
}

export type SessionStatus = 'idle' | 'running' | 'needs-input' | 'error' | 'stopped'

export type SessionRecord = {
  id: string
  providerId: string
  title: string
  createdAt: string
  updatedAt: string
  mode: PermissionMode
  model?: string
  /** The provider's own session id, used to resume. */
  nativeId?: string
  /** False until a prompt was sent; a provider cannot resume a session it never saved. */
  hasTurns: boolean
  /** Latest fact of each kind, shown before the CLI is running again. */
  facts: Partial<Record<SessionFact['kind'], SessionFact>>
}

const KEY = 'agentdeck.sessions'

export class SessionStore {
  constructor(private readonly memento: Memento) {}

  list(): SessionRecord[] {
    return this.all().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
  }

  get(id: string): SessionRecord | undefined {
    return this.all().find((record) => record.id === id)
  }

  async put(record: SessionRecord): Promise<void> {
    await this.memento.update(KEY, [...this.all().filter((other) => other.id !== record.id), record])
  }

  async delete(id: string): Promise<void> {
    await this.memento.update(
      KEY,
      this.all().filter((record) => record.id !== id)
    )
  }

  private all(): SessionRecord[] {
    return structuredClone(this.memento.get<SessionRecord[]>(KEY) ?? [])
  }
}
```

- [ ] **Step 5: Run tests**

Run: `pnpm test && pnpm typecheck`
Expected: PASS; typecheck clean.

- [ ] **Step 6: Commit**

```bash
git add src/sessions/store.ts test/memory-memento.ts test/sessions/store.test.ts
git commit -m "feat(sessions): add the session record store"
```

---

### Task 9: Session manager

**Files:**
- Create: `test/fake-provider.ts`
- Create: `src/sessions/manager.ts`
- Test: `test/sessions/manager.test.ts`

Behaviour (spec: *Sessions*):
- `create` adds a record titled *New chat*; the first prompt's first line becomes the title.
- `subscribe` sends a snapshot, then live events. Several subscribers per session receive every event.
- `warm` starts the provider CLI without prompting, so models and MCP status arrive early.
- A prompt while `running` or `needs-input` is queued and sent when the turn ends; queued prompts can be removed.
- An unresolved approval sets `needs-input` and fires attention; resolving the last one returns to `running`.
- Items persist to the journal; after a restart, history is restored and the provider is reopened with `resumeId`.
- A provider exit with an error adds a notice with a retry action and sets `error`; the next prompt reconnects. If a resume attempt fails before any output, the next connect starts a fresh provider session and says so.
- Approvals left unanswered by a previous run are shown as expired; messages left streaming are shown as finished.

- [ ] **Step 1: Write the fake provider**

`test/fake-provider.ts`:

```ts
import { Emitter } from '../src/core/emitter'
import type {
  OpenOptions,
  PermissionMode,
  PromptPart,
  ProviderDefinition,
  ProviderSession,
  SessionFact,
  SessionItem
} from '../src/core/types'

export class FakeSession implements ProviderSession {
  readonly prompts: PromptPart[][] = []
  readonly answers: [string, string][] = []
  readonly modes: PermissionMode[] = []
  disposed = false
  private readonly items = new Emitter<SessionItem>()
  private readonly facts = new Emitter<SessionFact>()
  private readonly exits = new Emitter<{ error?: string }>()
  readonly onItem = this.items.event
  readonly onFact = this.facts.event
  readonly onExit = this.exits.event

  constructor(
    readonly nativeId: string,
    readonly options: OpenOptions
  ) {}

  async prompt(parts: PromptPart[]): Promise<void> {
    this.prompts.push(parts)
  }

  async cancel(): Promise<void> {}

  async setMode(mode: PermissionMode): Promise<void> {
    this.modes.push(mode)
  }

  answer(itemId: string, optionId: string): void {
    this.answers.push([itemId, optionId])
  }

  async dispose(): Promise<void> {
    this.disposed = true
    this.exits.fire({})
  }

  emit(item: SessionItem): void {
    this.items.fire(item)
  }

  fact(fact: SessionFact): void {
    this.facts.fire(fact)
  }

  exit(error?: string): void {
    this.exits.fire({ error })
  }

  endTurn(): void {
    this.items.fire({ kind: 'turn', id: `turn:${this.nativeId}:${this.prompts.length}`, state: 'ended' })
  }
}

export function fakeProvider(): { provider: ProviderDefinition; sessions: FakeSession[] } {
  const sessions: FakeSession[] = []
  const provider: ProviderDefinition = {
    id: 'fake',
    label: 'Fake',
    cli: { command: 'fake', installUrl: 'https://example.invalid' },
    signInCommand: 'fake login',
    capabilities: new Set(['resume', 'interrupt', 'modes', 'setMode']),
    modes: ['ask', 'accept-edits'],
    probe: async () => ({ status: 'signed-in' }),
    open: async (options) => {
      const session = new FakeSession(options.resumeId ?? `native-${sessions.length + 1}`, options)
      sessions.push(session)
      return session
    }
  }
  return { provider, sessions }
}
```

- [ ] **Step 2: Write the failing tests**

`test/sessions/manager.test.ts`:

```ts
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { ApprovalItem, PromptPart } from '../../src/core/types'
import { type Attention, type SessionEvent, SessionManager } from '../../src/sessions/manager'
import { SessionStore } from '../../src/sessions/store'
import { fakeProvider } from '../fake-provider'
import { MemoryMemento } from '../memory-memento'

const text = (value: string): PromptPart[] => [{ type: 'text', text: value }]
const settle = () => new Promise((resolve) => setImmediate(resolve))
const approval = (id: string, resolved?: string): ApprovalItem => ({
  kind: 'approval',
  id,
  title: 'Allow Bash?',
  options: [
    { id: 'allow', label: 'Allow once' },
    { id: 'deny', label: 'Deny' }
  ],
  resolved
})

function setup(memento = new MemoryMemento(), journalDir = mkdtempSync(join(tmpdir(), 'agentdeck-manager-'))) {
  const { provider, sessions } = fakeProvider()
  const manager = new SessionManager({
    providers: new Map([[provider.id, provider]]),
    store: new SessionStore(memento),
    journalDir,
    cwd: '/work',
    env: async () => ({ PATH: '/bin' })
  })
  return { manager, sessions, memento, journalDir }
}

function watch(manager: SessionManager, id: string): SessionEvent[] {
  const events: SessionEvent[] = []
  manager.subscribe(id, (event) => events.push(event))
  return events
}

describe('SessionManager', () => {
  it('creates a session and sends a snapshot to subscribers', async () => {
    const { manager } = setup()
    const record = await manager.create('fake')
    const events = watch(manager, record.id)
    expect(events).toEqual([{ type: 'snapshot', record, status: 'idle', items: [], queue: [] }])
    expect(manager.list()).toEqual([{ record, status: 'idle' }])
  })

  it('sends a prompt, titles the session, and returns to idle at turn end', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.prompt(id, text('Fix the login bug\nmore detail'))
    expect(sessions[0].prompts).toEqual([text('Fix the login bug\nmore detail')])
    expect(sessions[0].options).toMatchObject({ cwd: '/work', mode: 'ask', resumeId: undefined })
    expect(manager.list()[0]).toMatchObject({ record: { title: 'Fix the login bug', hasTurns: true }, status: 'running' })
    sessions[0].endTurn()
    expect(manager.list()[0].status).toBe('idle')
    expect(events.map((event) => event.type)).toEqual(['snapshot', 'status', 'item', 'item', 'status'])
  })

  it('starts the CLI early when warmed and forwards its facts', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.warm(id)
    sessions[0].fact({ kind: 'mcp', servers: [{ name: 'notion', status: 'needs-auth', tools: [] }] })
    expect(events.at(-1)).toEqual({ type: 'fact', fact: { kind: 'mcp', servers: [{ name: 'notion', status: 'needs-auth', tools: [] }] } })
    expect(manager.list()[0].record.facts.mcp).toBeDefined()
    expect(sessions).toHaveLength(1)
  })

  it('queues prompts while running and sends them at turn end', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.prompt(id, text('first'))
    await manager.prompt(id, text('second'))
    expect(sessions[0].prompts).toEqual([text('first')])
    expect(events.at(-1)).toMatchObject({ type: 'queue', queue: [{ parts: text('second') }] })
    sessions[0].endTurn()
    await settle()
    expect(sessions[0].prompts).toEqual([text('first'), text('second')])
    expect(manager.list()[0].status).toBe('running')
  })

  it('removes a queued prompt before it is sent', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.prompt(id, text('first'))
    await manager.prompt(id, text('second'))
    const queued = events.at(-1) as Extract<SessionEvent, { type: 'queue' }>
    manager.removeQueued(id, queued.queue[0].id)
    sessions[0].endTurn()
    await settle()
    expect(sessions[0].prompts).toEqual([text('first')])
  })

  it('needs input while an approval is pending and forwards the answer', async () => {
    const { manager, sessions } = setup()
    const attention: Attention[] = []
    manager.onAttention((event) => attention.push(event))
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('run it'))
    sessions[0].emit(approval('approval:1'))
    expect(manager.list()[0].status).toBe('needs-input')
    expect(attention).toEqual([{ sessionId: id, reason: 'needs-input' }])
    manager.answer(id, 'approval:1', 'allow')
    expect(sessions[0].answers).toEqual([['approval:1', 'allow']])
    sessions[0].emit(approval('approval:1', 'allow'))
    expect(manager.list()[0].status).toBe('running')
  })

  it('fans out to every subscriber until one unsubscribes', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    const first: SessionEvent[] = []
    const second: SessionEvent[] = []
    manager.subscribe(id, (event) => first.push(event))
    const subscription = manager.subscribe(id, (event) => second.push(event))
    await manager.warm(id)
    sessions[0].emit({ kind: 'notice', id: 'n1', level: 'info', text: 'one' })
    subscription.dispose()
    sessions[0].emit({ kind: 'notice', id: 'n2', level: 'info', text: 'two' })
    expect(first.filter((event) => event.type === 'item')).toHaveLength(2)
    expect(second.filter((event) => event.type === 'item')).toHaveLength(1)
  })

  it('restores history and resumes the native session after a restart', async () => {
    const before = setup()
    const { id } = await before.manager.create('fake')
    await before.manager.prompt(id, text('remember this'))
    before.sessions[0].emit({ kind: 'message', id: 'a1', role: 'assistant', text: 'ok', streaming: false })
    before.sessions[0].endTurn()
    await before.manager.dispose()

    const after = setup(before.memento, before.journalDir)
    const events = watch(after.manager, id)
    const snapshot = events[0] as Extract<SessionEvent, { type: 'snapshot' }>
    expect(snapshot.items.map((item) => item.kind)).toEqual(['message', 'message', 'turn'])
    await after.manager.prompt(id, text('what did I say?'))
    expect(after.sessions[0].options.resumeId).toBe('native-1')
  })

  it('reports a provider crash and reconnects on the next prompt', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.prompt(id, text('go'))
    sessions[0].emit({ kind: 'message', id: 'a1', role: 'assistant', text: 'working', streaming: true })
    sessions[0].exit('claude exited with code 1')
    expect(manager.list()[0].status).toBe('error')
    expect(events.at(-2)).toMatchObject({
      type: 'item',
      item: { kind: 'notice', level: 'error', text: 'claude exited with code 1', action: 'retry' }
    })
    await manager.prompt(id, text('again'))
    expect(sessions).toHaveLength(2)
    expect(sessions[1].options.resumeId).toBe('native-1')
  })

  it('starts a fresh native session when resuming fails before any output', async () => {
    const before = setup()
    const { id } = await before.manager.create('fake')
    await before.manager.prompt(id, text('hello'))
    before.sessions[0].endTurn()
    await before.manager.dispose()

    const after = setup(before.memento, before.journalDir)
    await after.manager.prompt(id, text('continue'))
    after.sessions[0].exit('No conversation found with session ID: native-1')
    expect(after.manager.list()[0].record.hasTurns).toBe(false)
    await after.manager.prompt(id, text('continue'))
    expect(after.sessions[1].options.resumeId).toBeUndefined()
  })

  it('switches mode on the record and the running session', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.warm(id)
    await manager.setMode(id, 'accept-edits')
    expect(sessions[0].modes).toEqual(['accept-edits'])
    expect(manager.list()[0].record.mode).toBe('accept-edits')
  })

  it('expires approvals and finishes streams left over from a previous run', async () => {
    const { manager, journalDir, memento } = setup()
    const { id } = await manager.create('fake')
    writeFileSync(
      join(journalDir, `${id}.jsonl`),
      [
        JSON.stringify(approval('approval:old')),
        JSON.stringify({ kind: 'message', id: 'a1', role: 'assistant', text: 'par', streaming: true })
      ].join('\n') + '\n'
    )
    const fresh = setup(memento, journalDir)
    const snapshot = watch(fresh.manager, id)[0] as Extract<SessionEvent, { type: 'snapshot' }>
    expect(snapshot.items).toEqual([
      { ...approval('approval:old'), resolved: 'expired' },
      { kind: 'message', id: 'a1', role: 'assistant', text: 'par', streaming: false }
    ])
  })

  it('stops and deletes a session', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.warm(id)
    await manager.stop(id)
    expect(sessions[0].disposed).toBe(true)
    expect(manager.list()[0].status).toBe('stopped')
    await manager.delete(id)
    expect(manager.list()).toEqual([])
  })
})
```

- [ ] **Step 3: Run them to verify they fail**

Run: `pnpm test test/sessions/manager.test.ts`
Expected: FAIL, cannot resolve `manager`.

- [ ] **Step 4: Implement**

`src/sessions/manager.ts`:

```ts
import { randomUUID } from 'node:crypto'
import { rmSync } from 'node:fs'
import { join } from 'node:path'
import { type Disposable, Emitter } from '../core/emitter'
import type {
  PermissionMode,
  PromptPart,
  ProviderDefinition,
  ProviderSession,
  SessionFact,
  SessionItem
} from '../core/types'
import type { Env } from '../env'
import { Journal } from './journal'
import type { SessionRecord, SessionStatus, SessionStore } from './store'

export type QueuedPrompt = { id: string; parts: PromptPart[] }

/** What a chat surface receives: a snapshot first, then live events. */
export type SessionEvent =
  | { type: 'snapshot'; record: SessionRecord; status: SessionStatus; items: SessionItem[]; queue: QueuedPrompt[] }
  | { type: 'item'; item: SessionItem }
  | { type: 'fact'; fact: SessionFact }
  | { type: 'status'; status: SessionStatus }
  | { type: 'queue'; queue: QueuedPrompt[] }

export type Attention = { sessionId: string; reason: 'needs-input' | 'turn-ended' }

export type SessionManagerDeps = {
  providers: ReadonlyMap<string, ProviderDefinition>
  store: SessionStore
  journalDir: string
  cwd: string
  env: () => Promise<Env>
}

type Live = {
  record: SessionRecord
  status: SessionStatus
  items: Map<string, SessionItem>
  queue: QueuedPrompt[]
  journal: Journal
  approvals: Set<string>
  subscribers: Set<(event: SessionEvent) => void>
  session?: ProviderSession
  opening?: Promise<ProviderSession>
  listeners: Disposable[]
  /** Items received since the provider session was opened; zero means it never produced output. */
  received: number
  resumed: boolean
}

const NEW_TITLE = 'New chat'
const MAX_TITLE = 60

export class SessionManager {
  private readonly live = new Map<string, Live>()
  private readonly changed = new Emitter<void>()
  private readonly attention = new Emitter<Attention>()
  /** Fires when the session list, a title, or a status changes. */
  readonly onDidChange = this.changed.event
  /** Fires when a session needs the user or finishes a turn. */
  readonly onAttention = this.attention.event

  constructor(private readonly deps: SessionManagerDeps) {}

  list(): { record: SessionRecord; status: SessionStatus }[] {
    return this.deps.store.list().map((record) => {
      const live = this.live.get(record.id)
      return live ? { record: live.record, status: live.status } : { record, status: 'idle' }
    })
  }

  async create(providerId: string, mode: PermissionMode = 'ask'): Promise<SessionRecord> {
    if (!this.deps.providers.has(providerId)) throw new Error(`Unknown provider: ${providerId}`)
    const now = new Date().toISOString()
    const record: SessionRecord = {
      id: randomUUID(),
      providerId,
      title: NEW_TITLE,
      createdAt: now,
      updatedAt: now,
      mode,
      hasTurns: false,
      facts: {}
    }
    await this.deps.store.put(record)
    this.changed.fire()
    return record
  }

  subscribe(id: string, listener: (event: SessionEvent) => void): Disposable {
    const live = this.load(id)
    live.subscribers.add(listener)
    listener({
      type: 'snapshot',
      record: live.record,
      status: live.status,
      items: [...live.items.values()],
      queue: [...live.queue]
    })
    return { dispose: () => live.subscribers.delete(listener) }
  }

  /** Starts the provider CLI so models and MCP status are available before the first prompt. */
  async warm(id: string): Promise<void> {
    const live = this.load(id)
    try {
      await this.connect(live)
    } catch (error) {
      this.fail(live, errorText(error))
    }
  }

  async prompt(id: string, parts: PromptPart[]): Promise<void> {
    const live = this.load(id)
    if (live.status === 'running' || live.status === 'needs-input') {
      live.queue.push({ id: randomUUID(), parts })
      this.broadcast(live, { type: 'queue', queue: [...live.queue] })
      return
    }
    await this.send(live, parts)
  }

  removeQueued(id: string, queuedId: string): void {
    const live = this.load(id)
    live.queue = live.queue.filter((queued) => queued.id !== queuedId)
    this.broadcast(live, { type: 'queue', queue: [...live.queue] })
  }

  async cancel(id: string): Promise<void> {
    await this.live.get(id)?.session?.cancel()
  }

  answer(id: string, itemId: string, optionId: string): void {
    this.live.get(id)?.session?.answer(itemId, optionId)
  }

  async setModel(id: string, model: string): Promise<void> {
    const live = this.load(id)
    live.record.model = model
    await this.save(live)
    await live.session?.setModel?.(model)
  }

  async setMode(id: string, mode: PermissionMode): Promise<void> {
    const live = this.load(id)
    live.record.mode = mode
    await this.save(live)
    await live.session?.setMode?.(mode)
  }

  async refreshMcp(id: string): Promise<void> {
    await this.live.get(id)?.session?.refreshMcp?.()
  }

  async reconnectMcp(id: string, server: string): Promise<void> {
    await this.live.get(id)?.session?.reconnectMcp?.(server)
  }

  async rename(id: string, title: string): Promise<void> {
    const live = this.load(id)
    live.record.title = title
    await this.save(live)
    this.changed.fire()
  }

  /** Stops the CLI. The session stays listed and resumes on the next prompt. */
  async stop(id: string): Promise<void> {
    const live = this.live.get(id)
    if (!live) return
    const session = live.session ?? (await live.opening?.catch(() => undefined))
    live.session = undefined
    live.queue = []
    this.broadcast(live, { type: 'queue', queue: [] })
    this.setStatus(live, 'stopped')
    await session?.dispose()
    this.detach(live)
    live.journal.flush()
  }

  async delete(id: string): Promise<void> {
    await this.stop(id)
    this.live.delete(id)
    rmSync(this.journalPath(id), { force: true })
    await this.deps.store.delete(id)
    this.changed.fire()
  }

  async dispose(): Promise<void> {
    await Promise.all([...this.live.keys()].map((id) => this.stop(id)))
  }

  private load(id: string): Live {
    const existing = this.live.get(id)
    if (existing) return existing
    const record = this.deps.store.get(id)
    if (!record) throw new Error(`Unknown session: ${id}`)
    const path = this.journalPath(id)
    const live: Live = {
      record,
      status: 'idle',
      items: new Map(Journal.read(path).map((item) => [item.id, settled(item)])),
      queue: [],
      journal: new Journal(path),
      approvals: new Set(),
      subscribers: new Set(),
      listeners: [],
      received: 0,
      resumed: false
    }
    this.live.set(id, live)
    return live
  }

  private journalPath(id: string): string {
    return join(this.deps.journalDir, `${id}.jsonl`)
  }

  private async send(live: Live, parts: PromptPart[]): Promise<void> {
    if (live.record.title === NEW_TITLE) live.record.title = titleFrom(parts)
    live.record.updatedAt = new Date().toISOString()
    this.setStatus(live, 'running')
    this.upsert(live, { kind: 'message', id: `user:${randomUUID()}`, role: 'user', parts })
    try {
      const session = await this.connect(live)
      live.record.hasTurns = true
      await this.save(live)
      await session.prompt(parts)
    } catch (error) {
      this.fail(live, errorText(error))
    }
  }

  private connect(live: Live): Promise<ProviderSession> {
    if (live.session) return Promise.resolve(live.session)
    live.opening ??= this.open(live).finally(() => {
      live.opening = undefined
    })
    return live.opening
  }

  private async open(live: Live): Promise<ProviderSession> {
    const provider = this.deps.providers.get(live.record.providerId)
    if (!provider) throw new Error(`Unknown provider: ${live.record.providerId}`)
    const resumeId = live.record.hasTurns ? live.record.nativeId : undefined
    const session = await provider.open({
      env: await this.deps.env(),
      cwd: this.deps.cwd,
      mode: live.record.mode,
      model: live.record.model,
      resumeId
    })
    live.session = session
    live.received = 0
    live.resumed = resumeId !== undefined
    live.listeners = [
      session.onItem((item) => {
        live.received++
        this.upsert(live, item)
      }),
      session.onFact((fact) => this.fact(live, fact)),
      session.onExit(({ error }) => this.exited(live, session, error))
    ]
    live.record.nativeId = session.nativeId
    await this.save(live)
    return session
  }

  private upsert(live: Live, item: SessionItem): void {
    live.items.set(item.id, item)
    live.journal.append(item)
    this.broadcast(live, { type: 'item', item })
    if (item.kind === 'approval') this.approvalChanged(live, item.id, item.resolved)
    if (item.kind === 'turn' && item.state === 'ended') this.turnEnded(live)
  }

  private approvalChanged(live: Live, id: string, resolved: string | undefined): void {
    if (!resolved) {
      live.approvals.add(id)
      this.setStatus(live, 'needs-input')
      this.attention.fire({ sessionId: live.record.id, reason: 'needs-input' })
      return
    }
    live.approvals.delete(id)
    if (live.approvals.size === 0 && live.status === 'needs-input') this.setStatus(live, 'running')
  }

  private turnEnded(live: Live): void {
    live.journal.flush()
    live.record.updatedAt = new Date().toISOString()
    void this.save(live)
    live.approvals.clear()
    this.setStatus(live, 'idle')
    this.attention.fire({ sessionId: live.record.id, reason: 'turn-ended' })
    const next = live.queue.shift()
    if (!next) return
    this.broadcast(live, { type: 'queue', queue: [...live.queue] })
    void this.send(live, next.parts)
  }

  private fact(live: Live, fact: SessionFact): void {
    live.record.facts[fact.kind] = fact
    void this.save(live)
    this.broadcast(live, { type: 'fact', fact })
  }

  private exited(live: Live, session: ProviderSession, error: string | undefined): void {
    if (live.session !== session) return
    live.session = undefined
    this.detach(live)
    live.journal.flush()
    if (!error) {
      if (live.status !== 'idle') this.setStatus(live, 'stopped')
      return
    }
    if (live.resumed && live.received === 0) {
      live.record.hasTurns = false
      void this.save(live)
      error += '\nThe next message starts a new agent session. Earlier messages stay here, but the agent will not remember them.'
    }
    this.fail(live, error)
  }

  private detach(live: Live): void {
    for (const listener of live.listeners) listener.dispose()
    live.listeners = []
  }

  private fail(live: Live, text: string): void {
    this.upsert(live, { kind: 'notice', id: `notice:${randomUUID()}`, level: 'error', text, action: 'retry' })
    live.approvals.clear()
    this.setStatus(live, 'error')
  }

  private setStatus(live: Live, status: SessionStatus): void {
    if (live.status === status) return
    live.status = status
    this.broadcast(live, { type: 'status', status })
    this.changed.fire()
  }

  private broadcast(live: Live, event: SessionEvent): void {
    for (const subscriber of [...live.subscribers]) subscriber(event)
  }

  private async save(live: Live): Promise<void> {
    await this.deps.store.put(live.record)
  }
}

/** Items from a previous run that can no longer change. */
function settled(item: SessionItem): SessionItem {
  if (item.kind === 'approval' && !item.resolved) return { ...item, resolved: 'expired' }
  if ((item.kind === 'message' && item.role === 'assistant') || item.kind === 'thought') {
    return item.streaming ? { ...item, streaming: false } : item
  }
  return item
}

function titleFrom(parts: PromptPart[]): string {
  for (const part of parts) {
    if (part.type !== 'text') continue
    const line = part.text
      .split('\n')
      .map((value) => value.trim())
      .find(Boolean)
    if (line) return line.length > MAX_TITLE ? `${line.slice(0, MAX_TITLE - 1)}…` : line
  }
  return NEW_TITLE
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
```

- [ ] **Step 5: Run tests and typecheck**

Run: `pnpm test && pnpm typecheck`
Expected: PASS, all tests (13 in `manager.test.ts`); typecheck clean.

If the event-order assertion in *sends a prompt, titles the session…* fails, print `events` and compare with this sequence: snapshot → status `running` → item user message → (fake ends turn) item turn → status `idle`. The fake emits no `turn started` item; real providers do.

- [ ] **Step 6: Commit**

```bash
git add src/sessions/manager.ts test/fake-provider.ts test/sessions/manager.test.ts
git commit -m "feat(sessions): add the session manager"
```

---

### Task 10: Claude provider

**Files:**
- Create: `src/providers/claude/provider.ts`

The provider wraps the SDK `query()` that the POC proved (`src/claude-session.ts`, left in place for the POC UI until plan 2). It has no unit test: its logic is the SDK call, which Task 11's fixture and Task 12's live smoke cover. Decisions it encodes:
- `sessionId` is generated up front for new sessions (SDK option), so `nativeId` is known immediately; resumed sessions pass `resume`.
- Initial facts (mode, models, MCP) are emitted after awaiting the CLI, so the manager has subscribed.
- `allowDangerouslySkipPermissions: true` only permits switching to full access later; the starting mode is still the record's.
- `AskUserQuestion` is denied with a message, since the MVP does not render questions.
- The POC finding stands: an `allow` must echo `updatedInput`.

- [ ] **Step 1: Write the provider**

`src/providers/claude/provider.ts`:

```ts
import { execFile } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { promisify } from 'node:util'
import type {
  CanUseTool,
  PermissionResult,
  PermissionUpdate,
  Query,
  PermissionMode as SdkPermissionMode,
  SDKUserMessage
} from '@anthropic-ai/claude-agent-sdk'
import { Emitter } from '../../core/emitter'
import type {
  ApprovalItem,
  OpenOptions,
  PermissionMode,
  PromptPart,
  ProviderDefinition,
  ProviderSession,
  ProviderState,
  SessionFact,
  SessionItem
} from '../../core/types'
import { type Env, findOnPath } from '../../env'
import { encodePrompt } from './encode'
import { approvalDetail } from './tools'
import { ClaudeTranslator } from './translate'

const run = promisify(execFile)

type QueryFn = typeof import('@anthropic-ai/claude-agent-sdk').query
type ApprovalContext = Parameters<CanUseTool>[2]
type PendingApproval = {
  item: ApprovalItem
  input: Record<string, unknown>
  suggestions?: PermissionUpdate[]
  resolve: (result: PermissionResult) => void
}

const MODES: Record<PermissionMode, SdkPermissionMode> = {
  ask: 'default',
  'accept-edits': 'acceptEdits',
  plan: 'plan',
  'full-access': 'bypassPermissions'
}
const MODE_LIST: readonly PermissionMode[] = ['ask', 'accept-edits', 'plan', 'full-access']

/** An inherited API key would bill the API instead of the claude.ai subscription. */
export function claudeEnv(env: Env): Env {
  const copy = { ...env }
  delete copy.ANTHROPIC_API_KEY
  return copy
}

export const claudeProvider: ProviderDefinition = {
  id: 'claude',
  label: 'Claude',
  cli: { command: 'claude', installUrl: 'https://docs.anthropic.com/en/docs/claude-code/setup' },
  signInCommand: 'claude auth login --claudeai',
  capabilities: new Set(['resume', 'interrupt', 'models', 'setModel', 'modes', 'setMode', 'mcpStatus', 'context']),
  modes: MODE_LIST,

  async probe(env: Env): Promise<ProviderState> {
    const path = findOnPath(env, 'claude')
    if (!path) return { status: 'not-installed' }
    const options = { env: claudeEnv(env), timeout: 15_000 }
    try {
      const [version, auth] = await Promise.all([run(path, ['--version'], options), authStatus(path, options)])
      return {
        status: auth.loggedIn ? 'signed-in' : 'signed-out',
        version: version.stdout.trim().split(' ')[0],
        account: auth.email
      }
    } catch {
      return { status: 'unknown' }
    }
  },

  async open(options: OpenOptions): Promise<ProviderSession> {
    const path = findOnPath(options.env, 'claude')
    if (!path) throw new Error('The claude CLI was not found on PATH.')
    // Loaded on first use so activating the extension stays fast.
    const { query } = await import('@anthropic-ai/claude-agent-sdk')
    return new ClaudeSession(query, path, options)
  }
}

/** `claude auth status` prints JSON; it may exit non-zero when signed out. */
async function authStatus(
  path: string,
  options: { env: Env; timeout: number }
): Promise<{ loggedIn: boolean; email?: string }> {
  try {
    const { stdout } = await run(path, ['auth', 'status'], options)
    return JSON.parse(stdout)
  } catch (error) {
    const stdout = (error as { stdout?: string }).stdout
    return stdout ? JSON.parse(stdout) : { loggedIn: false }
  }
}

class ClaudeSession implements ProviderSession {
  readonly nativeId: string
  private readonly items = new Emitter<SessionItem>()
  private readonly facts = new Emitter<SessionFact>()
  private readonly exits = new Emitter<{ error?: string }>()
  readonly onItem = this.items.event
  readonly onFact = this.facts.event
  readonly onExit = this.exits.event
  private readonly translator = new ClaudeTranslator((item) => this.items.fire(item))
  private readonly query: Query
  private readonly inbox: SDKUserMessage[] = []
  private wake: (() => void) | null = null
  private closed = false
  private readonly approvals = new Map<string, PendingApproval>()
  private models: { id: string; label: string }[] = []
  private model: string

  constructor(
    query: QueryFn,
    cliPath: string,
    private readonly options: OpenOptions
  ) {
    this.nativeId = options.resumeId ?? randomUUID()
    this.model = options.model ?? 'default'
    this.query = query({
      prompt: this.messages(),
      options: {
        pathToClaudeCodeExecutable: cliPath,
        cwd: options.cwd,
        env: claudeEnv(options.env),
        model: options.model,
        includePartialMessages: true,
        systemPrompt: { type: 'preset', preset: 'claude_code' },
        settingSources: ['user', 'project', 'local'],
        permissionMode: MODES[options.mode],
        // Permits switching to full access mid-session; the starting mode is still options.mode.
        allowDangerouslySkipPermissions: true,
        ...(options.resumeId ? { resume: options.resumeId } : { sessionId: this.nativeId }),
        canUseTool: (toolName, input, context) => this.requestApproval(toolName, input, context)
      }
    })
    void this.pump()
    void this.loadFacts()
  }

  async prompt(parts: PromptPart[]): Promise<void> {
    this.translator.startTurn()
    this.inbox.push({
      type: 'user',
      message: { role: 'user', content: encodePrompt(parts, this.options.cwd) },
      parent_tool_use_id: null
    })
    this.wake?.()
  }

  async cancel(): Promise<void> {
    this.translator.interrupted()
    await this.query.interrupt()
  }

  async setModel(id: string): Promise<void> {
    await this.query.setModel(id)
    this.model = id
    this.facts.fire({ kind: 'model', current: id, available: this.models })
  }

  async setMode(mode: PermissionMode): Promise<void> {
    await this.query.setPermissionMode(MODES[mode])
    this.facts.fire({ kind: 'mode', current: mode, available: MODE_LIST })
  }

  answer(itemId: string, optionId: string): void {
    const pending = this.approvals.get(itemId)
    if (!pending) return
    this.approvals.delete(itemId)
    this.items.fire({ ...pending.item, resolved: optionId })
    if (optionId === 'deny') return pending.resolve({ behavior: 'deny', message: 'The user denied this action.' })
    // The CLI rejects an allow without updatedInput, although the SDK types mark it optional.
    pending.resolve({
      behavior: 'allow',
      updatedInput: pending.input,
      updatedPermissions: optionId === 'always' ? pending.suggestions : undefined
    })
  }

  async refreshMcp(): Promise<void> {
    const servers = await this.query.mcpServerStatus()
    this.facts.fire({
      kind: 'mcp',
      servers: servers.map((server) => ({
        name: server.name,
        status: server.status,
        scope: server.scope,
        error: server.error,
        tools: (server.tools ?? []).map((tool) => tool.name)
      }))
    })
  }

  async reconnectMcp(server: string): Promise<void> {
    await this.query.reconnectMcpServer(server)
    await this.refreshMcp()
  }

  async dispose(): Promise<void> {
    this.closed = true
    this.wake?.()
    for (const id of [...this.approvals.keys()]) this.answer(id, 'deny')
    this.query.close()
  }

  private async *messages(): AsyncGenerator<SDKUserMessage> {
    while (!this.closed) {
      const next = this.inbox.shift()
      if (next) {
        yield next
        continue
      }
      await new Promise<void>((resolve) => (this.wake = resolve))
      this.wake = null
    }
  }

  private async pump(): Promise<void> {
    let error: string | undefined
    try {
      for await (const message of this.query) {
        this.translator.feed(message)
        if (message.type === 'system' && message.subtype === 'init' && message.model !== this.model) {
          this.model = message.model
          this.facts.fire({ kind: 'model', current: this.model, available: this.models })
        }
        if (message.type === 'result') void this.refreshContext()
      }
    } catch (caught) {
      if (!this.closed) error = caught instanceof Error ? caught.message : String(caught)
    }
    this.exits.fire({ error })
  }

  private async loadFacts(): Promise<void> {
    try {
      const models = await this.query.supportedModels()
      this.models = models.map((model) => ({ id: model.value, label: model.displayName }))
    } catch {
      // The model picker then offers only the current model.
    }
    this.facts.fire({ kind: 'mode', current: this.options.mode, available: MODE_LIST })
    this.facts.fire({ kind: 'model', current: this.model, available: this.models })
    await this.refreshMcp().catch(() => undefined)
  }

  private async refreshContext(): Promise<void> {
    try {
      const usage = await this.query.getContextUsage({ detail: 'summary' })
      this.facts.fire({ kind: 'context', usedTokens: usage.totalTokens, maxTokens: usage.maxTokens })
    } catch {
      // Older CLIs lack this request; the context meter stays hidden.
    }
  }

  private requestApproval(
    toolName: string,
    input: Record<string, unknown>,
    context: ApprovalContext
  ): Promise<PermissionResult> {
    if (toolName === 'AskUserQuestion') {
      return Promise.resolve({
        behavior: 'deny',
        message: 'This client cannot show questions yet. Ask the user in plain text instead.'
      })
    }
    const suggestions = context.suppressAlwaysAllowRule ? undefined : context.suggestions
    const item: ApprovalItem = {
      kind: 'approval',
      id: `approval:${context.toolUseID}`,
      title: context.title ?? `Allow ${toolName}?`,
      detail: approvalDetail(input),
      options: [
        { id: 'allow', label: 'Allow once' },
        ...(suggestions?.length ? [{ id: 'always', label: 'Always allow' }] : []),
        { id: 'deny', label: 'Deny' }
      ]
    }
    return new Promise((resolve) => {
      this.approvals.set(item.id, { item, input, suggestions, resolve })
      context.signal.addEventListener('abort', () => this.answer(item.id, 'deny'))
      this.items.fire(item)
    })
  }
}
```

- [ ] **Step 2: Typecheck**

Run: `pnpm typecheck`
Expected: clean. If an SDK name differs (for example the `PermissionMode` export or a `canUseTool` context field), look it up in `node_modules/@anthropic-ai/claude-agent-sdk/sdk.d.ts` and fix the reference; the behaviour above is what matters.

- [ ] **Step 3: Run the unit tests**

Run: `pnpm test`
Expected: PASS (nothing tests this file directly; this confirms nothing else broke).

- [ ] **Step 4: Commit**

```bash
git add src/providers/claude/provider.ts
git commit -m "feat(claude): add the Claude provider on the session contract"
```

---

### Task 11: Recorded Claude fixture

**Files:**
- Create: `scripts/record-claude.ts`
- Modify: `esbuild.mjs` (entry points)
- Create: `test/fixtures/claude/edit-turn.jsonl` (generated)
- Test: `test/providers/claude-fixture.test.ts`

The recorder runs one real edit turn with no user settings (`settingSources: []`), so no hooks, MCP servers, or account details end up in the fixture, and skips `system` and `rate_limit_event` messages for the same reason.

- [ ] **Step 1: Write the recorder**

`scripts/record-claude.ts`:

```ts
// Records a real Claude edit turn's SDK messages as a translator fixture.
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { captureEnv, findOnPath } from '../src/env'
import { claudeEnv } from '../src/providers/claude/provider'

const OUT = 'test/fixtures/claude/edit-turn.jsonl'

async function main(): Promise<void> {
  const env = await captureEnv()
  const cli = findOnPath(env, 'claude')
  if (!cli) throw new Error('claude CLI not found on the login-shell PATH')
  const { query } = await import('@anthropic-ai/claude-agent-sdk')
  const cwd = mkdtempSync(join(tmpdir(), 'agentdeck-record-'))
  writeFileSync(join(cwd, 'notes.md'), '# Notes\n\nhello world\n')

  const lines: string[] = []
  const messages = query({
    prompt: 'In notes.md, replace "hello world" with "goodbye world" using the Edit tool. Then reply with one short sentence.',
    options: {
      pathToClaudeCodeExecutable: cli,
      cwd,
      env: claudeEnv(env),
      includePartialMessages: true,
      systemPrompt: { type: 'preset', preset: 'claude_code' },
      settingSources: [],
      permissionMode: 'acceptEdits'
    }
  })
  for await (const message of messages) {
    if (message.type === 'system' || message.type === 'rate_limit_event') continue
    lines.push(JSON.stringify(message))
  }
  mkdirSync('test/fixtures/claude', { recursive: true })
  writeFileSync(OUT, `${lines.join('\n')}\n`)
  console.log(`wrote ${lines.length} messages to ${OUT}`)
}

main().catch((error) => {
  console.error('RECORD FAILED:', error)
  process.exit(1)
})
```

- [ ] **Step 2: Add the recorder to the build**

In `esbuild.mjs`, change the `entryPoints` line to:

```js
  entryPoints: { extension: 'src/extension.ts', smoke: 'scripts/smoke.ts', 'record-claude': 'scripts/record-claude.ts' },
```

- [ ] **Step 3: Record**

Run: `pnpm build && node dist/record-claude.js`
Expected: `wrote N messages to test/fixtures/claude/edit-turn.jsonl` with N well above 10. This uses the signed-in `claude` and a little quota.

Check that the fixture holds nothing personal: `grep -c -i -E 'email|@gmail|oauth' test/fixtures/claude/edit-turn.jsonl` should print `0`. If not, stop and tell the user rather than committing it.

- [ ] **Step 4: Write the fixture test**

`test/providers/claude-fixture.test.ts`:

```ts
import { readFileSync } from 'node:fs'
import type { SDKMessage } from '@anthropic-ai/claude-agent-sdk'
import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import { ClaudeTranslator } from '../../src/providers/claude/translate'

function translateFixture(): SessionItem[] {
  const messages = readFileSync('test/fixtures/claude/edit-turn.jsonl', 'utf8')
    .trim()
    .split('\n')
    .map((line) => JSON.parse(line) as SDKMessage)
  const latest = new Map<string, SessionItem>()
  const translator = new ClaudeTranslator((item) => latest.set(item.id, item))
  translator.startTurn()
  for (const message of messages) translator.feed(message)
  return [...latest.values()]
}

describe('Claude fixture: an edit turn', () => {
  const items = translateFixture()

  it('completes an edit tool call', () => {
    expect(items.some((item) => item.kind === 'tool' && item.toolKind === 'edit' && item.status === 'done')).toBe(true)
  })

  it('shows the edit as a diff of notes.md', () => {
    const diff = items.find((item) => item.kind === 'diff')
    expect(diff).toMatchObject({ kind: 'diff', newText: expect.stringContaining('goodbye world') })
    expect(diff?.kind === 'diff' && diff.path.endsWith('notes.md')).toBe(true)
  })

  it('replies with finished text', () => {
    const replies = items.filter((item) => item.kind === 'message' && item.role === 'assistant')
    expect(replies.length).toBeGreaterThan(0)
    for (const reply of replies) expect(reply).toMatchObject({ streaming: false, text: expect.stringMatching(/\S/) })
  })

  it('ends the turn successfully', () => {
    // Started and ended share an id, so the folded turn item sits where the turn began.
    expect(items.find((item) => item.kind === 'turn')).toMatchObject({ kind: 'turn', state: 'ended', stopReason: 'success' })
  })
})
```

- [ ] **Step 5: Run tests**

Run: `pnpm test && pnpm typecheck`
Expected: PASS. If *replies with finished text* fails because a reply has `streaming: true`, the fixture lacks a `content_block_stop`; inspect the fixture's `stream_event` lines before changing the translator.

- [ ] **Step 6: Commit**

```bash
git add scripts/record-claude.ts esbuild.mjs test/fixtures/claude/edit-turn.jsonl test/providers/claude-fixture.test.ts
git commit -m "test(claude): record a real edit turn and check the translator against it"
```

---

### Task 12: Live smoke through the session manager

**Files:**
- Modify: `scripts/smoke.ts` (full replacement)
- Modify: `README.md` (*Live check* section)

The smoke drives the real stack: `SessionManager` → `claudeProvider` → the user's `claude`. It checks sign-in, MCP status before the first prompt, an approved edit, a second turn that remembers the first, and resume after the manager is disposed (a simulated VS Code reload).

- [ ] **Step 1: Replace the smoke script**

`scripts/smoke.ts`:

```ts
// Live check outside VS Code: sign-in, MCP status, an approved edit, memory across turns, and resume.
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { SessionFact } from '../src/core/types'
import { captureEnv } from '../src/env'
import { claudeProvider } from '../src/providers/claude/provider'
import { SessionManager } from '../src/sessions/manager'
import { SessionStore } from '../src/sessions/store'
import { MemoryMemento } from '../test/memory-memento'

const TIMEOUT_MS = 180_000

async function main(): Promise<void> {
  const env = await captureEnv()
  const state = await claudeProvider.probe(env)
  console.log('claude:', state)
  if (state.status !== 'signed-in') throw new Error('claude is not signed in')

  const cwd = mkdtempSync(join(tmpdir(), 'agentdeck-smoke-'))
  const file = join(cwd, 'notes.md')
  writeFileSync(file, '# Notes\n\nhello world\n')
  const memento = new MemoryMemento()
  const manager = () =>
    new SessionManager({
      providers: new Map([[claudeProvider.id, claudeProvider]]),
      store: new SessionStore(memento),
      journalDir: join(cwd, '.journal'),
      cwd,
      env: async () => env
    })

  const first = manager()
  const { id } = await first.create('claude')
  const mcp = waitForFact(first, id, 'mcp')
  await first.warm(id)
  const servers = await mcp
  console.log('mcp before first prompt:', servers.kind === 'mcp' ? servers.servers.map((s) => `${s.name}=${s.status}`) : [])

  await turn(first, id, 'In notes.md, replace "hello world" with "goodbye world". Use the Edit tool. Reply with one short sentence.')
  if (!readFileSync(file, 'utf8').includes('goodbye world')) throw new Error('edit was not applied')
  const recall = await turn(first, id, 'What word did you just replace? Answer with that single word only.')
  if (!/hello/i.test(recall)) throw new Error(`second turn lost context: ${JSON.stringify(recall)}`)
  await first.dispose()

  // A new manager over the same storage stands in for a VS Code reload.
  const second = manager()
  const resumed = await turn(second, id, 'Earlier in this conversation you replaced one word in notes.md. Which word did you remove? Answer with that single word only.')
  if (!/hello/i.test(resumed)) throw new Error(`resume lost context: ${JSON.stringify(resumed)}`)
  await second.dispose()
  console.log('SMOKE OK')
}

/** Sends a prompt, approves every tool, and returns the turn's assistant text. */
function turn(manager: SessionManager, id: string, text: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const replies = new Map<string, string>()
    const timer = setTimeout(() => reject(new Error(`turn timed out: ${text}`)), TIMEOUT_MS)
    const subscription = manager.subscribe(id, (event) => {
      if (event.type !== 'item') return
      const item = event.item
      if (item.kind === 'message' && item.role === 'assistant') replies.set(item.id, item.text)
      if (item.kind === 'approval' && !item.resolved) {
        console.log('approving:', item.title, item.detail ?? '')
        manager.answer(id, item.id, 'allow')
      }
      if (item.kind === 'tool' && item.status !== 'running') console.log(`tool ${item.status}:`, item.title)
      if (item.kind === 'notice') console.log(`notice (${item.level}):`, item.text)
      if (item.kind === 'turn' && item.state === 'ended') {
        clearTimeout(timer)
        subscription.dispose()
        const reply = [...replies.values()].join('\n')
        console.log('reply:', reply)
        resolve(reply)
      }
    })
    void manager.prompt(id, [{ type: 'text', text }])
  })
}

function waitForFact(manager: SessionManager, id: string, kind: SessionFact['kind']): Promise<SessionFact> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`no ${kind} fact`)), TIMEOUT_MS)
    const subscription = manager.subscribe(id, (event) => {
      if (event.type !== 'fact' || event.fact.kind !== kind) return
      clearTimeout(timer)
      subscription.dispose()
      resolve(event.fact)
    })
  })
}

main().catch((error) => {
  console.error('SMOKE FAILED:', error)
  process.exit(1)
})
```

- [ ] **Step 2: Build and run it**

Run: `pnpm typecheck && pnpm build && node dist/smoke.js`
Expected, in order: the probe result with `status: 'signed-in'`; an `mcp before first prompt:` line listing the user's servers (the same set `claude mcp list` shows); `approving: …` for the edit (unless the user's settings already allow it); `tool done: Edit …`; replies; and finally `SMOKE OK`. Exit code 0.

If the CLI exits at start with an unknown-option error, the installed `claude` is older than the SDK expects for `sessionId` or `allowDangerouslySkipPermissions`; report the version and the message to the user.

If the resume turn fails with a notice like `No conversation found`, the SDK's `sessionId` option may not persist the transcript under that id for the installed CLI. Report the notice text to the user; do not work around it silently.

- [ ] **Step 3: Update the README's live check**

In `README.md`, replace the *Live check* section's paragraph with:

```markdown
`node dist/smoke.js` (after `pnpm build`) drives a real Claude session through the session manager against a temporary folder: it checks sign-in, lists MCP servers before the first prompt, approves an edit, confirms a second turn remembers the first, and resumes the session after a simulated reload.

`node dist/record-claude.js` re-records the translator fixture in `test/fixtures/claude/` from a real edit turn. Run `pnpm test` afterwards.
```

- [ ] **Step 4: Run all tests once more**

Run: `pnpm test && pnpm typecheck`
Expected: PASS; typecheck clean.

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke.ts README.md
git commit -m "test: run the live smoke through the session manager, including resume"
```

---

## Done when

- `pnpm test` passes (emitter, env, encode, tools, translator, fixture, journal, store, manager).
- `pnpm typecheck` is clean.
- `node dist/smoke.js` prints `SMOKE OK` against the user's real Claude login.
- The POC still works: `pnpm run package`, install the VSIX, run **AgentDeck: New Claude Chat**. Plan 1 does not touch `src/extension.ts`, `src/claude-session.ts`, or `media/`.
