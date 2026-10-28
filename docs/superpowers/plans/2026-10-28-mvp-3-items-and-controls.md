# MVP plan 3: Chat items and controls — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first. Plan 2 must be complete.

**Goal:** Turn plan 2's compact item lines into the mockup's cards (collapsible tools, diffs with *Open diff*, plan), add the composer controls (model, permission mode, context meter, MCP popover with sign-in handoff and reconnect), and add the sessions tree, sidebar session switcher, sign-in banner, and status bar.

**Architecture:** New controls send new `WebviewMessage`s that `ChatSurfaces` routes to `SessionManager`. Provider-specific MCP sign-in is a `ProviderDefinition.mcpSignIn` hook, so the host stays provider-neutral. MCP status is re-read until no server is `pending` (plan 1's live run showed servers start `pending`). Diffs open in VS Code's diff editor through a read-only `TextDocumentContentProvider`. The sessions tree and status bar read `SessionManager.list()` and refresh on `onDidChange`.

**Tech Stack:** as plan 2; shadcn `collapsible`, `dropdown-menu`, `popover`, `tooltip` are already vendored.

---

## File structure

| File | Responsibility |
|---|---|
| `src/providers/mcp-settle.ts` | Re-read MCP status until it settles |
| `src/providers/claude/provider.ts` | Use it; add `mcpSignIn` |
| `src/core/types.ts` | `ProviderDefinition.mcpSignIn`, `McpSignIn` |
| `src/sessions/manager.ts` | `item()` lookup |
| `src/ui/protocol.ts` | New messages, `SessionSummary` |
| `src/ui/time.ts` | Relative time labels |
| `src/ui/diff-documents.ts` | Read-only documents for *Open diff* |
| `src/ui/chat-surfaces.ts` | Route the new messages; send session lists to the sidebar |
| `src/ui/sessions-tree.ts` | Sessions tree view |
| `src/ui/status-bar.ts` | Running / needs-input counts |
| `src/extension.ts`, `package.json` | Register the tree, status bar, and commands |
| `webview/app/state.ts` | `sessions` in state |
| `webview/app/items/tool-card.tsx`, `diff-card.tsx`, `plan-card.tsx` | Replace the plan 2 lines |
| `webview/app/components/{model-picker,mode-picker,context-meter,mcp-popover,session-switcher,sign-in-banner}.tsx` | New controls |
| `webview/preview/scenario.ts` | Facts and sessions for screenshots |

---

### Task 1: MCP status settles

**Files:**
- Create: `src/providers/mcp-settle.ts`
- Test: `test/providers/mcp-settle.test.ts`
- Modify: `src/providers/claude/provider.ts` (`refreshMcp`)

- [ ] **Step 1: Write the failing test**

`test/providers/mcp-settle.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { McpServer } from '../../src/core/types'
import { refreshUntilSettled } from '../../src/providers/mcp-settle'

const server = (status: McpServer['status']): McpServer => ({ name: 'notion', status, tools: [] })

function reader(...results: McpServer[][]) {
  let calls = 0
  return {
    read: async () => results[Math.min(calls++, results.length - 1)],
    calls: () => calls
  }
}

describe('refreshUntilSettled', () => {
  it('re-reads while a server is pending and emits every reading', async () => {
    const { read, calls } = reader([server('pending')], [server('pending')], [server('connected')])
    const emitted: McpServer[][] = []
    await refreshUntilSettled(read, (servers) => emitted.push(servers), { intervalMs: 0, attempts: 10 })
    expect(calls()).toBe(3)
    expect(emitted.at(-1)).toEqual([server('connected')])
  })

  it('stops after the attempt limit', async () => {
    const { read, calls } = reader([server('pending')])
    await refreshUntilSettled(read, () => {}, { intervalMs: 0, attempts: 4 })
    expect(calls()).toBe(4)
  })

  it('stops when the session closes', async () => {
    const { read, calls } = reader([server('pending')])
    let closed = false
    await refreshUntilSettled(
      read,
      () => {
        closed = true
      },
      { intervalMs: 0, attempts: 10, closed: () => closed }
    )
    expect(calls()).toBe(1)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm test test/providers/mcp-settle.test.ts`
Expected: FAIL, cannot resolve `mcp-settle`.

- [ ] **Step 3: Implement**

`src/providers/mcp-settle.ts`:

```ts
import type { McpServer } from '../core/types'

type Options = { intervalMs: number; attempts: number; closed?: () => boolean }

/** Servers report `pending` while they connect; re-read until none is, so the UI settles on real states. */
export async function refreshUntilSettled(
  read: () => Promise<McpServer[]>,
  emit: (servers: McpServer[]) => void,
  { intervalMs, attempts, closed = () => false }: Options
): Promise<void> {
  for (let attempt = 1; attempt <= attempts; attempt++) {
    const servers = await read()
    emit(servers)
    if (!servers.some((server) => server.status === 'pending') || attempt === attempts) return
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
    if (closed()) return
  }
}
```

- [ ] **Step 4: Use it in the Claude provider**

In `src/providers/claude/provider.ts`, add the import:

```ts
import { refreshUntilSettled } from '../mcp-settle'
```

and replace the whole `refreshMcp` method with:

```ts
  async refreshMcp(): Promise<void> {
    await refreshUntilSettled(
      async () =>
        (await this.query.mcpServerStatus()).map((server) => ({
          name: server.name,
          status: server.status,
          scope: server.scope,
          error: server.error,
          tools: (server.tools ?? []).map((tool) => tool.name)
        })),
      (servers) => this.facts.fire({ kind: 'mcp', servers }),
      { intervalMs: 1000, attempts: 30, closed: () => this.closed }
    )
  }
```

- [ ] **Step 5: Run tests and typecheck**

Run: `pnpm test && pnpm typecheck`
Expected: PASS; clean.

- [ ] **Step 6: Commit**

```bash
git add src/providers/mcp-settle.ts src/providers/claude/provider.ts test/providers/mcp-settle.test.ts
git commit -m "feat(providers): re-read MCP status until servers finish connecting"
```

---

### Task 2: MCP sign-in hook and item lookup

**Files:**
- Modify: `src/core/types.ts`, `src/providers/claude/provider.ts`, `src/sessions/manager.ts`
- Test: `test/providers/claude-mcp-sign-in.test.ts`, `test/sessions/manager.test.ts` (one test added)

- [ ] **Step 1: Write the failing tests**

`test/providers/claude-mcp-sign-in.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { claudeProvider } from '../../src/providers/claude/provider'

describe('Claude MCP sign-in', () => {
  it('sends claude.ai connectors to the connector settings page', () => {
    expect(claudeProvider.mcpSignIn?.('claude.ai Notion', 'claudeai')).toEqual({
      kind: 'url',
      url: 'https://claude.ai/settings/connectors'
    })
  })

  it('runs Claude for its /mcp flow for other servers', () => {
    expect(claudeProvider.mcpSignIn?.('linear', 'user')).toEqual({
      kind: 'terminal',
      command: 'claude',
      hint: 'In the terminal, run /mcp and choose linear to sign in. Then press Reconnect in AgentDeck.'
    })
  })
})
```

In `test/sessions/manager.test.ts`, add inside the `describe` block:

```ts
  it('looks up an item by id', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.warm(id)
    sessions[0].emit({ kind: 'notice', id: 'n1', level: 'info', text: 'hello' })
    expect(manager.item(id, 'n1')).toMatchObject({ text: 'hello' })
    expect(manager.item(id, 'missing')).toBeUndefined()
  })
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pnpm test`
Expected: FAIL: `mcpSignIn` is undefined and `manager.item` is not a function.

- [ ] **Step 3: Add the hook to the contract**

In `src/core/types.ts`, add before `export interface ProviderDefinition`:

```ts
/** Where a user signs in to an MCP server: a web page, or a CLI flow in a terminal. */
export type McpSignIn = { kind: 'url'; url: string } | { kind: 'terminal'; command: string; hint: string }
```

and add to `ProviderDefinition`, after `open(...)`:

```ts
  mcpSignIn?(server: string, scope: string | undefined): McpSignIn
```

- [ ] **Step 4: Implement it for Claude**

In `src/providers/claude/provider.ts`, add `McpSignIn` to the type import from `../../core/types`, and add this member to the `claudeProvider` object after `open`:

```ts
  mcpSignIn(server: string, scope: string | undefined): McpSignIn {
    if (scope === 'claudeai') return { kind: 'url', url: 'https://claude.ai/settings/connectors' }
    return {
      kind: 'terminal',
      command: 'claude',
      hint: `In the terminal, run /mcp and choose ${server} to sign in. Then press Reconnect in AgentDeck.`
    }
  }
```

- [ ] **Step 5: Add `item()` to the manager**

In `src/sessions/manager.ts`, add after `answer(...)`:

```ts
  item(id: string, itemId: string): SessionItem | undefined {
    return this.live.get(id)?.items.get(itemId)
  }
```

- [ ] **Step 6: Run tests and typecheck**

Run: `pnpm test && pnpm typecheck`
Expected: PASS; clean.

- [ ] **Step 7: Commit**

```bash
git add src/core/types.ts src/providers/claude/provider.ts src/sessions/manager.ts test/providers/claude-mcp-sign-in.test.ts test/sessions/manager.test.ts
git commit -m "feat: add MCP sign-in handoff per provider and item lookup"
```

---

### Task 3: Protocol, state, and relative time

**Files:**
- Modify: `src/ui/protocol.ts`, `webview/app/state.ts`
- Create: `src/ui/time.ts`
- Test: `test/webview/state.test.ts` (one test added), `test/ui/time.test.ts`

- [ ] **Step 1: Write the failing tests**

`test/ui/time.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { relativeTime } from '../../src/ui/time'

const now = Date.parse('2026-10-28T12:00:00.000Z')
const ago = (ms: number) => new Date(now - ms).toISOString()

describe('relativeTime', () => {
  it('labels recent times compactly', () => {
    expect(relativeTime(ago(20_000), now)).toBe('now')
    expect(relativeTime(ago(5 * 60_000), now)).toBe('5m')
    expect(relativeTime(ago(3 * 3_600_000), now)).toBe('3h')
    expect(relativeTime(ago(2 * 86_400_000), now)).toBe('2d')
    expect(relativeTime(ago(40 * 86_400_000), now)).toBe('5w')
  })
})
```

In `test/webview/state.test.ts`, add inside the `describe` block:

```ts
  it('keeps the session list for the switcher', () => {
    const sessions = [{ id: 's1', title: 'Chat', providerId: 'claude', status: 'idle' as const, updatedAt: 't' }]
    expect(run({ type: 'sessions', sessions }).sessions).toEqual(sessions)
  })
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pnpm test`
Expected: FAIL on the new tests.

- [ ] **Step 3: Relative time**

`src/ui/time.ts`:

```ts
const UNITS: [label: string, ms: number][] = [
  ['w', 7 * 86_400_000],
  ['d', 86_400_000],
  ['h', 3_600_000],
  ['m', 60_000]
]

/** Compact age for lists: now, 5m, 3h, 2d, 5w. */
export function relativeTime(iso: string, now = Date.now()): string {
  const elapsed = now - Date.parse(iso)
  for (const [label, ms] of UNITS) {
    if (elapsed >= ms) return `${Math.floor(elapsed / ms)}${label}`
  }
  return 'now'
}
```

- [ ] **Step 4: Protocol additions**

In `src/ui/protocol.ts`:
- change the first import to `import type { Capability, PermissionMode, ProviderState } from '../core/types'` (unchanged) and add `import type { SessionStatus } from '../sessions/store'`;
- add after `ProviderInfo`:

```ts
export type SessionSummary = { id: string; title: string; providerId: string; status: SessionStatus; updatedAt: string }
```

- add to `HostMessage`:

```ts
  /** Recent sessions, for the sidebar's session switcher. */
  | { type: 'sessions'; sessions: SessionSummary[] }
```

- add to `WebviewMessage`:

```ts
  | { type: 'setModel'; model: string }
  | { type: 'setMode'; mode: PermissionMode }
  | { type: 'refreshMcp' }
  | { type: 'reconnectMcp'; server: string }
  | { type: 'mcpSignIn'; server: string; scope?: string }
  | { type: 'openDiff'; itemId: string }
  | { type: 'switchSession'; sessionId: string }
```

- [ ] **Step 5: State**

In `webview/app/state.ts`:
- import `SessionSummary` alongside the other protocol types;
- add `sessions: SessionSummary[]` to `ChatState` (after `editorContext`) and `sessions: []` to `initialState`;
- add a case to `reduce`, before `case 'session'`:

```ts
    case 'sessions':
      return { ...state, sessions: message.sessions }
```

- in the `'empty'` case, keep the list: `return { ...initialState, provider: state.provider, editorContext: state.editorContext, sessions: state.sessions, empty: true }`.

- [ ] **Step 6: Run tests and typecheck**

Run: `pnpm test && pnpm typecheck`
Expected: PASS; clean. `chat-surfaces.ts` still compiles because new `WebviewMessage` variants only add cases it does not yet handle (its `switch` has no exhaustiveness check).

- [ ] **Step 7: Commit**

```bash
git add src/ui/protocol.ts src/ui/time.ts webview/app/state.ts test/ui/time.test.ts test/webview/state.test.ts
git commit -m "feat(ui): add control messages, session summaries, and relative time"
```

---

### Task 4: Tool, diff, and plan cards

**Files:**
- Create: `webview/app/items/tool-card.tsx`, `webview/app/items/diff-card.tsx`, `webview/app/items/plan-card.tsx`
- Delete: `webview/app/items/tool-line.tsx`, `webview/app/items/diff-line.tsx`, `webview/app/items/plan-list.tsx`
- Modify: `webview/app/items/item-view.tsx`

- [ ] **Step 1: Tool card**

`webview/app/items/tool-card.tsx`:

```tsx
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'
import type { ToolItem, ToolKind } from '../../../src/core/types'
import { Codicon } from '../components/codicon'

const ICONS: Record<ToolKind, string> = {
  read: 'file',
  edit: 'edit',
  execute: 'terminal',
  search: 'search',
  fetch: 'globe',
  mcp: 'plug',
  other: 'tools'
}

const STATUS: Record<ToolItem['status'], { label: string; icon: string; className: string }> = {
  running: { label: 'Running', icon: 'loading', className: 'bg-info/15 text-info' },
  done: { label: 'Completed', icon: 'check', className: 'bg-success/15 text-success' },
  failed: { label: 'Failed', icon: 'close', className: 'bg-destructive/15 text-destructive' }
}

export function ToolCard({ item }: { item: ToolItem }) {
  const [verb, ...rest] = item.title.split(' ')
  const status = STATUS[item.status]
  const input = item.input === undefined ? null : JSON.stringify(item.input, null, 2)
  return (
    <Collapsible defaultOpen={item.status === 'failed'} className="group rounded-md border">
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-accent/50">
        <Codicon name={ICONS[item.toolKind]} className="text-muted-foreground" />
        <span className="font-medium">{verb}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-muted-foreground">{rest.join(' ')}</span>
        <span className={cn('inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium', status.className)}>
          <Codicon name={status.icon} size={10} spin={item.status === 'running'} />
          {status.label}
        </span>
        <Codicon name="chevron-down" className="text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-2 border-t px-3 py-2">
        {input && (
          <div>
            <div className="mb-1 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">Input</div>
            <pre className="max-h-40 overflow-auto rounded-md bg-code px-3 py-2 text-xs whitespace-pre-wrap">{input}</pre>
          </div>
        )}
        {item.output && (
          <div>
            <div className="mb-1 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">Output</div>
            <pre className="max-h-64 overflow-auto rounded-md bg-code px-3 py-2 text-xs whitespace-pre-wrap">{item.output}</pre>
          </div>
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}
```

- [ ] **Step 2: Diff card**

`webview/app/items/diff-card.tsx`:

```tsx
import { Button } from '@/components/ui/button'
import type { DiffItem } from '../../../src/core/types'
import { Codicon } from '../components/codicon'
import { fileName } from '../format'
import { send } from '../host'

const MAX_LINES = 200

export function DiffCard({ item }: { item: DiffItem }) {
  const removed = item.oldText === null ? [] : item.oldText.split('\n')
  const added = item.newText.split('\n')
  const rows = [...removed.map((line) => ['-', line] as const), ...added.map((line) => ['+', line] as const)]
  return (
    <div className="overflow-hidden rounded-md border">
      <div className="flex items-center gap-2 border-b px-3 py-1.5 text-xs">
        <Codicon name="diff" className="text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate font-mono" title={item.path}>
          {fileName(item.path)}
        </span>
        <span className="text-success">+{added.length}</span>
        {removed.length > 0 && <span className="text-destructive">−{removed.length}</span>}
        <Button size="xs" variant="ghost" onClick={() => send({ type: 'openDiff', itemId: item.id })}>
          Open diff
        </Button>
      </div>
      <pre className="max-h-72 overflow-auto py-1 text-xs leading-5">
        {rows.slice(0, MAX_LINES).map(([sign, line], index) => (
          <div key={index} className={sign === '+' ? 'bg-diff-added px-3' : 'bg-diff-removed px-3'}>
            <span className="mr-2 text-muted-foreground select-none">{sign === '+' ? '+' : '−'}</span>
            {line}
          </div>
        ))}
        {rows.length > MAX_LINES && (
          <div className="px-3 text-muted-foreground">… {rows.length - MAX_LINES} more lines</div>
        )}
      </pre>
    </div>
  )
}
```

- [ ] **Step 3: Plan card**

`webview/app/items/plan-card.tsx`:

```tsx
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { PlanItem } from '../../../src/core/types'
import { Codicon } from '../components/codicon'

const ICONS = { pending: 'circle-large-outline', in_progress: 'loading', done: 'pass-filled' } as const

export function PlanCard({ item }: { item: PlanItem }) {
  const done = item.entries.filter((entry) => entry.status === 'done').length
  return (
    <Collapsible defaultOpen className="group rounded-md border">
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-accent/50">
        <Codicon name="checklist" className="text-muted-foreground" />
        <span className="font-medium">Plan</span>
        <span className="flex-1 text-muted-foreground">
          {done} of {item.entries.length} done
        </span>
        <Codicon name="chevron-down" className="text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="border-t px-3 py-2">
        <ul className="space-y-1 text-sm">
          {item.entries.map((entry, index) => (
            <li key={index} className="flex items-center gap-2">
              <Codicon
                name={ICONS[entry.status]}
                spin={entry.status === 'in_progress'}
                className={entry.status === 'done' ? 'text-success' : 'text-muted-foreground'}
              />
              <span className={entry.status === 'done' ? 'text-muted-foreground line-through' : ''}>{entry.text}</span>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  )
}
```

- [ ] **Step 4: Switch the item view over and remove the lines**

In `webview/app/items/item-view.tsx`, replace the imports of `DiffLine`, `PlanList`, and `ToolLine` with:

```tsx
import { DiffCard } from './diff-card'
import { PlanCard } from './plan-card'
import { ToolCard } from './tool-card'
```

and in the switch render `<ToolCard item={item} />`, `<DiffCard item={item} />`, and `<PlanCard item={item} />` for `tool`, `diff`, and `plan`. Then:

```bash
git rm webview/app/items/tool-line.tsx webview/app/items/diff-line.tsx webview/app/items/plan-list.tsx
grep -rn "tool-line\|diff-line\|plan-list\|ToolLine\|DiffLine\|PlanList" webview || echo CLEAN
```

Expected: `CLEAN`.

- [ ] **Step 5: Add a plan to the preview scenario**

In `webview/preview/scenario.ts`, add this item to `items` right after the `tool3` entry:

```ts
  {
    kind: 'plan',
    id: 'plan',
    entries: [
      { text: 'Find why the retry test is flaky', status: 'done' },
      { text: 'Schedule the backoff synchronously', status: 'in_progress' },
      { text: 'Run the test 20 times', status: 'pending' }
    ]
  },
```

- [ ] **Step 6: Build and review screenshots**

Run: `pnpm typecheck && pnpm test && pnpm build:preview && pnpm screenshot dark && pnpm screenshot light`
Expected: clean, passing, two PNGs. In both: tool cards show verb, monospace target, and a status pill (green *Completed*, red *Failed*); the failed `pnpm vitest` card is expanded with its input and output; the plan card shows "1 of 3 done" with a strike-through first entry; the diff card shows `retry.ts +2 −1` with tinted rows and *Open diff*.

- [ ] **Step 7: Commit**

```bash
git add -A webview/app/items webview/preview/scenario.ts
git commit -m "feat(webview): render tools, diffs, and plans as cards"
```

---

### Task 5: Composer controls

**Files:**
- Create: `webview/app/components/{model-picker,mode-picker,context-meter,mcp-popover}.tsx`
- Modify: `webview/app/components/composer.tsx` (toolbar), `webview/preview/scenario.ts` (facts)

- [ ] **Step 1: Model picker**

`webview/app/components/model-picker.tsx`:

```tsx
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import type { SessionFact } from '../../../src/core/types'
import { send } from '../host'
import { Codicon } from './codicon'

export function ModelPicker({ fact }: { fact?: Extract<SessionFact, { kind: 'model' }> }) {
  if (!fact) return null
  const label = fact.available.find((model) => model.id === fact.current)?.label ?? fact.current
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="xs" variant="ghost" className="text-muted-foreground">
          {label}
          <Codicon name="chevron-down" size={12} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuRadioGroup value={fact.current} onValueChange={(model) => send({ type: 'setModel', model })}>
          {fact.available.map((model) => (
            <DropdownMenuRadioItem key={model.id} value={model.id}>
              {model.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
```

- [ ] **Step 2: Mode picker**

`webview/app/components/mode-picker.tsx`:

```tsx
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import type { PermissionMode } from '../../../src/core/types'
import { send } from '../host'
import { Codicon } from './codicon'

const MODES: Record<PermissionMode, { label: string; icon: string }> = {
  ask: { label: 'Ask before edits', icon: 'shield' },
  'accept-edits': { label: 'Accept edits', icon: 'edit' },
  plan: { label: 'Plan', icon: 'checklist' },
  'full-access': { label: 'Full access', icon: 'warning' }
}

export function ModePicker({ current, available }: { current: PermissionMode; available: readonly PermissionMode[] }) {
  if (available.length < 2) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="xs" variant="ghost" className="text-muted-foreground">
          <Codicon name={MODES[current].icon} size={12} />
          {MODES[current].label}
          <Codicon name="chevron-down" size={12} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuRadioGroup value={current} onValueChange={(mode) => send({ type: 'setMode', mode: mode as PermissionMode })}>
          {available.map((mode) => (
            <DropdownMenuRadioItem key={mode} value={mode}>
              <Codicon name={MODES[mode].icon} size={12} />
              {MODES[mode].label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
```

- [ ] **Step 3: Context meter**

`webview/app/components/context-meter.tsx`:

```tsx
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { SessionFact } from '../../../src/core/types'

const RADIUS = 6
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

export function ContextMeter({ fact }: { fact?: Extract<SessionFact, { kind: 'context' }> }) {
  if (!fact || fact.maxTokens <= 0) return null
  const ratio = Math.min(fact.usedTokens / fact.maxTokens, 1)
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex items-center gap-1 px-1 text-xs text-muted-foreground">
          <svg width="16" height="16" viewBox="0 0 16 16" className="-rotate-90" aria-hidden>
            <circle cx="8" cy="8" r={RADIUS} fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2" />
            <circle
              cx="8"
              cy="8"
              r={RADIUS}
              fill="none"
              stroke="var(--info)"
              strokeWidth="2"
              strokeLinecap="round"
              strokeDasharray={CIRCUMFERENCE}
              strokeDashoffset={CIRCUMFERENCE * (1 - ratio)}
            />
          </svg>
          {Math.round(ratio * 100)}%
        </span>
      </TooltipTrigger>
      <TooltipContent>
        {fact.usedTokens.toLocaleString()} of {fact.maxTokens.toLocaleString()} context tokens used
      </TooltipContent>
    </Tooltip>
  )
}
```

- [ ] **Step 4: MCP popover**

`webview/app/components/mcp-popover.tsx`:

```tsx
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import type { McpServer, SessionFact } from '../../../src/core/types'
import { send } from '../host'
import { Codicon } from './codicon'

const STATES: Record<McpServer['status'], { label: string; dot: string }> = {
  connected: { label: 'Connected', dot: 'bg-success' },
  failed: { label: 'Failed', dot: 'bg-destructive' },
  'needs-auth': { label: 'Needs sign-in', dot: 'bg-warning' },
  pending: { label: 'Connecting…', dot: 'bg-muted-foreground' },
  disabled: { label: 'Disabled', dot: 'bg-muted-foreground/40' }
}

export function McpPopover({ fact }: { fact?: Extract<SessionFact, { kind: 'mcp' }> }) {
  if (!fact) return null
  const connected = fact.servers.filter((server) => server.status === 'connected').length
  const attention = fact.servers.some((server) => server.status === 'failed' || server.status === 'needs-auth')
  return (
    <Popover onOpenChange={(open) => open && send({ type: 'refreshMcp' })}>
      <PopoverTrigger asChild>
        <Button size="xs" variant="ghost" className="text-muted-foreground">
          <Codicon name="plug" size={12} />
          MCP {connected}
          {attention && <span className="size-1.5 rounded-full bg-warning" aria-label="Some servers need attention" />}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-0">
        <div className="flex items-center justify-between border-b px-3 py-2 text-xs font-medium">
          MCP servers
          <Button size="icon-xs" variant="ghost" aria-label="Refresh" onClick={() => send({ type: 'refreshMcp' })}>
            <Codicon name="refresh" size={12} />
          </Button>
        </div>
        {fact.servers.length === 0 ? (
          <p className="px-3 py-3 text-xs text-muted-foreground">No MCP servers are configured.</p>
        ) : (
          <ul className="max-h-80 overflow-auto py-1">
            {fact.servers.map((server) => (
              <McpServerRow key={server.name} server={server} />
            ))}
          </ul>
        )}
        <p className="border-t px-3 py-2 text-[11px] text-muted-foreground">
          Servers and their sign-ins come from the CLI's own configuration.
        </p>
      </PopoverContent>
    </Popover>
  )
}

function McpServerRow({ server }: { server: McpServer }) {
  const state = STATES[server.status]
  const details = [state.label, server.tools.length > 0 && `${server.tools.length} tools`, server.scope].filter(Boolean)
  return (
    <li className="flex items-start gap-2 px-3 py-1.5 text-xs">
      <span className={cn('mt-1 size-2 shrink-0 rounded-full', state.dot)} />
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{server.name}</div>
        <div className="truncate text-muted-foreground">{details.join(' · ')}</div>
        {server.error && <div className="mt-0.5 break-words text-destructive">{server.error}</div>}
      </div>
      {server.status === 'needs-auth' && (
        <Button
          size="xs"
          variant="secondary"
          onClick={() => send({ type: 'mcpSignIn', server: server.name, scope: server.scope })}
        >
          Sign in
        </Button>
      )}
      {(server.status === 'needs-auth' || server.status === 'failed') && (
        <Button size="xs" variant="ghost" onClick={() => send({ type: 'reconnectMcp', server: server.name })}>
          Reconnect
        </Button>
      )}
    </li>
  )
}
```

- [ ] **Step 5: Put the controls in the composer toolbar**

In `webview/app/components/composer.tsx`, add imports:

```tsx
import { ContextMeter } from './context-meter'
import { McpPopover } from './mcp-popover'
import { ModelPicker } from './model-picker'
import { ModePicker } from './mode-picker'
```

and replace the toolbar's spacer line `<div className="flex-1" />` with:

```tsx
        <ModelPicker fact={state.facts.model?.kind === 'model' ? state.facts.model : undefined} />
        <ModePicker
          current={state.facts.mode?.kind === 'mode' ? state.facts.mode.current : (state.record?.mode ?? 'ask')}
          available={state.provider?.modes ?? []}
        />
        <McpPopover fact={state.facts.mcp?.kind === 'mcp' ? state.facts.mcp : undefined} />
        <div className="flex-1" />
        <ContextMeter fact={state.facts.context?.kind === 'context' ? state.facts.context : undefined} />
```

(`facts` is typed `Partial<Record<kind, SessionFact>>`, so each lookup narrows by `kind`.)

- [ ] **Step 6: Add facts to the preview scenario**

In `webview/preview/scenario.ts`, change `facts: {}` in `record` to:

```ts
  facts: {
    model: { kind: 'model', current: 'opus', available: [{ id: 'opus', label: 'Opus 5.5' }, { id: 'sonnet', label: 'Sonnet 5.5' }] },
    mode: { kind: 'mode', current: 'ask', available: ['ask', 'accept-edits', 'plan', 'full-access'] },
    context: { kind: 'context', usedTokens: 76_000, maxTokens: 200_000 },
    mcp: {
      kind: 'mcp',
      servers: [
        { name: 'screenscribe', status: 'connected', scope: 'user', tools: ['analyze_video', 'extract_frames'] },
        { name: 'claude.ai Notion', status: 'needs-auth', scope: 'claudeai', tools: [] },
        { name: 'linear', status: 'failed', scope: 'project', tools: [], error: 'Connection refused' }
      ]
    }
  }
```

and the provider's `modes: ['ask']` to `modes: ['ask', 'accept-edits', 'plan', 'full-access']`.

- [ ] **Step 7: Build and review screenshots**

Run: `pnpm typecheck && pnpm test && pnpm build:preview && pnpm screenshot dark && pnpm screenshot light`
Expected: the composer toolbar reads `Opus 5.5 ⌄ · 🛡 Ask before edits ⌄ · 🔌 MCP 1 •` on the left and `◔ 38%` before the Stop button on the right, matching the mockup's toolbar. Popovers and menus are closed in screenshots; that is expected.

- [ ] **Step 8: Commit**

```bash
git add webview/app/components webview/preview/scenario.ts
git commit -m "feat(webview): add model, mode, MCP, and context controls to the composer"
```

---

### Task 6: Host routing for the new controls

**Files:**
- Create: `src/ui/diff-documents.ts`
- Modify: `src/ui/chat-surfaces.ts`

- [ ] **Step 1: Read-only diff documents**

`src/ui/diff-documents.ts`:

```ts
import { basename } from 'node:path'
import * as vscode from 'vscode'
import type { SessionManager } from '../sessions/manager'

export const DIFF_SCHEME = 'agentdeck-diff'

type Side = 'before' | 'after'

/** Serves the two sides of a diff item, so VS Code's diff editor can show it. */
export class DiffDocuments implements vscode.TextDocumentContentProvider {
  constructor(private readonly manager: SessionManager) {}

  provideTextDocumentContent(uri: vscode.Uri): string {
    const { sessionId, itemId, side } = JSON.parse(uri.query) as { sessionId: string; itemId: string; side: Side }
    const item = this.manager.item(sessionId, itemId)
    if (item?.kind !== 'diff') return ''
    return side === 'before' ? (item.oldText ?? '') : item.newText
  }

  async open(sessionId: string, itemId: string): Promise<void> {
    const item = this.manager.item(sessionId, itemId)
    if (item?.kind !== 'diff') return
    const name = basename(item.path)
    const uri = (side: Side) =>
      vscode.Uri.from({ scheme: DIFF_SCHEME, path: `/${name}`, query: JSON.stringify({ sessionId, itemId, side }) })
    await vscode.commands.executeCommand('vscode.diff', uri('before'), uri('after'), `${name} (agent change)`)
  }
}
```

- [ ] **Step 2: Route the messages**

In `src/ui/chat-surfaces.ts`:

1. Add the import:

```ts
import type { DiffDocuments } from './diff-documents'
```

2. Add a constructor parameter after `editor`:

```ts
    private readonly diffs: DiffDocuments
```

3. In the constructor, also refresh the sidebar's session list on every change: change the `manager.onDidChange(...)` line to

```ts
      manager.onDidChange(() => {
        this.refreshTitles()
        this.postSessions()
      }),
```

4. In `handle`, in the `'ready'` case, add `this.postSessions(surface)` right after the `editorContext` post.

5. Add these cases to the `switch` in `handle`, before `case 'openFile'`:

```ts
      case 'setModel':
        if (sessionId) await this.manager.setModel(sessionId, message.model)
        return
      case 'setMode':
        if (sessionId) await this.manager.setMode(sessionId, message.mode)
        return
      case 'refreshMcp':
        if (sessionId) await this.manager.refreshMcp(sessionId)
        return
      case 'reconnectMcp':
        if (sessionId) await this.manager.reconnectMcp(sessionId, message.server)
        return
      case 'mcpSignIn':
        return this.mcpSignIn(surface, message.server, message.scope)
      case 'openDiff':
        if (sessionId) await this.diffs.open(sessionId, message.itemId)
        return
      case 'switchSession':
        if (surface.kind === 'view') await this.showInSidebar(message.sessionId)
        else this.openPanel(message.sessionId)
        return
```

6. Add these methods (next to `signIn`):

```ts
  /** Sends the user to where the MCP server's sign-in happens; the token stays with the provider. */
  private async mcpSignIn(surface: Surface, server: string, scope: string | undefined): Promise<void> {
    const provider = this.providers.get(this.providerOf(surface.sessionId))
    const target = provider?.mcpSignIn?.(server, scope)
    if (!target) return
    if (target.kind === 'url') {
      await vscode.env.openExternal(vscode.Uri.parse(target.url))
      return
    }
    const terminal = vscode.window.createTerminal({ name: `${server} sign-in` })
    terminal.show()
    terminal.sendText(target.command)
    void vscode.window.showInformationMessage(target.hint)
  }

  /** The sidebar's session switcher lists recent sessions. */
  private postSessions(surface = this.sidebar): void {
    if (!surface || surface.kind !== 'view') return
    const sessions = this.manager
      .list()
      .slice(0, 20)
      .map(({ record, status }) => ({
        id: record.id,
        title: record.title,
        providerId: record.providerId,
        status,
        updatedAt: record.updatedAt
      }))
    this.post(surface, { type: 'sessions', sessions })
  }
```

- [ ] **Step 3: Typecheck**

Run: `pnpm typecheck`
Expected: errors only in `src/extension.ts`, where `ChatSurfaces` is constructed without the new `diffs` argument; Task 8 fixes that. Everything else is clean.

- [ ] **Step 4: Commit**

```bash
git add src/ui/diff-documents.ts src/ui/chat-surfaces.ts
git commit -m "feat(ui): route model, mode, MCP, diff, and session-switch messages"
```

---

### Task 7: Session switcher and sign-in banner in the webview

**Files:**
- Create: `webview/app/components/session-switcher.tsx`, `webview/app/components/sign-in-banner.tsx`
- Modify: `webview/app/components/chat-header.tsx`, `webview/app/App.tsx`, `webview/preview/scenario.ts`

- [ ] **Step 1: Session switcher**

`webview/app/components/session-switcher.tsx`:

```tsx
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import { relativeTime } from '../../../src/ui/time'
import { send } from '../host'
import type { ChatState } from '../state'
import { Codicon } from './codicon'
import { ProviderAvatar } from './provider-avatar'

export function SessionSwitcher({ state }: { state: ChatState }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="icon-sm" variant="ghost" aria-label="Switch session">
          <Codicon name="history" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuItem onSelect={() => send({ type: 'newChat' })}>
          <Codicon name="add" />
          New chat
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-xs text-muted-foreground">Recent</DropdownMenuLabel>
        {state.sessions.map((session) => (
          <DropdownMenuItem key={session.id} onSelect={() => send({ type: 'switchSession', sessionId: session.id })}>
            <ProviderAvatar providerId={session.providerId} className="size-5 text-[10px]" />
            <span className="min-w-0 flex-1 truncate">{session.title}</span>
            <span className="text-xs text-muted-foreground">{relativeTime(session.updatedAt)}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
```

- [ ] **Step 2: Show it in the sidebar header**

In `webview/app/components/chat-header.tsx`, add `import { SessionSwitcher } from './session-switcher'` and, right after `<StatusBadge status={state.status} />`, add:

```tsx
      {document.body.dataset.surface === 'view' && <SessionSwitcher state={state} />}
```

- [ ] **Step 3: Sign-in banner**

`webview/app/components/sign-in-banner.tsx`:

```tsx
import { Button } from '@/components/ui/button'
import type { ProviderInfo } from '../../../src/ui/protocol'
import { send } from '../host'
import { Codicon } from './codicon'

export function SignInBanner({ provider }: { provider?: ProviderInfo }) {
  const status = provider?.state.status
  if (!provider || (status !== 'signed-out' && status !== 'not-installed')) return null
  return (
    <div className="flex items-center gap-2 rounded-md border border-warning/50 bg-warning/5 px-3 py-2 text-sm">
      <Codicon name="warning" className="text-warning" />
      {status === 'signed-out' ? (
        <>
          <span className="flex-1">You are signed out of {provider.label}.</span>
          <Button size="xs" onClick={() => send({ type: 'signIn' })}>
            Sign in
          </Button>
        </>
      ) : (
        <span className="flex-1">
          The {provider.label} CLI is not installed. <a href={provider.installUrl}>Install it</a>, then reload.
        </span>
      )}
    </div>
  )
}
```

In `webview/app/App.tsx`, add `import { SignInBanner } from './components/sign-in-banner'` and render `<SignInBanner provider={state.provider} />` as the first child of the bottom `<div className="space-y-2 px-3 pb-3">`.

- [ ] **Step 4: Preview the sidebar**

In `webview/preview/scenario.ts`, add a `sessions` message as the first entry of `messages`:

```ts
  {
    type: 'sessions',
    sessions: [
      { id: 's1', title: 'Fix flaky retry test', providerId: 'claude', status: 'needs-input', updatedAt: '2026-10-28T10:04:00.000Z' },
      { id: 's2', title: 'Refactor auth middleware', providerId: 'claude', status: 'idle', updatedAt: '2026-10-28T09:00:00.000Z' }
    ]
  },
```

and in `webview/preview/index.html` change the body-class script line to also set the surface from the URL:

```html
<script>document.body.classList.add(window.previewTheme === 'light' ? 'vscode-light' : 'vscode-dark'); document.body.dataset.surface = new URLSearchParams(location.search).get('surface') ?? 'panel'</script>
```

In `scripts/screenshot.mjs`, accept a third argument for the surface: change the first line of argument parsing to

```js
const [theme = 'dark', size = '900x1200', surface = 'panel'] = process.argv.slice(2)
```

the output path to ``resolve(`dist/preview/screenshot-${theme}-${surface}.png`)``, and the URL to ```file://${resolve('dist/preview/index.html')}?theme=${theme}&surface=${surface}` ``.

- [ ] **Step 5: Build and review screenshots**

Run:

```bash
pnpm typecheck; pnpm test && pnpm build:preview && pnpm screenshot dark 900x1200 panel && pnpm screenshot dark 420x1000 view
```

Expected: `pnpm typecheck` still reports only the `src/extension.ts` constructor error from Task 6. The `view` screenshot (narrow, sidebar background) shows the history button in the header; the `panel` one does not.

- [ ] **Step 6: Commit**

```bash
git add webview scripts/screenshot.mjs
git commit -m "feat(webview): add the sidebar session switcher and a sign-in banner"
```

---

### Task 8: Sessions tree, status bar, and registration

**Files:**
- Create: `src/ui/sessions-tree.ts`, `src/ui/status-bar.ts`
- Modify: `src/extension.ts`, `package.json`

- [ ] **Step 1: Sessions tree**

`src/ui/sessions-tree.ts`:

```ts
import * as vscode from 'vscode'
import type { SessionManager } from '../sessions/manager'
import type { SessionStatus } from '../sessions/store'
import { relativeTime } from './time'

export type SessionNode = { id: string; title: string; status: SessionStatus; updatedAt: string; provider: string }

const ICONS: Record<SessionStatus, vscode.ThemeIcon> = {
  idle: new vscode.ThemeIcon('comment'),
  running: new vscode.ThemeIcon('loading~spin'),
  'needs-input': new vscode.ThemeIcon('bell-dot', new vscode.ThemeColor('editorWarning.foreground')),
  error: new vscode.ThemeIcon('error', new vscode.ThemeColor('errorForeground')),
  stopped: new vscode.ThemeIcon('debug-stop')
}

export class SessionsTree implements vscode.TreeDataProvider<SessionNode>, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<void>()
  readonly onDidChangeTreeData = this.changed.event
  private readonly view: vscode.TreeView<SessionNode>
  private readonly subscription: { dispose(): void }

  constructor(
    private readonly manager: SessionManager,
    private readonly labels: ReadonlyMap<string, string>
  ) {
    this.view = vscode.window.createTreeView('agentdeck.sessions', { treeDataProvider: this })
    this.subscription = manager.onDidChange(() => this.refresh())
    this.refresh()
  }

  getChildren(): SessionNode[] {
    return this.manager.list().map(({ record, status }) => ({
      id: record.id,
      title: record.title,
      status,
      updatedAt: record.updatedAt,
      provider: this.labels.get(record.providerId) ?? record.providerId
    }))
  }

  getTreeItem(node: SessionNode): vscode.TreeItem {
    const item = new vscode.TreeItem(node.title)
    item.id = node.id
    item.description = relativeTime(node.updatedAt)
    item.tooltip = `${node.provider} · ${node.status}`
    item.iconPath = ICONS[node.status]
    item.contextValue = 'session'
    item.command = { command: 'agentdeck.openSession', title: 'Open', arguments: [node] }
    return item
  }

  dispose(): void {
    this.subscription.dispose()
    this.view.dispose()
    this.changed.dispose()
  }

  private refresh(): void {
    this.changed.fire()
    const waiting = this.manager.list().filter(({ status }) => status === 'needs-input').length
    this.view.badge = waiting > 0 ? { value: waiting, tooltip: `${waiting} waiting for input` } : undefined
  }
}
```

- [ ] **Step 2: Status bar**

`src/ui/status-bar.ts`:

```ts
import * as vscode from 'vscode'
import type { SessionManager } from '../sessions/manager'

/** Running and waiting counts; hidden when nothing is active. */
export class SessionsStatusBar implements vscode.Disposable {
  private readonly item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50)
  private readonly subscription: { dispose(): void }

  constructor(private readonly manager: SessionManager) {
    this.item.command = 'agentdeck.sessions.focus'
    this.subscription = manager.onDidChange(() => this.update())
    this.update()
  }

  dispose(): void {
    this.subscription.dispose()
    this.item.dispose()
  }

  private update(): void {
    const sessions = this.manager.list()
    const running = sessions.filter(({ status }) => status === 'running').length
    const waiting = sessions.filter(({ status }) => status === 'needs-input').length
    if (running === 0 && waiting === 0) return this.item.hide()
    const parts = [running > 0 && `$(loading~spin) ${running} running`, waiting > 0 && `$(bell-dot) ${waiting} needs input`]
    this.item.text = parts.filter(Boolean).join('  ')
    this.item.tooltip = 'AgentDeck sessions'
    this.item.show()
  }
}
```

- [ ] **Step 3: Register everything**

In `src/extension.ts`:
- add imports:

```ts
import { DIFF_SCHEME, DiffDocuments } from './ui/diff-documents'
import { type SessionNode, SessionsTree } from './ui/sessions-tree'
import { SessionsStatusBar } from './ui/status-bar'
```

- right after the `manager = new SessionManager({...})` statement, add (the module-level `manager` is a `let`, which TypeScript does not narrow inside the command callbacks below):

```ts
  const sessionManager = manager
```

- replace the line constructing `surfaces` with:

```ts
  const diffs = new DiffDocuments(manager)
  const surfaces = new ChatSurfaces(context, manager, providers, getEnv, editor, diffs)
```

- add to `context.subscriptions.push(...)`:

```ts
    vscode.workspace.registerTextDocumentContentProvider(DIFF_SCHEME, diffs),
    new SessionsTree(sessionManager, new Map([...providers].map(([id, provider]) => [id, provider.label]))),
    new SessionsStatusBar(sessionManager),
    vscode.commands.registerCommand('agentdeck.openSession', (node: SessionNode) => surfaces.openPanel(node.id)),
    vscode.commands.registerCommand('agentdeck.openSessionInSidebar', (node: SessionNode) => surfaces.showInSidebar(node.id)),
    vscode.commands.registerCommand('agentdeck.renameSession', async (node: SessionNode) => {
      const title = await vscode.window.showInputBox({ prompt: 'Session name', value: node.title })
      if (title?.trim()) await sessionManager.rename(node.id, title.trim())
    }),
    vscode.commands.registerCommand('agentdeck.stopSession', (node: SessionNode) => sessionManager.stop(node.id)),
    vscode.commands.registerCommand('agentdeck.deleteSession', async (node: SessionNode) => {
      const choice = await vscode.window.showWarningMessage(`Delete “${node.title}”?`, { modal: true }, 'Delete')
      if (choice === 'Delete') await sessionManager.delete(node.id)
    })
```

- [ ] **Step 4: Contributions**

In `package.json` `contributes`:
- add to `views.agentdeck`, after the chat view:

```json
        { "id": "agentdeck.sessions", "name": "Sessions" }
```

- add to `commands`:

```json
      { "command": "agentdeck.openSession", "title": "Open in Editor", "category": "AgentDeck" },
      { "command": "agentdeck.openSessionInSidebar", "title": "Open in Sidebar", "category": "AgentDeck" },
      { "command": "agentdeck.renameSession", "title": "Rename…", "category": "AgentDeck" },
      { "command": "agentdeck.stopSession", "title": "Stop", "category": "AgentDeck" },
      { "command": "agentdeck.deleteSession", "title": "Delete…", "category": "AgentDeck" }
```

- add to `menus`:

```json
      "view/item/context": [
        { "command": "agentdeck.openSession", "when": "view == agentdeck.sessions && viewItem == session", "group": "1_open@1" },
        { "command": "agentdeck.openSessionInSidebar", "when": "view == agentdeck.sessions && viewItem == session", "group": "1_open@2" },
        { "command": "agentdeck.renameSession", "when": "view == agentdeck.sessions && viewItem == session", "group": "2_edit@1" },
        { "command": "agentdeck.stopSession", "when": "view == agentdeck.sessions && viewItem == session", "group": "2_edit@2" },
        { "command": "agentdeck.deleteSession", "when": "view == agentdeck.sessions && viewItem == session", "group": "3_delete@1" }
      ],
      "commandPalette": [
        { "command": "agentdeck.openSession", "when": "false" },
        { "command": "agentdeck.openSessionInSidebar", "when": "false" },
        { "command": "agentdeck.renameSession", "when": "false" },
        { "command": "agentdeck.stopSession", "when": "false" },
        { "command": "agentdeck.deleteSession", "when": "false" }
      ]
```

- [ ] **Step 5: Verify**

Run: `pnpm typecheck && pnpm test && pnpm build && pnpm run package && node dist/smoke.js`
Expected: clean, passing, packaged, `SMOKE OK`.

- [ ] **Step 6: Commit**

```bash
git add src package.json
git commit -m "feat(ui): add the sessions tree, status bar, and session commands"
```

- [ ] **Step 7: Hand off for the manual check**

Stop and ask the user to check, after `code --install-extension agentdeck-0.0.1.vsix --force` and a reload:
1. The AgentDeck view shows *Chat* and *Sessions*; sessions list newest first with status icons; the context menu opens, renames, stops, and deletes.
2. In a chat: tool cards expand; a diff card's *Open diff* opens VS Code's diff editor; the plan card tracks progress.
3. The model and mode menus change the session (the next reply uses the new model; *Plan* mode stops edits).
4. The MCP popover lists the same servers as `claude mcp list`, settles from *Connecting…* to real states, *Sign in* on a claude.ai connector opens the connector settings, and *Reconnect* updates the row.
5. The sidebar's history button switches sessions and starts a new one.
6. The status bar shows running and waiting counts while a turn runs or waits.

---

## Done when

- `pnpm typecheck`, `pnpm test`, and `node dist/smoke.js` pass.
- Preview screenshots (dark and light, panel and view) match Tasks 4, 5, and 7.
- The user has run the manual check in Task 8 Step 7.
