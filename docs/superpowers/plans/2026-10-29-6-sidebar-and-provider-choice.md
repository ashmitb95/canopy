# Plan 6: Sidebar layout and in-app provider choice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first. The MVP plans 1–5 are complete.

**Goal:** Fix the chat at sidebar width and move provider choice into the chat UI. Today, at ~340 px the composer toolbar pushes the context meter and the Send/Stop button out of view, the model label falls back to a raw id (`claude-sonnet-4-6`), and starting a chat opens a VS Code quick pick to choose Claude or Codex.

**Architecture:** A surface without a session shows an in-app provider chooser (cards with each provider's sign-in state), fed by a new `providers` host message. *New chat* commands open that chooser (a blank editor tab or the cleared sidebar) instead of a quick pick, and a blank tab adopts the session started from it. The composer becomes a CSS container; its toolbar collapses labels below set widths and keeps the action button fixed. The model picker matches the CLI's resolved model id to the alias it came from.

**Tech Stack:** as before; Tailwind v4 container queries (`@container`, `@[26rem]:`).

**Found while planning** (2026-10-29): the user's screenshot of the sidebar; a 340 px preview screenshot reproduces the clipped toolbar. Claude's `supportedModels()` returns aliases (`default`, `opus`, `sonnet`, …) with a `resolvedModel` (`claude-opus-5-5`); the init message reports the resolved id, so the picker must match on both.

---

## File structure

| File | Change |
|---|---|
| `src/core/types.ts` | `ModelOption.resolved` |
| `src/providers/claude/provider.ts` | Pass `resolvedModel` through |
| `src/ui/protocol.ts` | `providers` host message; `providerId` on `newChat` and `signIn` |
| `webview/app/state.ts` | `providers` in state |
| `src/ui/chat-surfaces.ts` | Blank tabs, provider list, start-in-place, no quick pick |
| `webview/app/components/empty-state.tsx` | Provider chooser (full replacement) |
| `webview/app/components/session-switcher.tsx` | *New ‹provider› chat* items |
| `webview/app/components/{composer,model-picker,mode-picker,context-meter,chat-header}.tsx` | Narrow layout |
| `webview/app/App.tsx` | Pass providers to the chooser |
| `webview/preview/scenario.ts`, `scripts/screenshot.mjs` | Provider list; a `new` scenario |

---

### Task 1: Provider list in the protocol and state; model aliases

**Files:**
- Modify: `src/core/types.ts`, `src/providers/claude/provider.ts`, `src/ui/protocol.ts`, `webview/app/state.ts`, `webview/app/components/model-picker.tsx`
- Test: `test/webview/state.test.ts` (one test added)

- [ ] **Step 1: Write the failing test**

In `test/webview/state.test.ts`, add inside the `describe` block:

```ts
  it('keeps the provider list for the chooser, also across an empty surface', () => {
    const providers = [
      {
        id: 'codex',
        label: 'Codex',
        installUrl: 'u',
        capabilities: [],
        modes: ['ask' as const],
        state: { status: 'signed-out' as const }
      }
    ]
    const state = run({ type: 'providers', providers }, { type: 'empty' })
    expect(state.providers).toEqual(providers)
  })
```

Run: `pnpm test test/webview/state.test.ts`
Expected: FAIL (`state.providers` is undefined).

- [ ] **Step 2: Protocol**

In `src/ui/protocol.ts`:
- add to `HostMessage`:

```ts
  /** Every provider with its install and sign-in state, for the chooser. */
  | { type: 'providers'; providers: ProviderInfo[] }
```

- change `| { type: 'newChat' }` to `| { type: 'newChat'; providerId?: string }` and `| { type: 'signIn' }` to `| { type: 'signIn'; providerId?: string }`.

- [ ] **Step 3: State**

In `webview/app/state.ts`:
- add `providers: ProviderInfo[]` to `ChatState` (after `provider?: ProviderInfo`) and `providers: []` to `initialState`;
- add before `case 'session':`

```ts
    case 'providers':
      return { ...state, providers: message.providers }
```

- in the `'empty'` case, also keep `providers: state.providers`.

Run: `pnpm test`
Expected: PASS.

- [ ] **Step 4: Model aliases**

In `src/core/types.ts`, change the `ModelOption` line to:

```ts
export type ModelOption = { id: string; label: string; description?: string; resolved?: string }
```

(keep its doc comment, and extend it with: "`resolved` is the concrete model id an alias such as `opus` maps to.")

In `src/providers/claude/provider.ts`, change

```ts
      this.models = models.map((model) => ({ id: model.value, label: model.displayName, description: model.description }))
```

to

```ts
      this.models = models.map((model) => ({
        id: model.value,
        label: model.displayName,
        description: model.description,
        resolved: model.resolvedModel
      }))
```

In `webview/app/components/model-picker.tsx`, replace the line `const label = fact.available.find((model) => model.id === fact.current)?.label ?? fact.current` with:

```tsx
  // The CLI reports the concrete model id; the picker lists aliases that resolve to it.
  const selected =
    fact.available.find((model) => model.id === fact.current) ??
    fact.available.find((model) => model.resolved === fact.current)
  const label = selected?.label ?? fact.current
```

and change the radio group's `value={fact.current}` to `value={selected?.id ?? fact.current}`.

- [ ] **Step 5: Verify and commit**

Run: `pnpm test && pnpm typecheck`
Expected: PASS; typecheck errors only in `src/ui/chat-surfaces.ts` and `webview/app/App.tsx` are acceptable if they concern `newChat`/`signIn`/`EmptyState` props (Tasks 2–3 fix them). Any other error: stop and report.

```bash
git add src/core/types.ts src/providers/claude/provider.ts src/ui/protocol.ts webview/app/state.ts webview/app/components/model-picker.tsx test/webview/state.test.ts
git commit -m "feat: send the provider list to chats and match model aliases to resolved ids"
```

---

### Task 2: Host — blank tabs and starting a chat in place

**Files:**
- Modify: `src/ui/chat-surfaces.ts`

- [ ] **Step 1: Track blank tabs**

In `src/ui/chat-surfaces.ts`:
- add `panel?: vscode.WebviewPanel` to the `Surface` type (after `kind`);
- add a field after `private sidebar: Surface | undefined`:

```ts
  /** Editor tabs showing the provider chooser, before a session exists. */
  private readonly blankPanels = new Set<Surface>()
```

- [ ] **Step 2: Replace `newChat` and remove the quick pick**

Replace the `newChat` method and delete the `pickProvider` method entirely, with:

```ts
  /** Starts a chat with a provider, or shows the in-app provider chooser when none is given. */
  async newChat(where: SurfaceKind, providerId?: string): Promise<void> {
    if (providerId) {
      const record = await this.manager.create(providerId)
      if (where === 'panel') this.openPanel(record.id)
      else await this.showInSidebar(record.id)
      return
    }
    if (where === 'panel') return this.openBlankPanel()
    await this.context.workspaceState.update(SIDEBAR_SESSION_KEY, undefined)
    await vscode.commands.executeCommand(`${SIDEBAR_VIEW}.focus`)
    if (this.sidebar) this.clear(this.sidebar)
  }

  private openBlankPanel(): void {
    const panel = vscode.window.createWebviewPanel(PANEL_TYPE, 'New chat', vscode.ViewColumn.Beside, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [this.assets()]
    })
    this.attachPanel(panel)
  }

  private clear(surface: Surface): void {
    surface.subscription?.dispose()
    surface.subscription = undefined
    surface.sessionId = undefined
    this.post(surface, { type: 'empty' })
  }

  /** A chat started from a surface's chooser opens in that surface. */
  private async startIn(surface: Surface, providerId: string): Promise<void> {
    const record = await this.manager.create(providerId)
    if (surface.kind === 'view') return this.showInSidebar(record.id)
    if (surface.sessionId || !surface.panel) return this.openPanel(record.id)
    this.blankPanels.delete(surface)
    this.panels.set(record.id, { panel: surface.panel, surface })
    surface.panel.title = this.title(record.id)
    this.show(surface, record.id)
  }
```

- [ ] **Step 3: Panels may start blank**

Replace `attachPanel` with:

```ts
  private attachPanel(panel: vscode.WebviewPanel, sessionId?: string): void {
    panel.webview.options = { enableScripts: true, localResourceRoots: [this.assets()] }
    panel.webview.html = this.html(panel.webview, 'panel')
    panel.title = sessionId ? this.title(sessionId) : 'New chat'
    const surface = this.surface(panel.webview, 'panel', sessionId)
    surface.panel = panel
    if (sessionId) this.panels.set(sessionId, { panel, surface })
    else this.blankPanels.add(surface)
    panel.onDidDispose(() => {
      this.release(surface)
      if (surface.sessionId) this.panels.delete(surface.sessionId)
      this.blankPanels.delete(surface)
    })
  }
```

- [ ] **Step 4: Provider info for every surface**

Replace the `postProvider` method with these three methods:

```ts
  private async postProvider(surface: Surface): Promise<void> {
    const provider = this.providers.get(this.providerOf(surface.sessionId))
    if (provider) this.post(surface, { type: 'provider', provider: await this.info(provider) })
  }

  /** The chooser lists every provider; sent on ready and after a sign-in. */
  private async postProviders(target?: Surface): Promise<void> {
    const providers = await Promise.all([...this.providers.values()].map((provider) => this.info(provider)))
    if (target) this.post(target, { type: 'providers', providers })
    else this.broadcast({ type: 'providers', providers })
  }

  private async info(provider: ProviderDefinition): Promise<ProviderInfo> {
    const state = this.states.get(provider.id) ?? (await this.probe(provider))
    return {
      id: provider.id,
      label: provider.label,
      installUrl: provider.cli.installUrl,
      capabilities: [...provider.capabilities],
      modes: provider.modes,
      state
    }
  }
```

and change the protocol type import at the top to `import type { HostMessage, ProviderInfo, WebviewMessage } from './protocol'`.

- [ ] **Step 5: Route the messages**

In `handle`:
- replace the whole `'ready'` case with:

```ts
      case 'ready':
        this.post(surface, { type: 'editorContext', context: this.editor.current() })
        this.postSessions(surface)
        await this.postProviders(surface)
        if (sessionId) this.show(surface, sessionId)
        else this.post(surface, { type: 'empty' })
        return
```

- replace the `'newChat'` and `'signIn'` cases with:

```ts
      case 'newChat':
        if (message.providerId) return this.startIn(surface, message.providerId)
        return this.newChat(surface.kind)
      case 'signIn':
        return this.signIn(surface, message.providerId)
```

- [ ] **Step 6: Show sends the session's provider**

In `show`, add as its last line (switching the sidebar between a Claude and a Codex chat must update the provider shown):

```ts
    void this.postProvider(surface)
```

- [ ] **Step 7: Sign-in for a chosen provider**

Change `signIn`'s signature and first line to:

```ts
  private async signIn(surface: Surface, providerId?: string): Promise<void> {
    const provider = this.providers.get(providerId ?? this.providerOf(surface.sessionId))
```

and replace the two lines inside the terminal-closed handler after `closed.dispose()` with:

```ts
      this.states.delete(provider.id)
      void this.postProviders()
      if (surface.sessionId) void this.postProvider(surface)
```

- [ ] **Step 8: Prompts from a surface without a session**

Replace `createFor` with (the chooser normally prevents this; a prompt can still arrive from a stale webview):

```ts
  private async createFor(surface: Surface): Promise<string> {
    await this.startIn(surface, DEFAULT_PROVIDER)
    if (!surface.sessionId) throw new Error('Could not start a chat.')
    return surface.sessionId
  }
```

- [ ] **Step 9: Broadcast to blank tabs too**

In `broadcast`, add `for (const surface of this.blankPanels) this.post(surface, message)` after the panels loop. In `dispose`, add `for (const surface of this.blankPanels) this.release(surface)`.

- [ ] **Step 10: Verify and commit**

Run: `pnpm typecheck`
Expected: errors only in `webview/app/App.tsx` (the `EmptyState` props, fixed in Task 3).

```bash
git add src/ui/chat-surfaces.ts
git commit -m "feat(ui): start chats from an in-app chooser; blank tabs adopt their first session"
```

---

### Task 3: Webview — provider chooser and switcher

**Files:**
- Modify: `webview/app/components/empty-state.tsx` (full replacement), `webview/app/components/session-switcher.tsx`, `webview/app/App.tsx`

- [ ] **Step 1: The chooser**

`webview/app/components/empty-state.tsx`:

```tsx
import { Shimmer } from '@/components/ai-elements/shimmer'
import { Button } from '@/components/ui/button'
import type { ProviderInfo } from '../../../src/ui/protocol'
import { send } from '../host'
import { Codicon } from './codicon'
import { ProviderAvatar } from './provider-avatar'

/** Shown by a tab or the sidebar before a chat exists: pick who to work with. */
export function EmptyState({ providers }: { providers: ProviderInfo[] }) {
  return (
    <div className="flex h-screen flex-col justify-center gap-4 p-4">
      <div className="text-center">
        <div className="font-semibold">Start a chat</div>
        <div className="text-xs text-muted-foreground">Each agent runs through its own CLI and sign-in.</div>
      </div>
      {providers.length === 0 ? (
        <Shimmer as="div" className="text-center text-xs">
          Checking providers…
        </Shimmer>
      ) : (
        <div className="mx-auto flex w-full max-w-sm flex-col gap-2">
          {providers.map((provider) => (
            <ProviderCard key={provider.id} provider={provider} />
          ))}
        </div>
      )}
    </div>
  )
}

function ProviderCard({ provider }: { provider: ProviderInfo }) {
  const { status, account, version } = provider.state
  const detail =
    status === 'signed-in'
      ? [account, version && `v${version}`].filter(Boolean).join(' · ') || 'Signed in'
      : status === 'signed-out'
        ? 'Signed out'
        : status === 'not-installed'
          ? 'Not installed'
          : 'Status unknown'
  const body = (
    <>
      <ProviderAvatar providerId={provider.id} />
      <div className="min-w-0 flex-1 text-left">
        <div className="font-medium">{provider.label}</div>
        <div className="truncate text-xs text-muted-foreground">{detail}</div>
      </div>
    </>
  )
  if (status === 'signed-in' || status === 'unknown') {
    return (
      <button
        type="button"
        className="flex items-center gap-3 rounded-lg border px-3 py-2.5 hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring"
        onClick={() => send({ type: 'newChat', providerId: provider.id })}
      >
        {body}
        <Codicon name="arrow-right" className="text-muted-foreground" />
      </button>
    )
  }
  return (
    <div className="flex items-center gap-3 rounded-lg border px-3 py-2.5">
      {body}
      {status === 'signed-out' ? (
        <Button size="xs" variant="secondary" onClick={() => send({ type: 'signIn', providerId: provider.id })}>
          Sign in
        </Button>
      ) : (
        <Button size="xs" variant="secondary" asChild>
          <a href={provider.installUrl}>Install</a>
        </Button>
      )}
    </div>
  )
}
```

- [ ] **Step 2: App passes the providers**

In `webview/app/App.tsx`, change `if (state.empty) return <EmptyState provider={state.provider} />` to:

```tsx
  if (state.empty) return <EmptyState providers={state.providers} />
```

- [ ] **Step 3: Switcher offers each provider**

In `webview/app/components/session-switcher.tsx`, replace the single *New chat* `DropdownMenuItem` with:

```tsx
        {state.providers
          .filter((provider) => provider.state.status !== 'not-installed')
          .map((provider) => (
            <DropdownMenuItem key={provider.id} onSelect={() => send({ type: 'newChat', providerId: provider.id })}>
              <ProviderAvatar providerId={provider.id} className="size-5 text-[10px]" />
              New {provider.label} chat
            </DropdownMenuItem>
          ))}
```

- [ ] **Step 4: Verify and commit**

Run: `pnpm typecheck && pnpm test`
Expected: clean; PASS.

```bash
git add webview/app
git commit -m "feat(webview): choose the provider in the chat UI"
```

---

### Task 4: Narrow layout

**Files:**
- Modify: `webview/app/components/{composer,model-picker,mode-picker,context-meter,chat-header}.tsx`

- [ ] **Step 1: The composer is a container; the action button never leaves**

In `webview/app/components/composer.tsx`:
- add `@container` to the root `div`'s class list: `className="@container rounded-xl border bg-input/40 focus-within:border-ring"`;
- replace the toolbar (the `div` with `className="flex items-center gap-1 px-2 pb-2"` and everything inside it) with:

```tsx
      <div className="flex items-center gap-1 px-2 pb-2">
        <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-hidden">
          <ModelPicker fact={state.facts.model?.kind === 'model' ? state.facts.model : undefined} />
          <ModePicker
            current={state.facts.mode?.kind === 'mode' ? state.facts.mode.current : (state.record?.mode ?? 'ask')}
            available={state.provider?.modes ?? []}
          />
          <McpPopover fact={state.facts.mcp?.kind === 'mcp' ? state.facts.mcp : undefined} />
        </div>
        <ContextMeter fact={state.facts.context?.kind === 'context' ? state.facts.context : undefined} />
        {busy ? (
          <Button
            key="stop"
            size="icon-sm"
            variant="secondary"
            className="shrink-0"
            aria-label="Stop"
            onClick={() => send({ type: 'cancel' })}
          >
            <Codicon name="debug-stop" />
          </Button>
        ) : (
          <Button key="send" size="icon-sm" className="shrink-0" aria-label="Send" disabled={!text.trim()} onClick={submit}>
            <Codicon name="send" />
          </Button>
        )}
      </div>
```

- [ ] **Step 2: Labels collapse with the composer's width**

In `webview/app/components/model-picker.tsx`, give the trigger button `className="min-w-0 shrink text-muted-foreground"` and wrap the label: replace `{label}` inside the trigger with `<span className="truncate">{label}</span>`.

In `webview/app/components/mode-picker.tsx`, replace `{MODES[current].label}` inside the trigger (the first occurrence, in `DropdownMenuTrigger`, not the menu items) with:

```tsx
          <span className="hidden @[26rem]:inline">{MODES[current].label}</span>
```

and add `title={MODES[current].label}` to that trigger `Button`, so the icon alone still has a name.

In `webview/app/components/context-meter.tsx`, replace `{Math.round(ratio * 100)}%` with:

```tsx
          <span className="hidden @[20rem]:inline">{Math.round(ratio * 100)}%</span>
```

- [ ] **Step 3: A tighter header in the sidebar**

In `webview/app/components/chat-header.tsx`, replace the component body with:

```tsx
  if (!state.record) return null
  const compact = document.body.dataset.surface === 'view'
  return (
    <header className={compact ? 'flex items-center gap-2 border-b px-3 py-1.5' : 'flex items-center gap-2.5 border-b px-4 py-2.5'}>
      <ProviderAvatar providerId={state.record.providerId} className={compact ? 'size-6 text-[11px]' : undefined} />
      <div className="min-w-0 flex-1">
        <div className={compact ? 'truncate text-sm font-semibold' : 'truncate font-semibold'}>{state.record.title}</div>
        {!compact && (
          <div className="truncate text-xs text-muted-foreground">{state.provider?.label ?? state.record.providerId}</div>
        )}
      </div>
      <StatusBadge status={state.status} />
      {compact && <SessionSwitcher state={state} />}
    </header>
  )
```

- [ ] **Step 4: Verify and commit**

Run: `pnpm typecheck && pnpm test`
Expected: clean; PASS.

```bash
git add webview/app/components
git commit -m "fix(webview): keep the composer usable at sidebar width"
```

---

### Task 5: Preview the chooser and the narrow layout

**Files:**
- Modify: `webview/preview/scenario.ts`, `scripts/screenshot.mjs`

- [ ] **Step 1: Provider list and a `new` scenario**

In `webview/preview/scenario.ts`, replace everything from `const messages: HostMessage[] = [` to the end of the file with:

```ts
const claude: ProviderInfo = {
  id: 'claude',
  label: 'Claude',
  installUrl: 'https://example.invalid',
  capabilities: [],
  modes: ['ask', 'accept-edits', 'plan', 'full-access'],
  state: { status: 'signed-in', account: 'me@example.com', version: '2.1.311' }
}
const codex: ProviderInfo = { ...claude, id: 'codex', label: 'Codex', state: { status: 'signed-out' } }
const providers: HostMessage = { type: 'providers', providers: [claude, codex] }

const chat: HostMessage[] = [
  providers,
  {
    type: 'sessions',
    sessions: [
      { id: 's1', title: 'Fix flaky retry test', providerId: 'claude', status: 'needs-input', updatedAt: '2026-10-28T10:04:00.000Z' },
      { id: 's2', title: 'Refactor auth middleware', providerId: 'claude', status: 'idle', updatedAt: '2026-10-28T09:00:00.000Z' }
    ]
  },
  { type: 'provider', provider: claude },
  { type: 'editorContext', context: { path: '/work/src/api.test.ts', label: 'src/api.test.ts', range: [40, 72] } },
  {
    type: 'session',
    sessionId: 's1',
    event: {
      type: 'snapshot',
      record,
      status: 'needs-input',
      items,
      queue: [{ id: 'q1', parts: [{ type: 'text', text: 'Also add a regression test that runs the retry with real timers.' }] }]
    }
  }
]

// `?scenario=new` shows the provider chooser instead of a chat.
const messages: HostMessage[] = new URLSearchParams(location.search).get('scenario') === 'new' ? [providers, { type: 'empty' }] : chat

// Posted after the app has mounted and subscribed.
setTimeout(() => {
  for (const message of messages) window.postMessage(message, '*')
}, 100)
```

and change the protocol import at the top to `import type { HostMessage, ProviderInfo } from '../../src/ui/protocol'`.

- [ ] **Step 2: Screenshot a scenario**

In `scripts/screenshot.mjs`:
- change the argument line to `const [theme = 'dark', size = '900x1200', surface = 'panel', scenario = 'chat'] = process.argv.slice(2)`;
- change the output path to ``resolve(`dist/preview/screenshot-${theme}-${surface}${scenario === 'chat' ? '' : `-${scenario}`}.png`)``;
- append `&scenario=${scenario}` to the URL.

- [ ] **Step 3: Review**

Run:

```bash
pnpm build:preview && pnpm screenshot dark 340x900 view && pnpm screenshot dark 340x700 view new && pnpm screenshot light 900x1200 panel && pnpm screenshot dark 900x700 panel new
```

Expected, checked by opening each PNG:
- `screenshot-dark-view.png` (340 px): the header is one compact row (small avatar, title, *Input*, history button); the composer toolbar shows the model label (truncated if needed), the mode icon without its label, *MCP 1*, the context ring, and the Stop button fully inside the composer's border. Nothing overflows the right edge.
- `screenshot-dark-view-new.png`: "Start a chat", a Claude card (`me@example.com · v2.1.311`, arrow) and a Codex card (*Signed out*, *Sign in* button), all within 340 px.
- `screenshot-light-panel.png` (900 px): the toolbar shows *Ask before edits* with its label and the `38%` text, as before.
- `screenshot-dark-panel-new.png`: the chooser centered in a wide tab.

Any element overflowing or clipped is a defect to fix in the components this plan touched.

- [ ] **Step 4: Package and commit**

Run: `pnpm typecheck && pnpm test && pnpm run package`
Expected: clean; PASS; packaged.

```bash
git add webview/preview scripts/screenshot.mjs
git commit -m "test(webview): preview the provider chooser and the sidebar width"
```

- [ ] **Step 5: Hand off**

Ask the user to reinstall (`code --install-extension agentdeck-0.1.0.vsix --force`), reload, and check: the sidebar's *New chat* button shows the chooser in the sidebar; *AgentDeck: New Chat in Editor* opens a tab with the chooser, and picking a provider starts the chat in that tab; the sidebar composer keeps its Send/Stop button visible at their sidebar width; the model picker shows a name, not a raw id.
