# Plan 13: Transcript depth — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first. **Commit at every checkpoint** (each step whose check passes) so a usage limit cannot lose work; end each task with its named commit. Write files with the code itself; never extract code blocks from this plan with `sed` line ranges. Run each new test red before implementing.

**Goal:** Plan 13 makes the transcript read like AFK Pilot's:
- **Subagents:** a subagent's steps nest inside the card of the tool that started it.
- **Batched exploration:** runs of reads and searches fold into one "Explored N items" row.
- **Context popover:** the context meter opens a popover showing context used and the session's API-equivalent cost (Claude). It has a **Compact** button (Claude, Codex).
- **Math and diagrams:** replies render LaTeX math (KaTeX) and Mermaid diagrams.

**Not planned here:** workflow and deep-research cards, because no provider here emits workflow progress AgentDeck can read. Inline diffs at real line numbers are also left out; they stay ◐.

**Architecture:**
- **The transcript:** two pure functions turn the transcript into render units: `nestItems` (children by `parentId`) and `renderUnits` (explored batches). `App.tsx` renders units instead of items, and `ToolCard` takes the children of its tool.
- **Compact and cost:**
  - Compact is a new optional `ProviderSession.compact()`, behind the capability `'compact'`. Claude sends `/compact`; Codex sends `thread/compact/start`.
  - The context fact gains `costUsd`, from Claude's `result.total_cost_usd`.
- **Math and diagrams:**
  - Streamdown gets the official `@streamdown/math@1.0.3` and `@streamdown/mermaid@1.0.3` plugins.
  - KaTeX's CSS and fonts are copied into the webview assets.
  - Mermaid follows the VS Code theme (dark or default).

**Tech Stack:** as before, plus `@streamdown/math`, `@streamdown/mermaid`, `katex` (pinned, released more than two weeks ago).

---

### Task 1: Nesting and batching

**Files:**
- Create: `webview/app/units.ts`
- Test: `test/webview/units.test.ts`

- [ ] **Step 1: Write the failing tests**

`test/webview/units.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { SessionItem, ToolItem } from '../../src/core/types'
import { nestItems, renderUnits } from '../../webview/app/units'

const tool = (id: string, toolKind: ToolItem['toolKind'], parentId?: string): ToolItem => ({
  kind: 'tool',
  id,
  title: `${toolKind} ${id}`,
  toolKind,
  status: 'done',
  ...(parentId ? { parentId } : {})
})
const say = (id: string): SessionItem => ({ kind: 'message', id, role: 'assistant', text: id, streaming: false })

describe('nestItems', () => {
  it('moves items with a known parent under it, keeping orphans on top', () => {
    const items = [tool('task', 'other'), tool('r1', 'read', 'task'), say('m1'), tool('r2', 'read', 'gone')]
    const { top, children } = nestItems(items)
    expect(top.map((item) => item.id)).toEqual(['task', 'm1', 'r2'])
    expect(children.get('task')?.map((item) => item.id)).toEqual(['r1'])
  })
})

describe('renderUnits', () => {
  it('folds two or more reads and searches in a row into one explored unit', () => {
    const units = renderUnits([say('a'), tool('r1', 'read'), tool('s1', 'search'), tool('f1', 'fetch'), say('b'), tool('r2', 'read'), tool('e1', 'execute')])
    expect(units.map((unit) => (unit.type === 'item' ? unit.item.id : `explored:${unit.items.map((item) => item.id).join(',')}`))).toEqual([
      'a',
      'explored:r1,s1,f1',
      'b',
      'r2',
      'e1'
    ])
  })

  it('does not fold running or failed tools', () => {
    const running: ToolItem = { ...tool('r1', 'read'), status: 'running' }
    expect(renderUnits([running, tool('r2', 'read')]).map((unit) => unit.type)).toEqual(['item', 'item'])
  })
})
```

Run: `pnpm test test/webview/units.test.ts` → FAIL.

- [ ] **Step 2: Implement**

`webview/app/units.ts`:

```ts
import type { SessionItem, ToolItem } from '../../src/core/types'

/** Items whose parent is in the transcript go under it (a subagent's steps under the tool that started it). */
export function nestItems(items: SessionItem[]): { top: SessionItem[]; children: Map<string, SessionItem[]> } {
  const ids = new Set(items.map((item) => item.id))
  const children = new Map<string, SessionItem[]>()
  const top: SessionItem[] = []
  for (const item of items) {
    const parentId = 'parentId' in item ? item.parentId : undefined
    if (parentId && ids.has(parentId)) children.set(parentId, [...(children.get(parentId) ?? []), item])
    else top.push(item)
  }
  return { top, children }
}

export type RenderUnit = { type: 'item'; item: SessionItem } | { type: 'explored'; items: ToolItem[] }

const EXPLORING = new Set<ToolItem['toolKind']>(['read', 'search', 'fetch'])
const explores = (item: SessionItem): item is ToolItem => item.kind === 'tool' && item.status === 'done' && EXPLORING.has(item.toolKind)

/** Two or more finished reads, searches, or fetches in a row read as one "Explored N items" row. */
export function renderUnits(items: SessionItem[]): RenderUnit[] {
  const units: RenderUnit[] = []
  let run: ToolItem[] = []
  const flush = () => {
    if (run.length >= 2) units.push({ type: 'explored', items: run })
    else units.push(...run.map((item) => ({ type: 'item' as const, item })))
    run = []
  }
  for (const item of items) {
    if (explores(item)) {
      run.push(item)
      continue
    }
    flush()
    units.push({ type: 'item', item })
  }
  flush()
  return units
}
```

Run: `pnpm test test/webview/units.test.ts` → PASS.

- [ ] **Step 3: Render**

Create `webview/app/items/explored-card.tsx`:

```tsx
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { ToolItem } from '../../../src/core/types'
import { Codicon } from '../components/codicon'
import { ToolCard } from './tool-card'

export function ExploredCard({ items }: { items: ToolItem[] }) {
  return (
    <Collapsible className="group">
      <CollapsibleTrigger className="flex items-center gap-2 px-1 text-xs text-muted-foreground hover:text-foreground">
        <Codicon name="search" size={12} />
        Explored {items.length} items
        <Codicon name="chevron-down" size={12} className="transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-1.5 space-y-1.5">
        {items.map((item) => (
          <ToolCard key={item.id} item={item} />
        ))}
      </CollapsibleContent>
    </Collapsible>
  )
}
```

In `webview/app/items/tool-card.tsx`:
- change the signature to `export function ToolCard({ item, steps = [] }: { item: ToolItem; steps?: SessionItem[] })` (import `SessionItem` and `ItemView` from `./item-view`; if that import creates a cycle esbuild cannot handle, pass a `renderStep` prop from `App.tsx` instead and report);
- after `<span className="font-medium">{verb}</span>…` keep the header and add, before the status pill: `{steps.length > 0 && <span className="text-[10px] text-muted-foreground">{steps.length} steps</span>}`;
- at the top of `CollapsibleContent`, add `{steps.length > 0 && <div className="space-y-1.5 border-l pl-2">{steps.map((step) => <ItemView key={step.id} item={step} />)}</div>}`.

In `webview/app/items/item-view.tsx`, add an optional prop `steps?: SessionItem[]` and pass it to `ToolCard`: `case 'tool': return <ToolCard item={item} steps={steps} />`.

In `webview/app/App.tsx`, replace the `state.items.map(…)` block with:

```tsx
            {(() => {
              const { top, children } = nestItems(state.items)
              return renderUnits(top).map((unit) => {
                const items = unit.type === 'item' ? [unit.item] : unit.items
                const footer = items.map((item) => footers.get(item.id)).find(Boolean)
                return (
                  <Fragment key={items[0].id}>
                    {unit.type === 'item' ? <ItemView item={unit.item} steps={children.get(unit.item.id)} /> : <ExploredCard items={unit.items} />}
                    {footer && <TurnFooterView footer={footer} model={model} />}
                  </Fragment>
                )
              })
            })()}
```

(import `nestItems`, `renderUnits` from `./units` and `ExploredCard` from `./items/explored-card`). Footers are keyed by a turn's last item; if that item is nested under a parent, it is not rendered at the top, so also check `children` — change the `footer` line to look through the unit's items and their children:

```tsx
                const footer = items.flatMap((item) => [item, ...(children.get(item.id) ?? [])]).map((item) => footers.get(item.id)).find(Boolean)
```

Run: `pnpm typecheck && pnpm test` → clean; PASS.

- [ ] **Step 4: Commit**

```bash
git add webview test/webview/units.test.ts
git commit -m "feat(webview): subagent steps nest under their tool; runs of reads fold into Explored"
```

---

### Task 2: Context popover, cost, and Compact

**Files:**
- Modify: `src/core/types.ts`, `src/sessions/manager.ts`, `src/providers/claude/provider.ts`, `src/providers/codex/provider.ts`, `src/ui/protocol.ts`, `src/ui/chat-surfaces.ts`, `webview/app/components/context-meter.tsx`, `webview/app/components/composer.tsx`, `test/fake-provider.ts`, `test/sessions/manager.test.ts`

- [ ] **Step 1: Write the failing test**

In `test/fake-provider.ts`, add `compacted = 0` and `async compact(): Promise<void> { this.compacted++ }` to `FakeSession`.

Add inside the `describe` block of `test/sessions/manager.test.ts`:

```ts
  it('compacts through the provider and notes it in the transcript', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.warm(id)
    const events = watch(manager, id)
    await manager.compact(id)
    expect(sessions[0].compacted).toBe(1)
    expect(events.some((event) => event.type === 'item' && event.item.kind === 'notice' && /Compacting/.test(event.item.text))).toBe(true)
  })
```

Run → FAIL.

- [ ] **Step 2: Implement**

In `src/core/types.ts`:
- change the context fact to `| { kind: 'context'; usedTokens: number; maxTokens: number; /** Session total at API prices (Claude reports it; subscriptions are not billed this). */ costUsd?: number }`;
- add `| 'compact'` to `Capability`;
- add to `ProviderSession`: `/** Summarizes the conversation to free context. */ compact?(): Promise<void>`.

In `src/sessions/manager.ts`, add after `setEffort` (or after `setMode`):

```ts
  async compact(id: string): Promise<void> {
    const live = this.load(id)
    const session = live.session ?? (await this.connect(live))
    if (!session.compact) return
    this.notify(id, 'Compacting the conversation…')
    await session.compact()
  }
```

In `src/providers/claude/provider.ts`:
- add `'compact'` to the capabilities;
- add a field `private costUsd: number | undefined`;
- in the pump, change `if (message.type === 'result') void this.refreshContext()` to:

```ts
        if (message.type === 'result') {
          this.costUsd = message.total_cost_usd
          void this.refreshContext()
        }
```

- in `refreshContext`, fire `{ kind: 'context', usedTokens: usage.totalTokens, maxTokens: usage.maxTokens, ...(this.costUsd !== undefined ? { costUsd: this.costUsd } : {}) }`;
- add `async compact(): Promise<void> { await this.prompt([{ type: 'command', name: 'compact' }]) }`.

In `src/providers/codex/provider.ts`:
- add `'compact'` to the capabilities;
- add `async compact(): Promise<void> { await this.rpc.request('thread/compact/start', { threadId: this.nativeId }) }`.

In `src/ui/protocol.ts`, add the webview message `| { type: 'compact' }`; in `src/ui/chat-surfaces.ts`, handle it: `case 'compact': if (sessionId) await this.manager.compact(sessionId); return`.

`webview/app/components/context-meter.tsx` (full replacement):

```tsx
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { SessionFact } from '../../../src/core/types'
import { send } from '../host'

const RADIUS = 6
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

/** Context used, the session's API-equivalent cost when the provider reports it, and Compact. */
export function ContextMeter({ fact, canCompact }: { fact?: Extract<SessionFact, { kind: 'context' }>; canCompact: boolean }) {
  if (!fact || fact.maxTokens <= 0) return null
  const ratio = Math.min(fact.usedTokens / fact.maxTokens, 1)
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button type="button" className="inline-flex items-center gap-1 rounded px-1 text-xs text-muted-foreground hover:bg-accent" aria-label="Context">
          <svg width="16" height="16" viewBox="0 0 16 16" className="-rotate-90" aria-hidden>
            <circle cx="8" cy="8" r={RADIUS} fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2" />
            <circle
              cx="8"
              cy="8"
              r={RADIUS}
              fill="none"
              stroke={ratio > 0.85 ? 'var(--warning)' : 'var(--info)'}
              strokeWidth="2"
              strokeLinecap="round"
              strokeDasharray={CIRCUMFERENCE}
              strokeDashoffset={CIRCUMFERENCE * (1 - ratio)}
            />
          </svg>
          <span className="hidden @[20rem]:inline">{Math.round(ratio * 100)}%</span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 space-y-2 text-xs">
        <div className="font-medium">Context</div>
        <div className="text-muted-foreground">
          {fact.usedTokens.toLocaleString()} of {fact.maxTokens.toLocaleString()} tokens ({Math.round(ratio * 100)}%)
        </div>
        {fact.costUsd !== undefined && (
          <div className="text-muted-foreground">
            Session at API prices: ${fact.costUsd.toFixed(2)} <span className="opacity-70">(not billed on a subscription)</span>
          </div>
        )}
        {canCompact && (
          <Button size="sm" variant="secondary" className="w-full" onClick={() => send({ type: 'compact' })}>
            Compact conversation
          </Button>
        )}
      </PopoverContent>
    </Popover>
  )
}
```

In `webview/app/components/composer.tsx`, pass `canCompact={state.provider?.capabilities.includes('compact') ?? false}` to `ContextMeter`.

Run: `pnpm typecheck && pnpm test` → clean; PASS.

- [ ] **Step 3: Commit**

```bash
git add src test webview
git commit -m "feat: context popover with session cost and Compact"
```

---

### Task 3: Math and diagrams

**Files:**
- Modify: `package.json`, `webview/components/ai-elements/message.tsx`, `esbuild.mjs`, `src/ui/chat-surfaces.ts`, `webview/preview/index.html`

- [ ] **Step 1: Dependencies**

Run: `pnpm add @streamdown/math@1.0.3 @streamdown/mermaid@1.0.3 katex@0.16.27`
(If pnpm's minimum release age rejects a version, pick the newest version of that package published at least 14 days ago and report it; do not add a `minimumReleaseAgeExclude`.) Then check that `package.json` pins exact versions (no `^`), matching how the other dependencies are written.

- [ ] **Step 2: Plugins**

In `webview/components/ai-elements/message.tsx`:
- import `{ math }` from `@streamdown/math` and `{ createMermaidPlugin }` from `@streamdown/mermaid`;
- replace `const streamdownPlugins = { code };` with:

```ts
// Mermaid follows the VS Code theme kind, read once when the webview loads.
const dark = typeof document !== 'undefined' && document.body.classList.contains('vscode-dark')
const streamdownPlugins = { code, math, mermaid: createMermaidPlugin({ config: { theme: dark ? 'dark' : 'default' } }) }
```

(If Streamdown's `plugins` prop names the keys differently, check its `PluginConfig` type in `node_modules/streamdown/dist/index.d.ts` and use its key names; report.)

- [ ] **Step 3: KaTeX styles**

In `esbuild.mjs`, in `styles(outdir)`, add:

```js
  cpSync('node_modules/katex/dist/katex.min.css', `${outdir}/katex.css`)
  cpSync('node_modules/katex/dist/fonts', `${outdir}/fonts`, { recursive: true })
```

In `src/ui/chat-surfaces.ts` `html()`, add `<link rel="stylesheet" href="${asset('katex.css')}">` after the codicon stylesheet. In `webview/preview/index.html`, add `<link rel="stylesheet" href="katex.css">` after `codicon.css`.

- [ ] **Step 4: Preview check**

In `webview/preview/scenario.ts`, add to the default chat's items an assistant message:

````ts
  {
    kind: 'message',
    id: 'm-math',
    role: 'assistant',
    streaming: false,
    text: 'The backoff grows as $$d_n = d_0 \\cdot 2^n$$ and the flow is:\n\n```mermaid\ngraph LR\n  A[request] --> B{ok?}\n  B -- no --> C[wait d_n]\n  C --> A\n```'
  },
````

(placed among the existing items; add `explored` material too: two consecutive `tool` items with `toolKind: 'read'` and `status: 'done'` just before it).

Run: `pnpm build:preview && pnpm screenshot dark 900x1400 panel chat && pnpm screenshot light 900x1400 panel chat`
Open both: the formula renders as typeset math (not raw `$$`), the Mermaid block renders as a diagram readable in each theme, and the two reads show as "Explored 2 items". Report what you see. If the diagram fails only in headless Chromium, say so; the user checks it in VS Code.

- [ ] **Step 5: Package, docs, commit**

Run: `pnpm typecheck && pnpm test && pnpm run package` → clean; PASS; packaged (report the VSIX size before and after; Mermaid is large).

In `docs/superpowers/plans/2026-10-28-mvp-overview.md`, add a row for plan 13 (`| 13 | [Transcript depth](2026-10-30-13-transcript-depth.md) | Subagent steps nested, Explored batches, context popover with cost and Compact, LaTeX and Mermaid | Done |`). In `docs/roadmap.md`: mark *Subagent cards* ✓, *Tool batching…* ◐ (Explored batches; inline diffs at real line numbers later), *Workflow / deep-research progress cards* — (not planned: no provider exposes it), *Context and cost popover…* ✓, *LaTeX and Mermaid* ✓; end the line starting `- **13 — Transcript depth:**` with ` ✓ done.`

```bash
git add package.json pnpm-lock.yaml esbuild.mjs webview src docs
git commit -m "feat(webview): LaTeX and Mermaid in replies; plan 13 done"
```
