# Plan 12: Turn controls — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first. **Commit at every checkpoint** (each step whose check passes) so a usage limit cannot lose work; end each task with its named commit. Write files with the code itself; never extract code blocks from this plan with `sed` line ranges. Run each new test red before implementing.

**Goal:** Plan 12 brings AgentDeck's turn controls up to AFK Pilot's:
- **Reasoning effort:** you can set it live, for the models that support it.
- **Queued messages:**
  - you can **steer** a running turn with a queued message (Codex, Claude);
  - you can **edit** a queued message;
  - typing more while busy **merges** into the last queued message.
- **Drafts:** your draft is kept per chat, across chat switches and reloads.
- **History:** ↑ and ↓ in an empty composer walk back and forth through the chat's earlier prompts.

**Architecture:**

*Effort*
- Effort is a new session fact: `{ kind: 'effort', current?, available }`.
- Providers that support it:
  - **Claude:** each model reports `supportedEffortLevels`. Effort is set with `query.applyFlagSettings({ effortLevel })`, and passed as the `effort` option when a session starts.
  - **Codex:** each model reports `supportedReasoningEfforts` and `defaultReasoningEffort`. Effort is sent as `turn/start.effort`.
- Each provider that supports effort or steering declares it as a capability (`'effort'`, `'steer'`).

*Steering*
- **Codex:** `turn/steer { threadId, expectedTurnId, input }`.
- **Claude:** the message is pushed into the SDK's streaming input while the turn runs. The live check in Task 4 confirms the CLI takes it mid-turn; if it doesn't, Claude's `'steer'` capability is removed.

*Queue editing*
- The session manager merges a new prompt into the last queued message, and steers a queued message on request.
- Editing a queued message removes it from the queue and loads it back into the composer.

*Drafts and history*
- **Drafts:** a chat's draft is saved in the webview's persisted state, keyed by chat.
- **History:** ↑ and ↓ walk the chat's earlier user messages.
- **Restoring prompts:** both turn stored prompt parts back into composer content with a new `toDocument`, the inverse of `toParts`.

**Tech Stack:** as before.

---

### Task 1: Core and manager

**Files:**
- Modify: `src/core/types.ts`, `src/sessions/store.ts`, `src/sessions/manager.ts`, `test/fake-provider.ts`, `test/sessions/manager.test.ts`

- [ ] **Step 1: Types**

In `src/core/types.ts`:
- add `| { kind: 'effort'; current?: string; available: string[] }` to `SessionFact`;
- add `| 'steer' | 'effort'` to `Capability`;
- add `effort?: string` to `OpenOptions`;
- add to `ProviderSession` after `setModel` (or after `setMode` if `setModel` is not there):

```ts
  /** Sets the reasoning effort for this and later turns. */
  setEffort?(effort: string): Promise<void>
  /** Adds a message to the running turn instead of waiting for it to end. */
  steer?(parts: PromptPart[]): Promise<void>
```

In `src/sessions/store.ts`, add `effort?: string` to `SessionRecord` after `model`.

- [ ] **Step 2: Write the failing tests**

In `test/fake-provider.ts`: add fields `readonly efforts: string[] = []` and `readonly steers: PromptPart[][] = []` to `FakeSession` and methods:

```ts
  async setEffort(effort: string): Promise<void> {
    this.efforts.push(effort)
  }

  async steer(parts: PromptPart[]): Promise<void> {
    this.steers.push(parts)
  }
```

Also make the fake session record the options it was opened with (it already keeps `options`).

Add inside the `describe` block of `test/sessions/manager.test.ts`:

```ts
  it('sets the effort live and opens later sessions with it', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.warm(id)
    await manager.setEffort(id, 'high')
    expect(sessions[0].efforts).toEqual(['high'])
    expect(manager.list()[0].record.effort).toBe('high')
    await manager.stop(id)
    await manager.warm(id)
    expect(sessions[1].options.effort).toBe('high')
  })

  it('merges further typing into the last queued message', async () => {
    const { manager } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.prompt(id, text('first'))
    await manager.prompt(id, text('second'))
    await manager.prompt(id, text('third'))
    const queues = events.filter((event) => event.type === 'queue')
    expect(queues.at(-1)).toMatchObject({ queue: [{ parts: [...text('second'), ...text('third')] }] })
  })

  it('steers a queued message into the running turn', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.prompt(id, text('first'))
    await manager.prompt(id, text('also this'))
    const queued = events.filter((event) => event.type === 'queue').at(-1)
    const queuedId = queued?.type === 'queue' ? queued.queue[0].id : ''
    await manager.steer(id, queuedId)
    expect(sessions[0].steers).toEqual([text('also this')])
    expect(events.filter((event) => event.type === 'queue').at(-1)).toMatchObject({ queue: [] })
    expect(events.filter((event) => event.type === 'item' && event.item.kind === 'message' && event.item.role === 'user')).toHaveLength(2)
  })
```

Run: `pnpm test test/sessions` → FAIL.

- [ ] **Step 3: Implement**

In `src/sessions/manager.ts`:
- where a session is opened (`open`), pass the record's effort: add `...(live.record.effort ? { effort: live.record.effort } : {})` to the `OpenOptions` object built there;
- in `prompt`, replace `live.queue.push({ id: randomUUID(), parts })` with:

```ts
      // Further typing while busy joins the last queued message rather than lining up behind it.
      const last = live.queue.at(-1)
      if (last) last.parts = [...last.parts, ...parts]
      else live.queue.push({ id: randomUUID(), parts })
```

- add after `setMode`:

```ts
  async setEffort(id: string, effort: string): Promise<void> {
    const live = this.load(id)
    live.record.effort = effort
    await this.save(live)
    await live.session?.setEffort?.(effort)
  }

  /** Sends a queued message into the running turn now; when nothing is running it is simply sent. */
  async steer(id: string, queuedId: string): Promise<void> {
    const live = this.load(id)
    const queued = live.queue.find((entry) => entry.id === queuedId)
    if (!queued) return
    live.queue = live.queue.filter((entry) => entry.id !== queuedId)
    this.broadcast(live, { type: 'queue', queue: [...live.queue] })
    if (!isBusy(live.status) || !live.session?.steer) return this.send(live, queued.parts)
    this.upsert(live, { kind: 'message', id: `user:${randomUUID()}`, role: 'user', parts: queued.parts })
    await live.session.steer(queued.parts)
  }
```

  (`isBusy` exists from plan 20; if not, add `const isBusy = (status: SessionStatus) => status === 'running' || status === 'needs-input'` at module level.)

Run: `pnpm test` → PASS.

- [ ] **Step 4: Commit**

```bash
git add src/core/types.ts src/sessions test/fake-provider.ts test/sessions/manager.test.ts
git commit -m "feat(sessions): live effort, steering, and merging further typing into the queue"
```

---

### Task 2: Providers

**Files:**
- Modify: `src/providers/claude/provider.ts`, `src/providers/codex/provider.ts`

- [ ] **Step 1: Claude**

In `src/providers/claude/provider.ts`:
- add `'effort', 'steer'` to the definition's `capabilities` set;
- import `type EffortLevel` from the SDK with the other SDK types;
- add a field `private efforts = new Map<string, string[]>()` (model id → levels);
- in the `query({ options })` object add `...(options.effort ? { effort: options.effort as EffortLevel } : {}),`;
- in `loadFacts`, inside the `supportedModels` mapping, record levels: after building `this.models`, add `this.efforts = new Map(models.map((model) => [model.value, model.supportedEffortLevels ?? []]))`; after the model fact is fired, add `this.fireEffort()`;
- in `setModel`, after the model fact, add `this.fireEffort()`;
- add a field `private effort: string | undefined` initialised in the constructor to `options.effort`;
- add methods:

```ts
  async setEffort(effort: string): Promise<void> {
    await this.query.applyFlagSettings({ effortLevel: effort as EffortLevel })
    this.effort = effort
    this.fireEffort()
  }

  async steer(parts: PromptPart[]): Promise<void> {
    // The CLI reads streaming input during a turn and takes the message at its next step.
    this.push(parts)
  }

  private fireEffort(): void {
    const available = this.efforts.get(this.model) ?? this.efforts.get(this.models.find((model) => model.resolved === this.model)?.id ?? '') ?? []
    this.facts.fire({ kind: 'effort', ...(this.effort ? { current: this.effort } : {}), available })
  }
```

- split `prompt`: move everything after `this.translator.startTurn()` into `private push(parts: PromptPart[]): void`, so `prompt` becomes:

```ts
  async prompt(parts: PromptPart[]): Promise<void> {
    this.translator.startTurn()
    this.push(parts)
  }
```

- [ ] **Step 2: Codex**

In `src/providers/codex/provider.ts`:
- add `'effort', 'steer'` to the definition's `capabilities` set;
- extend the local `ModelInfo` type with `supportedReasoningEfforts?: { reasoningEffort: string }[]; defaultReasoningEffort?: string`;
- add fields `private effort: string | undefined` (set from `options.effort` in the constructor) and `private efforts = new Map<string, { levels: string[]; default?: string }>()`;
- in `loadFacts`, after `this.models = …`, add:

```ts
      this.efforts = new Map(
        data.map((model) => [
          model.id,
          { levels: (model.supportedReasoningEfforts ?? []).map((option) => option.reasoningEffort), default: model.defaultReasoningEffort }
        ])
      )
```

  and after the model fact is fired, `this.fireEffort()`; in `setModel`, after the model fact, `this.fireEffort()`;
- move the `input: [ … ]` array in `prompt` into `private input(parts: PromptPart[])` returning it, so `prompt` uses `input: this.input(parts),` and add `effort: this.effort ?? null,` to the `turn/start` params;
- add methods:

```ts
  async setEffort(effort: string): Promise<void> {
    this.effort = effort
    this.fireEffort()
  }

  async steer(parts: PromptPart[]): Promise<void> {
    if (!this.turnId) return this.prompt(parts)
    await this.rpc.request('turn/steer', { threadId: this.nativeId, expectedTurnId: this.turnId, input: this.input(parts) })
  }

  private fireEffort(): void {
    const model = this.efforts.get(this.model ?? '')
    const current = this.effort ?? model?.default
    this.facts.fire({ kind: 'effort', ...(current ? { current } : {}), available: model?.levels ?? [] })
  }
```

- [ ] **Step 3: Verify and commit**

Run: `pnpm typecheck && pnpm test` → clean except `webview` (Task 3 handles the new fact and messages if the webview's exhaustive switches complain); PASS.

```bash
git add src/providers
git commit -m "feat(providers): reasoning effort and steering for Claude and Codex"
```

---

### Task 3: Webview

**Files:**
- Modify: `src/ui/protocol.ts`, `src/ui/chat-surfaces.ts`, `webview/app/host.ts`, `webview/app/composer/prompt-document.ts`, `webview/app/composer/prompt-editor.tsx`, `webview/app/components/composer.tsx`, `webview/app/components/queue-list.tsx`, `webview/app/App.tsx`
- Create: `webview/app/composer/history.ts`, `webview/app/composer/drafts.ts`, `webview/app/components/effort-picker.tsx`
- Test: `test/webview/prompt-document.test.ts`, `test/webview/composer-memory.test.ts`

- [ ] **Step 1: Write the failing tests**

Add to `test/webview/prompt-document.test.ts` (import `toDocument` with `toParts`):

```ts
describe('toDocument', () => {
  it('turns prompt parts back into composer content', () => {
    const parts = [
      { type: 'command', name: 'review' },
      { type: 'text', text: 'look at' },
      { type: 'file', path: '/w/src/a.ts' },
      { type: 'text', text: 'and this\nsecond line' },
      { type: 'pasted', text: 'long paste' },
      { type: 'image', path: '/s/i.png', mimeType: 'image/png', name: 'i.png' }
    ] as const
    expect(toParts(toDocument([...parts]))).toEqual(parts)
  })
})
```

`test/webview/composer-memory.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { PromptPart } from '../../src/core/types'
import { Drafts } from '../../webview/app/composer/drafts'
import { History } from '../../webview/app/composer/history'

const p = (text: string): PromptPart[] => [{ type: 'text', text }]

describe('History', () => {
  it('walks back from the newest prompt and forward to empty', () => {
    const history = new History([p('one'), p('two'), p('three')])
    expect(history.up()).toEqual(p('three'))
    expect(history.up()).toEqual(p('two'))
    expect(history.up()).toEqual(p('one'))
    expect(history.up()).toEqual(p('one'))
    expect(history.down()).toEqual(p('two'))
    expect(history.down()).toEqual(p('three'))
    expect(history.down()).toEqual([])
    expect(history.down()).toBeUndefined()
  })

  it('has nothing to show without prompts', () => {
    expect(new History([]).up()).toBeUndefined()
  })
})

describe('Drafts', () => {
  it('keeps a draft per chat in the given store and forgets empty ones', () => {
    let saved: unknown = { sessionId: 's1' }
    const store = { get: () => saved, set: (value: unknown) => (saved = value) }
    const drafts = new Drafts(store)
    drafts.save('s1', { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'hi' }] }] })
    expect(new Drafts(store).load('s1')).toEqual({ type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'hi' }] }] })
    expect(saved).toMatchObject({ sessionId: 's1' })
    drafts.save('s1', undefined)
    expect(drafts.load('s1')).toBeUndefined()
  })
})
```

Run: `pnpm test test/webview` → FAIL.

- [ ] **Step 2: Pure modules**

In `webview/app/composer/prompt-document.ts`, add:

```ts
/** Prompt parts as composer content: the inverse of `toParts`, for history, drafts, and editing queued messages. */
export function toDocument(parts: PromptPart[]): JSONContent {
  const paragraphs: JSONContent[][] = [[]]
  const current = () => paragraphs[paragraphs.length - 1]
  // Pills get a space on each side for reading; toParts trims text around them, so the parts come back unchanged.
  const pill = (node: JSONContent) => current().push(...(current().length > 0 ? [{ type: 'text', text: ' ' }] : []), node, { type: 'text', text: ' ' })
  for (const part of parts) {
    if (part.type === 'text') {
      part.text.split('\n').forEach((line, index) => {
        if (index > 0) paragraphs.push([])
        if (line) current().push({ type: 'text', text: line })
      })
    } else if (part.type === 'file') {
      pill({ type: 'mention', attrs: { id: part.path, label: part.path.split('/').pop() ?? part.path, mentionSuggestionChar: '@' } })
    } else if (part.type === 'command') {
      pill({ type: 'mention', attrs: { id: part.name, label: part.name, mentionSuggestionChar: '/' } })
    } else if (part.type === 'pasted') {
      pill({ type: 'pastedText', attrs: { text: part.text } })
    } else {
      pill({ type: 'imageAttachment', attrs: { path: part.path, mimeType: part.mimeType, name: part.name } })
    }
  }
  return { type: 'doc', content: paragraphs.map((content) => ({ type: 'paragraph', ...(content.length > 0 ? { content } : {}) })) }
}
```

(If the round-trip test fails only on whitespace inside text parts, adjust the spaces added here, not the test.)

`webview/app/composer/history.ts`:

```ts
import type { PromptPart } from '../../../src/core/types'

/** ↑/↓ through a chat's earlier prompts: up goes back from the newest, down returns toward an empty composer. */
export class History {
  private index = -1

  constructor(private readonly entries: PromptPart[][]) {}

  up(): PromptPart[] | undefined {
    if (this.entries.length === 0) return undefined
    this.index = Math.min(this.index + 1, this.entries.length - 1)
    return this.entries[this.entries.length - 1 - this.index]
  }

  /** The next newer prompt, `[]` when stepping past the newest, undefined when not browsing. */
  down(): PromptPart[] | undefined {
    if (this.index < 0) return undefined
    this.index--
    return this.index < 0 ? [] : this.entries[this.entries.length - 1 - this.index]
  }
}
```

`webview/app/composer/drafts.ts`:

```ts
import type { JSONContent } from '@tiptap/core'

type Store = { get(): unknown; set(value: unknown): void }

/** Unsent drafts per chat, kept in the webview's persisted state next to whatever else is stored there. */
export class Drafts {
  constructor(private readonly store: Store) {}

  load(sessionId: string): JSONContent | undefined {
    return this.all()[sessionId]
  }

  save(sessionId: string, doc: JSONContent | undefined): void {
    const drafts = { ...this.all() }
    if (doc) drafts[sessionId] = doc
    else delete drafts[sessionId]
    const state = this.store.get()
    this.store.set({ ...(typeof state === 'object' && state !== null ? state : {}), drafts })
  }

  private all(): Record<string, JSONContent> {
    const state = this.store.get() as { drafts?: Record<string, JSONContent> } | undefined
    return state?.drafts ?? {}
  }
}
```

Run: `pnpm test test/webview` → PASS.

- [ ] **Step 3: Host messages and state**

In `src/ui/protocol.ts`, add webview messages `| { type: 'setEffort'; effort: string }` and `| { type: 'steer'; queuedId: string }`. In `src/ui/chat-surfaces.ts`, handle them next to `'setMode'`:

```ts
      case 'setEffort':
        if (sessionId) await this.manager.setEffort(sessionId, message.effort)
        return
      case 'steer':
        if (sessionId) await this.manager.steer(sessionId, message.queuedId)
        return
```

In `webview/app/host.ts`:
- change `saveState` so it merges instead of replacing: `api.setState({ ...(api.getState() as object | undefined), ...state })`;
- export the store for drafts: `export const persisted = { get: () => api.getState(), set: (value: unknown) => api.setState(value) }`.

- [ ] **Step 4: Editor handle, drafts, and history**

In `webview/app/composer/prompt-editor.tsx`:
- extend `PromptEditorHandle` with `getContent: () => JSONContent` and `setContent: (doc: JSONContent | undefined) => void`;
- add a prop `history: PromptPart[][]`;
- add a ref `const browsing = useRef<History | null>(null)` and a ref `const loading = useRef(false)`; import `History` from `./history` and `toDocument` from `./prompt-document`;
- add a keyboard extension inline in the `extensions` array, after `SubmitOnEnter`:

```ts
      Extension.create({
        name: 'promptHistory',
        addKeyboardShortcuts: () => ({
          ArrowUp: ({ editor: current }) => {
            if (!current.isEmpty && !browsing.current) return false
            browsing.current ??= new History(historyRef.current)
            const parts = browsing.current.up()
            if (!parts) return false
            load(toDocument(parts))
            return true
          },
          ArrowDown: () => {
            const parts = browsing.current?.down()
            if (!parts) return false
            load(parts.length > 0 ? toDocument(parts) : undefined)
            if (parts.length === 0) browsing.current = null
            return true
          }
        })
      }),
```

  with `import { Extension } from '@tiptap/core'` (merge with the existing `@tiptap/core` import), `const historyRef = useRef(history); historyRef.current = history`, and:

```ts
  const load = (doc: JSONContent | undefined) => {
    loading.current = true
    if (doc) editor?.commands.setContent(doc, { emitUpdate: true })
    else editor?.commands.clearContent(true)
    loading.current = false
  }
```

- in `onUpdate`, stop browsing when the user types: `if (!loading.current) browsing.current = null` before `onEmptyChange(current.isEmpty)`; also pass a new prop callback `onChange?: (doc: JSONContent) => void` called there with `current.getJSON()`;
- in `submitRef.current`, after `clearContent`, set `browsing.current = null`;
- add to `useImperativeHandle`: `getContent: () => editor?.getJSON() ?? { type: 'doc' }` and `setContent: load`.

(If `setContent`'s second argument has a different shape in TipTap 3.32, use the form that emits an update, e.g. `setContent(doc, true)`; report which.)

In `webview/app/components/composer.tsx`:
- import `persisted` from `../host`, `Drafts` from `../composer/drafts`, `EffortPicker` from `./effort-picker`, and `onEdit` from `../composer/edit-bus` (Step 5);
- create `const drafts = useMemo(() => new Drafts(persisted), [])` (import `useMemo`);
- compute `const history = useMemo(() => state.items.flatMap((item) => (item.kind === 'message' && item.role === 'user' ? [item.parts] : [])), [state.items])` and pass `history={history}` and `onChange={(doc) => state.sessionId && drafts.save(state.sessionId, editor.current && !isEmptyDoc(doc) ? doc : undefined)}` to `PromptEditor`, with:

```ts
const isEmptyDoc = (doc: JSONContent) => !(doc.content ?? []).some((block) => (block.content ?? []).length > 0)
```

  (import `type JSONContent` from `@tiptap/core`);
- restore a chat's draft when the chat changes:

```ts
  useEffect(() => {
    editor.current?.setContent(state.sessionId ? drafts.load(state.sessionId) : undefined)
  }, [state.sessionId, drafts])
```

- after sending (`submit`), clear the draft: `if (state.sessionId) drafts.save(state.sessionId, undefined)`;
- render `<EffortPicker fact={state.facts.effort?.kind === 'effort' ? state.facts.effort : undefined} />` right after `<ModelPicker … />`;
- subscribe to queued-message edits: `useEffect(() => onEdit((parts) => editor.current?.setContent(toDocument(parts))), [])` (import `toDocument`).

- [ ] **Step 5: Queue list and effort picker**

`webview/app/composer/edit-bus.ts`:

```ts
import type { PromptPart } from '../../../src/core/types'

const listeners = new Set<(parts: PromptPart[]) => void>()

/** Moves a queued message back into the composer for editing. */
export function editInComposer(parts: PromptPart[]): void {
  for (const listener of listeners) listener(parts)
}

export function onEdit(listener: (parts: PromptPart[]) => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
```

`webview/app/components/queue-list.tsx` (full replacement):

```tsx
import type { QueuedPrompt } from '../../../src/sessions/manager'
import { editInComposer } from '../composer/edit-bus'
import { promptText } from '../format'
import { send } from '../host'
import { Codicon } from './codicon'

export function QueueList({ queue, canSteer }: { queue: QueuedPrompt[]; canSteer: boolean }) {
  if (queue.length === 0) return null
  return (
    <div className="space-y-1">
      {queue.map((queued) => (
        <div key={queued.id} className="flex items-center gap-2 rounded-md border bg-card px-3 py-1.5 text-sm">
          <span className="text-xs text-muted-foreground">Queued</span>
          <span className="min-w-0 flex-1 truncate">{promptText(queued.parts)}</span>
          {canSteer && (
            <button
              type="button"
              title="Send now, into the running turn"
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              onClick={() => send({ type: 'steer', queuedId: queued.id })}
            >
              <Codicon name="arrow-up" size={12} />
              Steer
            </button>
          )}
          <button
            type="button"
            aria-label="Edit queued message"
            className="text-muted-foreground hover:text-foreground"
            onClick={() => {
              send({ type: 'removeQueued', queuedId: queued.id })
              editInComposer(queued.parts)
            }}
          >
            <Codicon name="edit" />
          </button>
          <button
            type="button"
            aria-label="Remove queued message"
            className="text-muted-foreground hover:text-foreground"
            onClick={() => send({ type: 'removeQueued', queuedId: queued.id })}
          >
            <Codicon name="close" />
          </button>
        </div>
      ))}
    </div>
  )
}
```

In `webview/app/App.tsx`, change `<QueueList queue={state.queue} />` to `<QueueList queue={state.queue} canSteer={state.provider?.capabilities.includes('steer') ?? false} />`.

`webview/app/components/effort-picker.tsx`:

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

const label = (effort: string) => effort.charAt(0).toUpperCase() + effort.slice(1)

/** Reasoning effort for models that offer levels. */
export function EffortPicker({ fact }: { fact?: Extract<SessionFact, { kind: 'effort' }> }) {
  if (!fact || fact.available.length === 0) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="xs" variant="ghost" className="text-muted-foreground" title="Reasoning effort">
          <Codicon name="lightbulb" size={12} />
          <span className="hidden @[26rem]:inline">{fact.current ? label(fact.current) : 'Effort'}</span>
          <Codicon name="chevron-down" size={12} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuRadioGroup value={fact.current ?? ''} onValueChange={(effort) => send({ type: 'setEffort', effort })}>
          {fact.available.map((effort) => (
            <DropdownMenuRadioItem key={effort} value={effort}>
              {label(effort)}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
```

Run: `pnpm typecheck && pnpm test` → clean; PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ui webview test/webview
git commit -m "feat(webview): effort picker, steer and edit queued messages, drafts per chat, prompt history"
```

---

### Task 4: Live checks, preview, hand-off

**Files:**
- Create: `scripts/smoke-steer.ts`
- Modify: `esbuild.mjs`, `webview/preview/scenario.ts`

- [ ] **Step 1: Steering live**

`scripts/smoke-steer.ts`:

```ts
// Live check: a queued message steered into a running turn reaches the agent within that same turn; effort can be set.
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { captureEnv } from '../src/env'
import { providers } from '../src/providers/registry'
import { SessionManager } from '../src/sessions/manager'
import { SessionStore } from '../src/sessions/store'
import { MemoryMemento } from '../test/memory-memento'

async function main(): Promise<void> {
  const providerId = process.argv[2] ?? 'codex'
  const cwd = mkdtempSync(join(tmpdir(), 'agentdeck-steer-'))
  const env = await captureEnv()
  const manager = new SessionManager({ providers, store: new SessionStore(new MemoryMemento()), journalDir: join(cwd, '.journal'), cwd, env: async () => env })
  const { id } = await manager.create(providerId, 'full-access')
  let turns = 0
  let reply = ''
  let queuedId: string | undefined
  let effort: { current?: string; available: string[] } | undefined
  const done = new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timed out')), 240_000)
    manager.subscribe(id, (event) => {
      if (event.type === 'fact' && event.fact.kind === 'effort') effort = event.fact
      if (event.type === 'queue' && event.queue[0]) queuedId = event.queue[0].id
      if (event.type !== 'item') return
      if (event.item.kind === 'message' && event.item.role === 'assistant') reply = event.item.text
      if (event.item.kind === 'tool' && event.item.status === 'running' && queuedId) {
        const steering = queuedId
        queuedId = undefined
        void manager.steer(id, steering)
      }
      if (event.item.kind === 'turn' && event.item.state === 'ended') {
        turns++
        clearTimeout(timer)
        resolve()
      }
    })
  })
  await manager.warm(id)
  await new Promise((resolve) => setTimeout(resolve, 3000))
  console.log('effort levels:', effort?.available.join(', ') || '(none)')
  if (effort?.available.length) await manager.setEffort(id, effort.available[0])
  await manager.prompt(id, [{ type: 'text', text: 'Run the shell command `sleep 8 && echo done`, then reply with one line.' }])
  await manager.prompt(id, [{ type: 'text', text: 'Also: end your reply with the word PINEAPPLE.' }])
  await done
  await new Promise((resolve) => setTimeout(resolve, 2000))
  console.log(`turns ended: ${turns} · reply: ${reply.replaceAll('\n', ' ').slice(0, 160)}`)
  await manager.dispose()
  console.log(/pineapple/i.test(reply) ? 'STEER SMOKE OK' : 'STEER NOT TAKEN IN-TURN')
}

main().catch((error) => {
  console.error('STEER SMOKE FAILED:', error)
  process.exit(1)
})
```

In `esbuild.mjs`, add `'smoke-steer': 'scripts/smoke-steer.ts'` to the extension build's `entryPoints`.

Run: `pnpm build && node dist/smoke-steer.js codex && node dist/smoke-steer.js claude`
Expected: `effort levels: …` lists levels; `STEER SMOKE OK` for each. If Claude prints `STEER NOT TAKEN IN-TURN`, remove `'steer'` from Claude's capabilities (its `steer` method may stay) and report that. If Codex does, report the full output; do not remove its capability without reporting.

- [ ] **Step 2: Preview**

In `webview/preview/scenario.ts`, add to the default chat's snapshot record facts an effort fact `effort: { kind: 'effort', current: 'high', available: ['low', 'medium', 'high', 'xhigh'] }` (inside `record.facts` or wherever the scenario sets facts), and add `'steer'` and `'effort'` to the `claude` provider info's `capabilities`.

Run: `pnpm build:preview && pnpm screenshot dark 900x1100 panel chat && pnpm screenshot dark 340x1100 view chat`
Open both: the effort picker (lightbulb, "High" at 900 px) sits after the model picker; the queued message row shows *Steer*, an edit pencil, and ×; nothing overflows at 340 px. Fix layout only in the new components.

- [ ] **Step 3: Package, docs, commit**

Run: `pnpm test && pnpm run package` → PASS; packaged.

In `docs/superpowers/plans/2026-10-28-mvp-overview.md`, add a row for plan 12 (`| 12 | [Turn controls](2026-10-29-12-turn-controls.md) | Reasoning effort, steering, queue editing and merging, drafts per chat, prompt history | Done |`). In `docs/roadmap.md`, mark the table rows *Reasoning effort, live*, *Queue: edit, remove, merge further typing; Steer*, and *Drafts kept per chat; prompt history* ✓ (write which providers steer, e.g. "✓ (steer: Codex, Claude)"), and end the line starting `- **12 — Turn controls:**` with ` ✓ done.`

```bash
git add scripts/smoke-steer.ts esbuild.mjs webview/preview src docs
git commit -m "test: live steering check; plan 12 done"
```
