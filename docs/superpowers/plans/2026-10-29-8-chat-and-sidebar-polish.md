# Plan 8: Chat and sidebar details from the mockups — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first. Plans 1–7 are complete.

**Goal:** Close the gaps between the chat and the mockups (`docs/design/mockups/2-chat-tab.html`, `4-side-by-side.html`, `5-sidebar-chat.html`): quota pill with a hover card, a searchable session switcher in the sidebar header, an elapsed-time working line, a "Queue a follow-up…" placeholder, a plan progress bar, a per-turn "Edited N files · Review changes" rollup, a reply footer (model, time, copy, retry), and a toast when a chat you are not looking at needs approval.

**Architecture:** Quota is account state, not transcript: providers parse their CLI's own usage reports into a `Quota` and emit it through an optional `ProviderSession.onQuota`; the manager relays it with the provider id; `ChatSurfaces` keeps the latest per provider in `globalState` (so it survives reloads, shown with its age) and sends it to every chat. Turn footers are derived in the webview from the transcript (a pure function, unit-tested); the manager stamps the end time on `turn` items. Review changes opens VS Code's multi-diff editor (`vscode.changes`) over the existing diff documents.

**Tech Stack:** as before; shadcn `hover-card` and `command` (cmdk) added through the shadcn CLI.

**Verified before writing** (2026-10-29):
- Claude 2.1.311 `rate_limit_event.rate_limit_info`: `{ status, resetsAt, rateLimitType: 'five_hour', unifiedWindows: { five_hour: { utilization: 0.32, resetsAt: 1793241600, status: 'allowed' }, seven_day: { utilization: 0.18, resetsAt: 1793743200, status: 'allowed' } } }` (`utilization` 0–1, `resetsAt` epoch seconds). Older CLIs send one window (`rateLimitType`, `utilization`) per event.
- Codex `account/rateLimits/updated`: `{ rateLimits: { primary: { usedPercent: 0, windowDurationMins: 43200, resetsAt: 1795747162 }, secondary: null } }` (`usedPercent` 0–100).
- Grok reports no quota over ACP; its chats show no pill.

---

## File structure

| File | Responsibility |
|---|---|
| `src/core/types.ts` | `Quota`; `ProviderSession.onQuota`; `TurnItem.at` |
| `src/providers/claude/quota.ts`, `src/providers/codex/quota.ts` | Parse each CLI's usage report |
| `src/providers/claude/provider.ts`, `src/providers/codex/provider.ts` | Emit quota |
| `src/sessions/manager.ts` | Relay quota; stamp turn end time |
| `src/ui/protocol.ts`, `webview/app/state.ts` | `quota` message and state; `inTab` on summaries; `reviewChanges`, `openSession` |
| `src/ui/chat-surfaces.ts`, `src/ui/diff-documents.ts` | Keep quota; attention toast; review changes; open session in tab |
| `webview/app/format.ts`, `webview/app/use-now.ts`, `webview/app/turns.ts` | Small helpers; turn footers |
| `webview/app/components/{quota-pill,session-switcher,chat-header,working-status,composer,model-picker}.tsx`, `webview/app/items/{plan-card,turn-footer}.tsx`, `webview/app/App.tsx` | UI |
| `webview/preview/scenario.ts` | A finished earlier turn and a quota report |

---

### Task 1: Quota from the CLIs

**Files:**
- Modify: `src/core/types.ts`
- Create: `src/providers/claude/quota.ts`, `src/providers/codex/quota.ts`
- Test: `test/providers/quota.test.ts`

- [ ] **Step 1: Types**

In `src/core/types.ts`, add before `export type ProviderState`:

```ts
/** An account's usage limits as its CLI last reported them; shown with their age. */
export type Quota = {
  observedAt: string
  windows: { label: string; usedPercent: number; resetsAt?: string; status: 'ok' | 'warning' | 'limited' }[]
}
```

and in `ProviderSession`, after `readonly onExit`, add:

```ts
  /** Usage limits, for providers whose CLI reports them. */
  readonly onQuota?: Event<Quota>
```

- [ ] **Step 2: Write the failing tests**

`test/providers/quota.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { claudeQuota } from '../../src/providers/claude/quota'
import { codexQuota } from '../../src/providers/codex/quota'

const now = new Date('2026-10-29T10:00:00.000Z')

describe('claudeQuota', () => {
  it('reads every unified window', () => {
    const quota = claudeQuota(
      {
        status: 'allowed',
        rateLimitType: 'five_hour',
        unifiedWindows: {
          five_hour: { utilization: 0.32, resetsAt: 1793241600, status: 'allowed' },
          seven_day: { utilization: 0.18, resetsAt: 1793743200, status: 'allowed_warning' }
        }
      },
      now
    )
    expect(quota).toEqual({
      observedAt: '2026-10-29T10:00:00.000Z',
      windows: [
        { label: '5-hour', usedPercent: 32, resetsAt: new Date(1793241600 * 1000).toISOString(), status: 'ok' },
        { label: 'Weekly', usedPercent: 18, resetsAt: new Date(1793743200 * 1000).toISOString(), status: 'warning' }
      ]
    })
  })

  it('falls back to the single window older CLIs report', () => {
    expect(claudeQuota({ status: 'rejected', rateLimitType: 'seven_day_opus', utilization: 1 }, now)?.windows).toEqual([
      { label: 'Weekly (Opus)', usedPercent: 100, status: 'limited' }
    ])
  })

  it('returns null without utilization', () => {
    expect(claudeQuota({ status: 'allowed' }, now)).toBeNull()
  })
})

describe('codexQuota', () => {
  it('labels windows by their length', () => {
    const quota = codexQuota(
      {
        primary: { usedPercent: 85, windowDurationMins: 300, resetsAt: 1795747162 },
        secondary: { usedPercent: 12, windowDurationMins: 10080, resetsAt: null }
      },
      now
    )
    expect(quota?.windows).toEqual([
      { label: '5-hour', usedPercent: 85, resetsAt: new Date(1795747162 * 1000).toISOString(), status: 'warning' },
      { label: 'Weekly', usedPercent: 12, status: 'ok' }
    ])
  })

  it('names a monthly window and marks a full one as limited', () => {
    expect(codexQuota({ primary: { usedPercent: 100, windowDurationMins: 43200 }, secondary: null }, now)?.windows).toEqual([
      { label: 'Monthly', usedPercent: 100, status: 'limited' }
    ])
  })
})
```

Run: `pnpm test test/providers/quota.test.ts` → FAIL (cannot resolve the modules).

- [ ] **Step 3: Implement**

`src/providers/claude/quota.ts`:

```ts
import type { Quota } from '../../core/types'

type Window = { utilization?: number; resetsAt?: number; status?: string }

/** The parts of `rate_limit_event.rate_limit_info` AgentDeck reads; `unifiedWindows` is newer than the SDK's types. */
export type RateLimitInfo = Window & { rateLimitType?: string; unifiedWindows?: Record<string, Window> }

const LABELS: Record<string, string> = {
  five_hour: '5-hour',
  seven_day: 'Weekly',
  seven_day_opus: 'Weekly (Opus)',
  seven_day_sonnet: 'Weekly (Sonnet)'
}

const STATUS: Record<string, Quota['windows'][number]['status']> = {
  allowed: 'ok',
  allowed_warning: 'warning',
  rejected: 'limited'
}

export function claudeQuota(info: RateLimitInfo, now = new Date()): Quota | null {
  const windows = info.unifiedWindows ?? (info.rateLimitType ? { [info.rateLimitType]: info } : {})
  const parsed = Object.entries(windows).flatMap(([type, window]) =>
    window.utilization === undefined
      ? []
      : [
          {
            label: LABELS[type] ?? type.replaceAll('_', ' '),
            usedPercent: Math.round(window.utilization * 100),
            ...(window.resetsAt ? { resetsAt: new Date(window.resetsAt * 1000).toISOString() } : {}),
            status: STATUS[window.status ?? ''] ?? 'ok'
          }
        ]
  )
  return parsed.length > 0 ? { observedAt: now.toISOString(), windows: parsed } : null
}
```

`src/providers/codex/quota.ts`:

```ts
import type { Quota } from '../../core/types'

type Window = { usedPercent: number; windowDurationMins?: number | null; resetsAt?: number | null } | null | undefined

export function codexQuota(rateLimits: { primary?: Window; secondary?: Window }, now = new Date()): Quota | null {
  const windows = [rateLimits.primary, rateLimits.secondary].flatMap((window) =>
    window
      ? [
          {
            label: windowLabel(window.windowDurationMins),
            usedPercent: Math.round(window.usedPercent),
            ...(window.resetsAt ? { resetsAt: new Date(window.resetsAt * 1000).toISOString() } : {}),
            status: status(window.usedPercent)
          }
        ]
      : []
  )
  return windows.length > 0 ? { observedAt: now.toISOString(), windows } : null
}

function status(usedPercent: number): Quota['windows'][number]['status'] {
  return usedPercent >= 100 ? 'limited' : usedPercent >= 80 ? 'warning' : 'ok'
}

function windowLabel(minutes: number | null | undefined): string {
  if (!minutes) return 'Usage'
  if (minutes === 300) return '5-hour'
  if (minutes === 10080) return 'Weekly'
  if (minutes >= 40320 && minutes <= 44640) return 'Monthly'
  return minutes % 1440 === 0 ? `${minutes / 1440}-day` : `${Math.round(minutes / 60)}-hour`
}
```

Run: `pnpm test && pnpm typecheck` → PASS; clean.

- [ ] **Step 4: Emit from the providers**

In `src/providers/claude/provider.ts`:
- add `Quota` to the type import from `../../core/types` and `import { claudeQuota, type RateLimitInfo } from './quota'`;
- add after `readonly onExit = this.exits.event`:

```ts
  private readonly quotas = new Emitter<Quota>()
  readonly onQuota = this.quotas.event
```

- in `pump`, after the `if (message.type === 'result') …` line, add:

```ts
        if (message.type === 'rate_limit_event') {
          const quota = claudeQuota(message.rate_limit_info as RateLimitInfo)
          if (quota) this.quotas.fire(quota)
        }
```

In `src/providers/codex/provider.ts`:
- add `Quota` to the type import and `import { codexQuota } from './quota'`;
- add the same two `quotas`/`onQuota` lines after `readonly onExit = this.exits.event`;
- in `notification`'s `switch`, add before `case 'mcpServer/startupStatus/updated'`:

```ts
      case 'account/rateLimits/updated': {
        const quota = codexQuota((params as { rateLimits: Parameters<typeof codexQuota>[0] }).rateLimits)
        if (quota) this.quotas.fire(quota)
        return
      }
```

Run: `pnpm typecheck && pnpm test` → clean; PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/types.ts src/providers test/providers/quota.test.ts
git commit -m "feat: read quota from Claude and Codex usage reports"
```

---

### Task 2: Relay quota and stamp turn end times

**Files:**
- Modify: `src/core/types.ts` (`TurnItem`), `src/sessions/manager.ts`, `test/fake-provider.ts`
- Test: `test/sessions/manager.test.ts` (two tests added)

- [ ] **Step 1: Write the failing tests**

In `test/fake-provider.ts`, import `Quota` from `../src/core/types` and add to `FakeSession` (after the `onExit` line):

```ts
  private readonly quotas = new Emitter<Quota>()
  readonly onQuota = this.quotas.event
```

and a method:

```ts
  quota(quota: Quota): void {
    this.quotas.fire(quota)
  }
```

In `test/sessions/manager.test.ts`, add inside the `describe` block:

```ts
  it('relays quota with the provider id', async () => {
    const { manager, sessions } = setup()
    const seen: unknown[] = []
    manager.onQuota((event) => seen.push(event))
    const { id } = await manager.create('fake')
    await manager.warm(id)
    const quota = { observedAt: 't', windows: [{ label: '5-hour', usedPercent: 40, status: 'ok' as const }] }
    sessions[0].quota(quota)
    expect(seen).toEqual([{ providerId: 'fake', quota }])
  })

  it('stamps when a turn ended', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.prompt(id, text('go'))
    sessions[0].endTurn()
    const ended = events.find((event) => event.type === 'item' && event.item.kind === 'turn')
    expect(ended).toMatchObject({ item: { state: 'ended', at: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T/) } })
  })
```

Run: `pnpm test test/sessions/manager.test.ts` → FAIL (`manager.onQuota` is not a function).

- [ ] **Step 2: `TurnItem.at`**

In `src/core/types.ts`, change the `TurnItem` line to:

```ts
export type TurnItem = {
  kind: 'turn'
  id: string
  state: 'started' | 'ended'
  stopReason?: string
  durationMs?: number
  /** When the turn ended (ISO), stamped by the session manager. */
  at?: string
}
```

- [ ] **Step 3: Manager**

In `src/sessions/manager.ts`:
- add `Quota` to the type import from `../core/types`;
- add after the `Attention` type:

```ts
export type QuotaReport = { providerId: string; quota: Quota }
```

- add after `private readonly attention = new Emitter<Attention>()`:

```ts
  private readonly quotas = new Emitter<QuotaReport>()
```

and after `readonly onAttention = this.attention.event`:

```ts
  /** Fires when a provider's CLI reports its account's usage limits. */
  readonly onQuota = this.quotas.event
```

- in `open`, change the `live.listeners = [...]` array to end with:

```ts
      session.onExit(({ error }) => this.exited(live, session, error)),
      ...(session.onQuota
        ? [session.onQuota((quota) => this.quotas.fire({ providerId: live.record.providerId, quota }))]
        : [])
    ]
```

- at the start of `upsert`, stamp ended turns:

```ts
  private upsert(live: Live, item: SessionItem): void {
    if (item.kind === 'turn' && item.state === 'ended' && !item.at) item = { ...item, at: new Date().toISOString() }
```

(the rest of `upsert` is unchanged).

Run: `pnpm test && pnpm typecheck` → PASS; clean.

- [ ] **Step 4: Commit**

```bash
git add src/core/types.ts src/sessions/manager.ts test/fake-provider.ts test/sessions/manager.test.ts
git commit -m "feat(sessions): relay quota reports and stamp turn end times"
```

---

### Task 3: Webview helpers and turn footers

**Files:**
- Modify: `webview/app/format.ts`
- Create: `webview/app/use-now.ts`, `webview/app/turns.ts`
- Test: `test/webview/format.test.ts`, `test/webview/turns.test.ts`

- [ ] **Step 1: Write the failing tests**

`test/webview/format.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { elapsed, quotaAge, shortWindow } from '../../webview/app/format'

describe('format', () => {
  it('formats elapsed time', () => {
    expect(elapsed(12_000)).toBe('12s')
    expect(elapsed(72_000)).toBe('1m 12s')
    expect(elapsed(3_780_000)).toBe('1h 3m')
  })

  it('shortens window labels', () => {
    expect(shortWindow('5-hour')).toBe('5h')
    expect(shortWindow('Weekly')).toBe('wk')
    expect(shortWindow('Monthly')).toBe('mo')
    expect(shortWindow('Weekly (Opus)')).toBe('Weekly (Opus)')
  })

  it('says how old a quota reading is', () => {
    const now = Date.parse('2026-10-29T10:00:00.000Z')
    expect(quotaAge('2026-10-29T09:59:50.000Z', now)).toBe('just now')
    expect(quotaAge('2026-10-29T09:57:00.000Z', now)).toBe('3m ago')
  })
})
```

`test/webview/turns.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import { turnFooters } from '../../webview/app/turns'

const user = (id: string): SessionItem => ({ kind: 'message', id, role: 'user', parts: [{ type: 'text', text: id }] })
const reply = (id: string, text: string): SessionItem => ({ kind: 'message', id, role: 'assistant', text, streaming: false })

describe('turnFooters', () => {
  it('puts a footer after the last item of each ended turn', () => {
    const items: SessionItem[] = [
      user('u1'),
      { kind: 'turn', id: 't1', state: 'ended', at: '2026-10-29T10:00:00.000Z' },
      reply('a1', 'first'),
      { kind: 'diff', id: 'd1', path: '/w/a.ts', oldText: 'x\ny', newText: 'x\ny\nz' },
      { kind: 'diff', id: 'd2', path: '/w/a.ts', oldText: null, newText: 'one' },
      reply('a2', 'done'),
      user('u2'),
      { kind: 'turn', id: 't2', state: 'started' },
      reply('a3', 'working')
    ]
    const footers = turnFooters(items)
    expect([...footers.keys()]).toEqual(['a2'])
    expect(footers.get('a2')).toMatchObject({
      at: '2026-10-29T10:00:00.000Z',
      prompt: { id: 'u1' },
      reply: { id: 'a2', text: 'done' },
      files: 1,
      added: 4,
      removed: 2
    })
    expect(footers.get('a2')?.diffs.map((diff) => diff.id)).toEqual(['d1', 'd2'])
  })

  it('gives no footer to a turn without a turn item', () => {
    expect(turnFooters([user('u1'), reply('a1', 'x')]).size).toBe(0)
  })
})
```

Run: `pnpm test test/webview` → FAIL.

- [ ] **Step 2: Implement**

Append to `webview/app/format.ts`:

```ts
export function elapsed(ms: number): string {
  const seconds = Math.floor(ms / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

const SHORT_WINDOWS: Record<string, string> = { '5-hour': '5h', Weekly: 'wk', Monthly: 'mo' }

export function shortWindow(label: string): string {
  return SHORT_WINDOWS[label] ?? label
}

export function quotaAge(observedAt: string, now: number): string {
  const minutes = Math.floor((now - Date.parse(observedAt)) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  return hours < 24 ? `${hours}h ago` : `${Math.floor(hours / 24)}d ago`
}

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

/** "at 3:10 PM" today, else "Monday at 3:10 PM". */
export function resetTime(iso: string, now: number): string {
  const date = new Date(iso)
  const time = clockTime(iso)
  return date.toDateString() === new Date(now).toDateString()
    ? `at ${time}`
    : `${date.toLocaleDateString([], { weekday: 'long' })} at ${time}`
}
```

`webview/app/use-now.ts`:

```ts
import { useEffect, useState } from 'react'

/** The current time, refreshed on an interval, for labels like "3m ago". */
export function useNow(intervalMs: number): number {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs])
  return now
}
```

`webview/app/turns.ts`:

```ts
import type { AssistantMessage, DiffItem, SessionItem, TurnItem, UserMessage } from '../../src/core/types'

export type TurnFooter = {
  at?: string
  prompt?: UserMessage
  reply?: AssistantMessage
  diffs: DiffItem[]
  files: number
  added: number
  removed: number
}

const lines = (text: string | null) => (text ? text.split('\n').length : 0)

/** Splits the transcript at user messages; each ended turn gets a footer keyed by its last item's id. */
export function turnFooters(items: SessionItem[]): Map<string, TurnFooter> {
  const footers = new Map<string, TurnFooter>()
  let segment: SessionItem[] = []
  const close = () => {
    const turn = segment.find((item): item is TurnItem => item.kind === 'turn')
    const last = segment.at(-1)
    if (turn?.state === 'ended' && last) {
      const diffs = segment.filter((item): item is DiffItem => item.kind === 'diff')
      footers.set(last.id, {
        at: turn.at,
        prompt: segment.find((item): item is UserMessage => item.kind === 'message' && item.role === 'user'),
        reply: segment.findLast((item): item is AssistantMessage => item.kind === 'message' && item.role === 'assistant'),
        diffs,
        files: new Set(diffs.map((diff) => diff.path)).size,
        added: diffs.reduce((sum, diff) => sum + lines(diff.newText), 0),
        removed: diffs.reduce((sum, diff) => sum + lines(diff.oldText), 0)
      })
    }
    segment = []
  }
  for (const item of items) {
    if (item.kind === 'message' && item.role === 'user') close()
    segment.push(item)
  }
  close()
  return footers
}
```

If `tsc` reports `findLast` missing, add `"ES2023"` to `lib` in both `tsconfig.json` and `webview/tsconfig.json` (Chrome 120 and Node 20 both support it).

Run: `pnpm test && pnpm typecheck` → PASS; clean.

- [ ] **Step 3: Commit**

```bash
git add webview/app/format.ts webview/app/use-now.ts webview/app/turns.ts test/webview tsconfig.json webview/tsconfig.json
git commit -m "feat(webview): add turn footers and time helpers"
```

---

### Task 4: Protocol, state, and host

**Files:**
- Modify: `src/ui/protocol.ts`, `webview/app/state.ts`, `src/ui/chat-surfaces.ts`, `src/ui/diff-documents.ts`
- Test: `test/webview/state.test.ts` (one test added)

- [ ] **Step 1: Write the failing test**

In `test/webview/state.test.ts`, add:

```ts
  it('keeps the latest quota per provider, also across an empty surface', () => {
    const quota = { observedAt: 't', windows: [{ label: '5-hour', usedPercent: 40, status: 'ok' as const }] }
    const state = run({ type: 'quota', providerId: 'claude', quota }, { type: 'empty' })
    expect(state.quotas).toEqual({ claude: quota })
  })
```

Run: `pnpm test test/webview/state.test.ts` → FAIL.

- [ ] **Step 2: Protocol and state**

In `src/ui/protocol.ts`:
- import `Quota` with the other core types;
- add `inTab: boolean` to `SessionSummary`;
- add to `HostMessage`: `| { type: 'quota'; providerId: string; quota: Quota }`;
- add to `WebviewMessage`: `| { type: 'reviewChanges'; itemIds: string[] }` and `| { type: 'openSession'; sessionId: string }`.

In `webview/app/state.ts`:
- import `Quota` from `../../src/core/types`;
- add `quotas: Record<string, Quota>` to `ChatState` and `quotas: {}` to `initialState`;
- add a case before `case 'session':`:

```ts
    case 'quota':
      return { ...state, quotas: { ...state.quotas, [message.providerId]: message.quota } }
```

- keep `quotas: state.quotas` in the `'empty'` case.

In `test/webview/state.test.ts`, the existing *keeps the session list for the switcher* test builds a summary without `inTab`; add `inTab: false` to that object.

Run: `pnpm test` → PASS.

- [ ] **Step 3: Review changes in the multi-diff editor**

In `src/ui/diff-documents.ts`, replace the `open` method with:

```ts
  async open(sessionId: string, itemId: string): Promise<void> {
    const item = this.manager.item(sessionId, itemId)
    if (item?.kind !== 'diff') return
    const name = basename(item.path)
    await vscode.commands.executeCommand('vscode.diff', this.uri(sessionId, itemId, name, 'before'), this.uri(sessionId, itemId, name, 'after'), `${name} (agent change)`)
  }

  /** Several diffs at once, in VS Code's multi-diff editor. */
  async openAll(sessionId: string, itemIds: string[]): Promise<void> {
    if (itemIds.length === 1) return this.open(sessionId, itemIds[0])
    const resources = itemIds.flatMap((itemId) => {
      const item = this.manager.item(sessionId, itemId)
      if (item?.kind !== 'diff') return []
      const name = basename(item.path)
      return [[vscode.Uri.file(item.path), this.uri(sessionId, itemId, name, 'before'), this.uri(sessionId, itemId, name, 'after')]]
    })
    await vscode.commands.executeCommand('vscode.changes', 'Agent changes', resources)
  }

  private uri(sessionId: string, itemId: string, name: string, side: Side): vscode.Uri {
    return vscode.Uri.from({ scheme: DIFF_SCHEME, path: `/${name}`, query: JSON.stringify({ sessionId, itemId, side }) })
  }
```

- [ ] **Step 4: Host**

In `src/ui/chat-surfaces.ts`:
- import `Quota` with the core types and `type Attention` from `../sessions/manager`;
- add fields after `private readonly blankPanels …`:

```ts
  private sidebarView: vscode.WebviewView | undefined
  /** Latest usage per provider; kept across reloads and shown with its age. */
  private readonly quotas: Record<string, Quota>
```

- at the start of the constructor body, add `this.quotas = context.globalState.get<Record<string, Quota>>(QUOTA_KEY) ?? {}`, define `const QUOTA_KEY = 'agentdeck.quota'` next to `SIDEBAR_SESSION_KEY`, and add to the constructor's `this.subscriptions.push(...)`:

```ts
      manager.onQuota(({ providerId, quota }) => {
        this.quotas[providerId] = quota
        void this.context.globalState.update(QUOTA_KEY, this.quotas)
        this.broadcast({ type: 'quota', providerId, quota })
      }),
      manager.onAttention((event) => this.attend(event))
```

- in `resolveWebviewView`, add `this.sidebarView = view` after `this.sidebar = surface`, and `this.sidebarView = undefined` inside the `onDidDispose` callback's `if`;
- in `handle`'s `'ready'` case, after `await this.postProviders(surface)`, add:

```ts
        for (const [providerId, quota] of Object.entries(this.quotas)) this.post(surface, { type: 'quota', providerId, quota })
```

- add cases before `case 'openFile'`:

```ts
      case 'reviewChanges':
        if (sessionId) await this.diffs.openAll(sessionId, message.itemIds)
        return
      case 'openSession':
        this.openPanel(message.sessionId)
        return
```

- in `postSessions`, add `inTab: this.panels.has(record.id)` to each summary;
- add this method next to `signIn`:

```ts
  /** A toast when a chat that is not on screen needs approval. */
  private async attend({ sessionId, reason }: Attention): Promise<void> {
    if (reason !== 'needs-input' || this.visible(sessionId)) return
    const record = this.manager.list().find((entry) => entry.record.id === sessionId)?.record
    if (!record) return
    const label = this.providers.get(record.providerId)?.label ?? record.providerId
    const choice = await vscode.window.showInformationMessage(`${label} needs your approval — ${record.title}`, 'Review')
    if (choice !== 'Review') return
    if (this.panels.has(sessionId) || this.sidebar?.sessionId !== sessionId) this.openPanel(sessionId)
    else await vscode.commands.executeCommand(`${SIDEBAR_VIEW}.focus`)
  }

  private visible(sessionId: string): boolean {
    if (this.panels.get(sessionId)?.panel.visible) return true
    return this.sidebar?.sessionId === sessionId && this.sidebarView?.visible === true
  }
```

Run: `pnpm typecheck && pnpm test` → clean; PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ui webview/app/state.ts test/webview/state.test.ts
git commit -m "feat(ui): keep quota per provider, review changes together, and toast approvals off screen"
```

---

### Task 5: Quota pill, switcher, and turn chrome

**Files:**
- Generated: `webview/components/ui/hover-card.tsx`, `webview/components/ui/command.tsx` (and any components they depend on)
- Create: `webview/app/components/quota-pill.tsx`, `webview/app/items/turn-footer.tsx`
- Modify: `webview/app/components/{session-switcher,chat-header,working-status,composer,model-picker}.tsx`, `webview/app/items/plan-card.tsx`, `webview/app/App.tsx`

- [ ] **Step 1: Add the shadcn components**

```bash
yes n | npx -y shadcn@4.23.0 add hover-card command --yes
python3 - <<'PY'
import json
pkg = json.load(open('package.json'))
for section in ('dependencies', 'devDependencies'):
    pkg[section] = {name: version.lstrip('^') for name, version in pkg[section].items()}
json.dump(pkg, open('package.json', 'w'), indent=2)
open('package.json', 'a').write('\n')
PY
pnpm install
```

Expected: `webview/components/ui/hover-card.tsx` and `command.tsx` exist (the CLI may add `dialog.tsx` for `command`); `cmdk` is a pinned dependency; `engines.vscode` is still `^1.95.0`. Run `pnpm typecheck` → clean.

- [ ] **Step 2: Model label helper**

In `webview/app/components/model-picker.tsx`, add and export (above `ModelPicker`), and use it for `selected` inside `ModelPicker`:

```tsx
/** The picker entry for the current model: the CLI reports a concrete id; the picker lists aliases. */
export function selectedModel(fact: Extract<SessionFact, { kind: 'model' }>) {
  return fact.available.find((model) => model.id === fact.current) ?? fact.available.find((model) => model.resolved === fact.current)
}
```

(replace the two-line `const selected = …` in `ModelPicker` with `const selected = selectedModel(fact)`).

- [ ] **Step 3: Quota pill**

`webview/app/components/quota-pill.tsx`:

```tsx
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'
import { cn } from '@/lib/utils'
import type { Quota } from '../../../src/core/types'
import { quotaAge, resetTime, shortWindow } from '../format'
import { useNow } from '../use-now'

const TONE = { ok: 'text-muted-foreground', warning: 'text-warning', limited: 'text-destructive' } as const
const BAR = { ok: 'bg-info', warning: 'bg-warning', limited: 'bg-destructive' } as const

export function QuotaPill({ label, quota, compact = false }: { label: string; quota?: Quota; compact?: boolean }) {
  const now = useNow(30_000)
  if (!quota || quota.windows.length === 0) return null
  const worst = quota.windows.some((window) => window.status === 'limited')
    ? 'limited'
    : quota.windows.some((window) => window.status === 'warning')
      ? 'warning'
      : 'ok'
  const shown = compact ? quota.windows.slice(0, 1) : quota.windows
  return (
    <HoverCard openDelay={150}>
      <HoverCardTrigger asChild>
        <button type="button" className={cn('shrink-0 rounded-md border px-2 py-0.5 text-xs whitespace-nowrap', TONE[worst])}>
          {shown.map((window) => `${shortWindow(window.label)} ${window.usedPercent}%`).join(' · ')}
        </button>
      </HoverCardTrigger>
      <HoverCardContent align="end" className="w-72 space-y-3 p-3 text-xs">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-sm font-semibold">{label} usage</span>
          <span className="text-muted-foreground">as of {quotaAge(quota.observedAt, now)}</span>
        </div>
        {quota.windows.map((window) => (
          <div key={window.label} className="space-y-1">
            <div className="flex justify-between">
              <span>{window.label}</span>
              <span className="font-medium">{window.usedPercent}%</span>
            </div>
            <div className="h-1 overflow-hidden rounded-full bg-muted">
              <div className={cn('h-full rounded-full', BAR[window.status])} style={{ width: `${Math.min(window.usedPercent, 100)}%` }} />
            </div>
            {window.resetsAt && <div className="text-muted-foreground">Resets {resetTime(window.resetsAt, now)}</div>}
          </div>
        ))}
        <p className="border-t pt-2 text-muted-foreground">Reported by the {label} CLI while a session runs.</p>
      </HoverCardContent>
    </HoverCard>
  )
}
```

- [ ] **Step 4: Session switcher as a searchable menu**

`webview/app/components/session-switcher.tsx` (full replacement):

```tsx
import { useState } from 'react'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import type { SessionStatus } from '../../../src/sessions/store'
import type { WebviewMessage } from '../../../src/ui/protocol'
import { relativeTime } from '../../../src/ui/time'
import { shortWindow } from '../format'
import { send } from '../host'
import type { ChatState } from '../state'
import { Codicon } from './codicon'
import { ProviderAvatar } from './provider-avatar'

function StatusDot({ status }: { status: SessionStatus }) {
  if (status === 'running') return <Codicon name="loading" size={12} spin className="text-info" />
  const color = status === 'needs-input' ? 'bg-warning' : status === 'error' ? 'bg-destructive' : 'border border-muted-foreground'
  return <span className={cn('mx-0.5 size-2 shrink-0 rounded-full', color)} />
}

/** The sidebar header: the session title opens a searchable list of new chats and recent sessions. */
export function SessionSwitcher({ state }: { state: ChatState }) {
  const [open, setOpen] = useState(false)
  const [highlighted, setHighlighted] = useState('')
  const choose = (message: WebviewMessage) => {
    setOpen(false)
    send(message)
  }
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button" className="flex min-w-0 flex-1 items-center gap-1 rounded-md px-1 py-0.5 text-left hover:bg-accent">
          <span className="truncate text-sm font-semibold">{state.record?.title ?? 'New chat'}</span>
          <Codicon name="chevron-down" size={12} className="shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-0">
        <Command
          value={highlighted}
          onValueChange={setHighlighted}
          onKeyDown={(event) => {
            if (event.key !== 'Enter' || !(event.metaKey || event.ctrlKey) || !highlighted.startsWith('session:')) return
            event.preventDefault()
            choose({ type: 'openSession', sessionId: highlighted.slice('session:'.length) })
          }}
        >
          <CommandInput placeholder="Search sessions or start a new chat…" />
          <CommandList>
            <CommandEmpty>No matching sessions.</CommandEmpty>
            <CommandGroup heading="New chat">
              {state.providers.map((provider) => {
                const status = provider.state.status
                const quota = state.quotas[provider.id]?.windows[0]
                return (
                  <CommandItem
                    key={provider.id}
                    value={`new:${provider.id}`}
                    keywords={[provider.label, 'new chat']}
                    disabled={status === 'not-installed'}
                    onSelect={() =>
                      choose(status === 'signed-out' ? { type: 'signIn', providerId: provider.id } : { type: 'newChat', providerId: provider.id })
                    }
                  >
                    <ProviderAvatar providerId={provider.id} className="size-5 text-[10px]" />
                    <span className="flex-1">{provider.label}</span>
                    {status === 'signed-out' ? (
                      <span className="text-xs text-warning">Sign in</span>
                    ) : status === 'not-installed' ? (
                      <span className="text-xs text-muted-foreground">Not installed</span>
                    ) : (
                      quota && <span className="text-xs text-muted-foreground">{`${shortWindow(quota.label)} ${quota.usedPercent}%`}</span>
                    )}
                  </CommandItem>
                )
              })}
            </CommandGroup>
            <CommandSeparator />
            <CommandGroup heading="Recent">
              {state.sessions.map((session) => (
                <CommandItem
                  key={session.id}
                  value={`session:${session.id}`}
                  keywords={[session.title]}
                  onSelect={() => choose({ type: 'switchSession', sessionId: session.id })}
                >
                  <StatusDot status={session.status} />
                  <span className="min-w-0 flex-1 truncate">{session.title}</span>
                  {session.inTab && <span className="rounded border px-1 text-[10px] text-muted-foreground">in tab</span>}
                  <span className="text-xs text-muted-foreground">{relativeTime(session.updatedAt)}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
          <div className="flex gap-3 border-t px-3 py-1.5 text-[11px] text-muted-foreground">
            <span>↑↓ navigate</span>
            <span>↵ open</span>
            <span>⌘↵ open in tab</span>
          </div>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
```

If `CommandItem` rejects the `keywords` prop, check the installed `cmdk` version (`keywords` needs cmdk 1.0+) and report it.

- [ ] **Step 5: Header**

`webview/app/components/chat-header.tsx` (full replacement):

```tsx
import type { ChatState } from '../state'
import { ProviderAvatar } from './provider-avatar'
import { QuotaPill } from './quota-pill'
import { SessionSwitcher } from './session-switcher'
import { StatusBadge } from './status-badge'

export function ChatHeader({ state }: { state: ChatState }) {
  if (!state.record) return null
  const label = state.provider?.label ?? state.record.providerId
  const quota = state.quotas[state.record.providerId]
  if (document.body.dataset.surface === 'view') {
    return (
      <header className="flex items-center gap-1.5 border-b px-2 py-1.5">
        <ProviderAvatar providerId={state.record.providerId} className="size-6 text-[11px]" />
        <SessionSwitcher state={state} />
        <QuotaPill label={label} quota={quota} compact />
        <StatusBadge status={state.status} />
      </header>
    )
  }
  return (
    <header className="flex items-center gap-2.5 border-b px-4 py-2.5">
      <ProviderAvatar providerId={state.record.providerId} />
      <div className="min-w-0 flex-1">
        <div className="truncate font-semibold">{state.record.title}</div>
        <div className="truncate text-xs text-muted-foreground">{label}</div>
      </div>
      <QuotaPill label={label} quota={quota} />
      <StatusBadge status={state.status} />
    </header>
  )
}
```

- [ ] **Step 6: Working timer and composer placeholder**

`webview/app/components/working-status.tsx` (full replacement):

```tsx
import { Shimmer } from '@/components/ai-elements/shimmer'
import type { SessionStatus } from '../../../src/sessions/store'
import { elapsed } from '../format'
import { useNow } from '../use-now'
import { Codicon } from './codicon'

export function WorkingStatus({ status, since }: { status: SessionStatus; since?: number }) {
  const now = useNow(1000)
  const time = since ? ` ${elapsed(now - since)}` : ''
  if (status === 'running') {
    return (
      <Shimmer as="div" className="px-1 text-xs">
        {`Working…${time}`}
      </Shimmer>
    )
  }
  if (status === 'needs-input') {
    return (
      <div className="flex items-center gap-1.5 px-1 text-xs text-warning">
        <Codicon name="loading" size={12} spin />
        Waiting for your approval{time && ` ·${time}`}
      </div>
    )
  }
  return null
}
```

In `webview/app/components/composer.tsx`, change the placeholder to:

```tsx
        placeholder={busy ? 'Queue a follow-up…' : `Ask ${state.provider?.label ?? 'the agent'}…`}
```

- [ ] **Step 7: Plan progress bar**

In `webview/app/items/plan-card.tsx`, add right after the closing `</CollapsibleTrigger>`:

```tsx
      <div className="mx-3 mb-2 h-1 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-info transition-[width]"
          style={{ width: `${item.entries.length ? (done / item.entries.length) * 100 : 0}%` }}
        />
      </div>
```

- [ ] **Step 8: Turn footer**

`webview/app/items/turn-footer.tsx`:

```tsx
import { Button } from '@/components/ui/button'
import { Codicon } from '../components/codicon'
import { clockTime, promptText } from '../format'
import { send } from '../host'
import type { TurnFooter } from '../turns'

export function TurnFooterView({ footer, model }: { footer: TurnFooter; model?: string }) {
  const meta = [model, footer.at && clockTime(footer.at)].filter(Boolean).join(' · ')
  return (
    <div className="space-y-2">
      {footer.diffs.length > 0 && (
        <div className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs">
          <Codicon name="edit" className="text-muted-foreground" />
          <span className="font-medium">
            Edited {footer.files} {footer.files === 1 ? 'file' : 'files'}
          </span>
          <span className="text-success">+{footer.added}</span>
          <span className="text-destructive">−{footer.removed}</span>
          <span className="flex-1" />
          <Button size="xs" variant="ghost" onClick={() => send({ type: 'reviewChanges', itemIds: footer.diffs.map((diff) => diff.id) })}>
            Review changes
          </Button>
        </div>
      )}
      <div className="flex items-center gap-0.5 text-xs text-muted-foreground">
        {footer.reply && (
          <Button
            size="icon-xs"
            variant="ghost"
            aria-label="Copy reply"
            onClick={() => void navigator.clipboard.writeText(footer.reply?.text ?? '')}
          >
            <Codicon name="copy" size={12} />
          </Button>
        )}
        {footer.prompt && (
          <Button
            size="icon-xs"
            variant="ghost"
            aria-label="Send this prompt again"
            onClick={() => send({ type: 'prompt', text: promptText(footer.prompt?.parts ?? []), includeContext: false })}
          >
            <Codicon name="refresh" size={12} />
          </Button>
        )}
        {meta && <span className="ml-1">{meta}</span>}
      </div>
    </div>
  )
}
```

- [ ] **Step 9: App**

In `webview/app/App.tsx`:
- change the React import to `import { Fragment, useEffect, useMemo, useReducer, useState } from 'react'` and add imports:

```tsx
import { selectedModel } from './components/model-picker'
import { TurnFooterView } from './items/turn-footer'
import { turnFooters } from './turns'
```

- after `useApprovalKeys(state.items)`, add:

```tsx
  const footers = useMemo(() => turnFooters(state.items), [state.items])
  const modelFact = state.facts.model?.kind === 'model' ? state.facts.model : undefined
  const model = modelFact ? (selectedModel(modelFact)?.label ?? modelFact.current) : undefined
  const busy = state.status === 'running' || state.status === 'needs-input'
  const [since, setSince] = useState<number>()
  useEffect(() => setSince((started) => (busy ? (started ?? Date.now()) : undefined)), [busy])
```

  (these hooks must stay above the `if (state.empty) return …` line, with the other hooks);
- replace the items map with:

```tsx
            {state.items.map((item) => {
              const footer = footers.get(item.id)
              return (
                <Fragment key={item.id}>
                  <ItemView item={item} />
                  {footer && <TurnFooterView footer={footer} model={model} />}
                </Fragment>
              )
            })}
```

- change `<WorkingStatus status={state.status} />` to `<WorkingStatus status={state.status} since={since} />`.

- [ ] **Step 10: Verify and commit**

Run: `pnpm typecheck && pnpm test` → clean; PASS.

```bash
git add webview package.json pnpm-lock.yaml
git commit -m "feat(webview): quota pill, searchable session switcher, working timer, turn footers"
```

---

### Task 6: Preview and review

**Files:**
- Modify: `webview/preview/scenario.ts`

- [ ] **Step 1: A finished earlier turn and a quota report**

In `webview/preview/scenario.ts`:
- right after the `items` array declaration ends, add:

```ts
const earlier: SessionItem[] = [
  { kind: 'message', id: 'u0', role: 'user', parts: [{ type: 'text', text: 'Add a retry helper with exponential backoff.' }] },
  { kind: 'turn', id: 't0', state: 'ended', stopReason: 'success', at: '2026-10-28T09:58:00.000Z' },
  {
    kind: 'message',
    id: 'a0',
    role: 'assistant',
    streaming: false,
    text: 'Added `retry()` in `src/retry.ts` with exponential backoff, capped at 3 attempts.'
  },
  { kind: 'diff', id: 'd0', path: '/work/src/retry.ts', oldText: null, newText: 'export async function retry() {\n  // …\n}' }
]
```

- change the snapshot's `items` to `items: [...earlier, ...items]`;
- add `inTab: false` to both session summaries (and `inTab: true` to the second one instead, to show the badge);
- add this message to the `chat` array, right after `providers`:

```ts
  {
    type: 'quota',
    providerId: 'claude',
    quota: {
      observedAt: new Date(Date.now() - 3 * 60_000).toISOString(),
      windows: [
        { label: '5-hour', usedPercent: 42, resetsAt: new Date(Date.now() + 2 * 3_600_000).toISOString(), status: 'ok' },
        { label: 'Weekly', usedPercent: 18, status: 'ok' }
      ]
    }
  },
```

- [ ] **Step 2: Screenshots**

Run:

```bash
pnpm build:preview && pnpm screenshot dark 900x1300 panel && pnpm screenshot dark 340x1000 view && pnpm screenshot light 900x1300 panel
```

Open each PNG and check:
- Panel header: `5h 42% · wk 18%` pill before the amber *Input* badge.
- After the first turn: an `Edited 1 file +3 −0 · Review changes` row, then a muted line with copy and retry icons and `Opus 5.5 · <time>`.
- The plan card has a progress bar about one third full.
- The bottom line reads `Waiting for your approval` (no timer in a static preview is fine).
- Sidebar (340 px): the header is avatar, the session title with a chevron, `5h 42%`, and *Input*; nothing overflows.
- Light: same layout, readable.

Fix layout defects only in files this plan created or modified; report each fix.

- [ ] **Step 3: Package and commit**

Run: `pnpm typecheck && pnpm test && pnpm build && node dist/smoke.js claude && pnpm run package`
Expected: clean; PASS; `SMOKE OK`; packaged.

```bash
git add webview/preview
git commit -m "test(webview): preview quota, turn footers, and the sidebar switcher"
```

- [ ] **Step 4: Hand off**

Ask the user to reinstall (`code --install-extension agentdeck-0.1.0.vsix --force`), reload, and check: the quota pill appears after the first Claude or Codex turn and its hover card shows each window with reset times and age; the sidebar title opens the searchable switcher (type to filter, Enter to switch, ⌘Enter to open in a tab); a turn that edits files ends with *Edited N files · Review changes* opening the multi-diff editor; copy and retry work; the working line counts up; a chat in a hidden tab that asks for approval raises a toast whose *Review* opens it.
