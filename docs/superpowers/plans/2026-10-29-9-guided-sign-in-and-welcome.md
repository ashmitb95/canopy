# Plan 9: Guided sign-in and the welcome screen — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first. Plans 1–8 are complete.

**Goal:** Sign in to each provider from inside AgentDeck, as in mockups `1-first-run.html` and `3-providers-sign-in.html`: a three-step progress view (start → approve in your browser → confirm), the sign-in link opened for you with *Copy sign-in link* as a fallback, a device code where the provider uses one, and *Cancel*. The provider chooser becomes the welcome screen ("Your agents, one chat", "2 of 3 providers ready") and opens once on first run; *AgentDeck: Manage Providers* opens it any time, with *Refresh*.

**Architecture:** A provider may implement `startSignIn(env, onEvent)`: it runs the provider's own login and reports `link` (URL, optional code), `done`, or `failed`. The CLI completes the OAuth and keeps the token; AgentDeck only sees and opens the link. Claude's login hands its link to `$BROWSER`, so a tiny helper script writes it to a file AgentDeck polls (Orca's technique). Codex's app-server has `account/login/start`, which returns the link and later sends `account/login/completed`. Grok's `grok login` prints a device link with the code in it. `ChatSurfaces` runs one flow per provider and broadcasts progress; the chooser's provider cards render the stepper. Providers without `startSignIn` keep the terminal sign-in.

**Tech Stack:** as before.

**Verified before writing** (2026-10-29):
- Orca's `claude-sign-in-browser.ts`: helper script `#!/bin/sh\nprintf '%s' "$1" > "$0.tmp" && mv "$0.tmp" "$0.link"`; Claude discards the helper's stdout; the link is an `https://claude.ai|claude.com/…` URL whose `redirect_uri` is `http://localhost|127.0.0.1…`; Orca runs `claude auth login --claudeai` with stdin kept open.
- Codex 0.165 schema: `account/login/start { type: 'chatgpt' }` → `{ type: 'chatgpt', loginId, authUrl }`; `account/login/completed { loginId, success, error }`; `account/login/cancel { loginId }`.
- `grok login` output (the user's own run): `https://accounts.x.ai/oauth2/device?user_code=KWMT-AT8W`, then `✓ Signed in as …`, exit 0.

---

## File structure

| File | Responsibility |
|---|---|
| `src/core/types.ts` | `SignInEvent`, `SignInFlow`, `ProviderDefinition.startSignIn` |
| `src/providers/sign-in.ts` | Run a login CLI and report its link; parse device links; validate Claude's link |
| `src/providers/{claude,codex,acp}/…` | Each provider's `startSignIn` |
| `src/ui/protocol.ts`, `webview/app/state.ts` | Sign-in progress; refresh |
| `src/ui/chat-surfaces.ts`, `src/extension.ts`, `package.json` | Run flows, welcome on first run, *Manage Providers* |
| `webview/app/components/empty-state.tsx` | Welcome hero, provider cards with the stepper |
| `webview/preview/scenario.ts` | A sign-in in progress |

---

### Task 1: Sign-in building blocks

**Files:**
- Modify: `src/core/types.ts`
- Create: `src/providers/sign-in.ts`
- Test: `test/providers/sign-in.test.ts`

- [ ] **Step 1: Types**

In `src/core/types.ts`, add before `export interface ProviderDefinition`:

```ts
/** Progress of a provider's own login. The CLI completes the OAuth and keeps the token. */
export type SignInEvent = { kind: 'link'; url: string; code?: string } | { kind: 'done' } | { kind: 'failed'; message: string }

export type SignInFlow = { cancel(): void }
```

and add to `ProviderDefinition`, after `signInCommand`:

```ts
  /** Runs the login inside AgentDeck, reporting the link to open; without it, sign-in runs in a terminal. */
  startSignIn?(env: Env, onEvent: (event: SignInEvent) => void): Promise<SignInFlow>
```

- [ ] **Step 2: Write the failing tests**

`test/providers/sign-in.test.ts`:

```ts
import { chmodSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { SignInEvent } from '../../src/core/types'
import { deviceLink, isClaudeSignInLink, runLoginCli } from '../../src/providers/sign-in'

function script(body: string): string {
  const path = join(mkdtempSync(join(tmpdir(), 'agentdeck-login-')), 'login')
  writeFileSync(path, `#!/bin/sh\n${body}\n`)
  chmodSync(path, 0o755)
  return path
}

function collect(run: (onEvent: (event: SignInEvent) => void) => void): Promise<SignInEvent[]> {
  return new Promise((resolve) => {
    const events: SignInEvent[] = []
    run((event) => {
      events.push(event)
      if (event.kind !== 'link') resolve(events)
    })
  })
}

describe('deviceLink', () => {
  it('finds the link and the code it carries', () => {
    const output = 'To sign in, open this URL in your browser:\n\n  https://accounts.x.ai/oauth2/device?user_code=KWMT-AT8W\n\nWaiting…'
    expect(deviceLink(output)).toEqual({ url: 'https://accounts.x.ai/oauth2/device?user_code=KWMT-AT8W', code: 'KWMT-AT8W' })
  })

  it('returns a link without a code, and null without a link', () => {
    expect(deviceLink('Open https://example.com/login now')).toEqual({ url: 'https://example.com/login' })
    expect(deviceLink('Starting…')).toBeNull()
  })
})

describe('isClaudeSignInLink', () => {
  it('accepts claude.ai links that call back to localhost', () => {
    expect(isClaudeSignInLink('https://claude.ai/oauth/authorize?redirect_uri=http%3A%2F%2Flocalhost%3A54545%2Fcallback')).toBe(true)
    expect(isClaudeSignInLink('https://claude.com/oauth/authorize?redirect_uri=http%3A%2F%2F127.0.0.1%3A5%2Fcb')).toBe(true)
  })

  it('rejects other hosts and redirects', () => {
    expect(isClaudeSignInLink('https://evil.example/oauth?redirect_uri=http%3A%2F%2Flocalhost%2F')).toBe(false)
    expect(isClaudeSignInLink('https://claude.ai/oauth/authorize?redirect_uri=https%3A%2F%2Fevil.example%2F')).toBe(false)
    expect(isClaudeSignInLink('not a url')).toBe(false)
  })
})

describe.skipIf(process.platform === 'win32')('runLoginCli', () => {
  it('reports the link, then success', async () => {
    const cli = script('echo "open https://accounts.x.ai/oauth2/device?user_code=AB12-CD34"; sleep 0.2; echo "Signed in"')
    const events = await collect((onEvent) => runLoginCli(cli, [], {}, onEvent, deviceLink))
    expect(events).toEqual([
      { kind: 'link', url: 'https://accounts.x.ai/oauth2/device?user_code=AB12-CD34', code: 'AB12-CD34' },
      { kind: 'done' }
    ])
  })

  it('reports failure with the last output lines', async () => {
    const cli = script('echo "network unreachable" >&2; exit 2')
    const events = await collect((onEvent) => runLoginCli(cli, [], {}, onEvent, deviceLink))
    expect(events).toEqual([{ kind: 'failed', message: 'network unreachable' }])
  })

  it('reports nothing after cancel', async () => {
    const cli = script('sleep 5')
    const events: SignInEvent[] = []
    const flow = runLoginCli(cli, [], {}, (event) => events.push(event), deviceLink)
    flow.cancel()
    await new Promise((resolve) => setTimeout(resolve, 300))
    expect(events).toEqual([])
  })
})
```

Run: `pnpm test test/providers/sign-in.test.ts` → FAIL (cannot resolve `sign-in`).

- [ ] **Step 3: Implement**

`src/providers/sign-in.ts`:

```ts
import type { SignInEvent, SignInFlow } from '../core/types'
import type { Env } from '../env'
import { spawnGroup, stopGroup } from '../process'

const OUTPUT_TAIL = 20_000
const CLAUDE_HOSTS = new Set(['claude.ai', 'claude.com'])
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1'])

/** Runs a CLI's own login and reports the link it offers; the CLI keeps the credentials. */
export function runLoginCli(
  command: string,
  args: string[],
  env: Env,
  onEvent: (event: SignInEvent) => void,
  findLink: (output: string) => { url: string; code?: string } | null
): SignInFlow {
  // stdin stays open: some logins wait on it while the browser step runs.
  const child = spawnGroup(command, args, { env, stdio: ['pipe', 'pipe', 'pipe'] })
  let output = ''
  let linked = false
  let settled = false
  const scan = (chunk: string) => {
    output = (output + chunk).slice(-OUTPUT_TAIL)
    if (linked) return
    const link = findLink(output)
    if (!link) return
    linked = true
    onEvent({ kind: 'link', ...link })
  }
  child.stdout?.setEncoding('utf8').on('data', scan)
  child.stderr?.setEncoding('utf8').on('data', scan)
  const settle = (event: SignInEvent) => {
    if (settled) return
    settled = true
    onEvent(event)
  }
  child.on('error', (error) => settle({ kind: 'failed', message: error.message }))
  child.on('exit', (code) =>
    settle(code === 0 ? { kind: 'done' } : { kind: 'failed', message: lastLines(output) || `Sign-in exited with ${code}.` })
  )
  return {
    cancel: () => {
      settled = true
      void stopGroup(child)
    }
  }
}

/** The first https link in a login's output, with the device code it carries, if any. */
export function deviceLink(output: string): { url: string; code?: string } | null {
  const url = output.match(/https:\/\/[^\s"'<>]+/)?.[0]
  if (!url) return null
  const code = new URL(url).searchParams.get('user_code') ?? undefined
  return code ? { url, code } : { url }
}

/** Claude's sign-in link: claude.ai or claude.com, calling back to a local port. */
export function isClaudeSignInLink(link: string): boolean {
  try {
    const url = new URL(link)
    const redirect = new URL(url.searchParams.get('redirect_uri') ?? '')
    return url.protocol === 'https:' && CLAUDE_HOSTS.has(url.hostname) && redirect.protocol === 'http:' && LOCAL_HOSTS.has(redirect.hostname)
  } catch {
    return false
  }
}

function lastLines(output: string): string {
  return output.trim().split('\n').slice(-3).join('\n').trim()
}
```

Run: `pnpm test && pnpm typecheck` → PASS; clean.

- [ ] **Step 4: Commit**

```bash
git add src/core/types.ts src/providers/sign-in.ts test/providers/sign-in.test.ts
git commit -m "feat(providers): add sign-in flow building blocks"
```

---

### Task 2: Each provider's sign-in

**Files:**
- Create: `src/providers/claude/sign-in.ts`, `src/providers/codex/sign-in.ts`
- Modify: `src/providers/claude/provider.ts`, `src/providers/codex/provider.ts`, `src/providers/acp/provider.ts`

These run real logins, so they are verified by typecheck here and by the user in Task 5.

- [ ] **Step 1: Claude**

`src/providers/claude/sign-in.ts`:

```ts
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { SignInEvent, SignInFlow } from '../../core/types'
import type { Env } from '../../env'
import { isClaudeSignInLink, runLoginCli } from '../sign-in'

// Claude hands its sign-in link to $BROWSER and discards the browser's stdout, so the helper writes it to a file.
const HELPER = `#!/bin/sh\nprintf '%s' "$1" > "$0.tmp" && mv "$0.tmp" "$0.link"\n`
const POLL_MS = 250

export function claudeSignIn(cliPath: string, env: Env, onEvent: (event: SignInEvent) => void): SignInFlow {
  const dir = mkdtempSync(join(tmpdir(), 'agentdeck-sign-in-'))
  const helper = join(dir, 'browser')
  writeFileSync(helper, HELPER, { mode: 0o700 })
  const cleanup = () => {
    clearInterval(poll)
    rmSync(dir, { recursive: true, force: true })
  }
  const poll = setInterval(() => {
    let link: string
    try {
      link = readFileSync(`${helper}.link`, 'utf8').trim()
    } catch {
      return
    }
    clearInterval(poll)
    if (isClaudeSignInLink(link)) onEvent({ kind: 'link', url: link })
    else onEvent({ kind: 'failed', message: 'Claude offered an unexpected sign-in link, so AgentDeck did not open it.' })
  }, POLL_MS)
  const flow = runLoginCli(cliPath, ['auth', 'login', '--claudeai'], { ...env, BROWSER: helper }, (event) => {
    if (event.kind !== 'link') cleanup()
    onEvent(event)
  }, () => null)
  return {
    cancel: () => {
      cleanup()
      flow.cancel()
    }
  }
}
```

In `src/providers/claude/provider.ts`, import `claudeSignIn` from `./sign-in`, add `SignInEvent` to the core type import, and add to `claudeProvider` after `signInCommand`:

```ts
  async startSignIn(env: Env, onEvent: (event: SignInEvent) => void) {
    const path = await findClaude(env)
    if (!path) throw new Error('The claude CLI was not found.')
    return claudeSignIn(path, claudeEnv(env), onEvent)
  },
```

- [ ] **Step 2: Codex**

`src/providers/codex/sign-in.ts`:

```ts
import type { SignInEvent, SignInFlow } from '../../core/types'
import type { Env } from '../../env'
import { spawnGroup, stopGroup } from '../../process'
import { RpcPeer } from '../rpc'

/** Codex's app-server runs the ChatGPT login itself and reports the link to open. */
export async function codexSignIn(cliPath: string, env: Env, onEvent: (event: SignInEvent) => void): Promise<SignInFlow> {
  const child = spawnGroup(cliPath, ['app-server'], { env, stdio: ['pipe', 'pipe', 'pipe'] })
  const rpc = new RpcPeer(child.stdout!, child.stdin!)
  let finished = false
  const finish = (event: SignInEvent | undefined) => {
    if (finished) return
    finished = true
    if (event) onEvent(event)
    void stopGroup(child)
  }
  rpc.onNotification(({ method, params }) => {
    if (method !== 'account/login/completed') return
    const { success, error } = params as { success: boolean; error: string | null }
    finish(success ? { kind: 'done' } : { kind: 'failed', message: error ?? 'Sign-in did not complete.' })
  })
  child.on('exit', () => finish({ kind: 'failed', message: 'Codex stopped before sign-in completed.' }))
  try {
    await rpc.request('initialize', {
      clientInfo: { name: 'agentdeck', title: 'AgentDeck', version: '0.1.0' },
      capabilities: { experimentalApi: true, requestAttestation: false }
    })
    rpc.notify('initialized')
    const { loginId, authUrl } = await rpc.request<{ loginId: string; authUrl: string }>('account/login/start', { type: 'chatgpt' })
    onEvent({ kind: 'link', url: authUrl })
    return {
      cancel: () => {
        if (finished) return
        void rpc.request('account/login/cancel', { loginId }).catch(() => undefined).finally(() => finish(undefined))
      }
    }
  } catch (error) {
    finish(undefined)
    throw error
  }
}
```

In `src/providers/codex/provider.ts`, import `codexSignIn` from `./sign-in`, add `SignInEvent` to the core type import, and add to `codexProvider` after `signInCommand`:

```ts
  async startSignIn(env: Env, onEvent: (event: SignInEvent) => void) {
    const path = findCodex(env)
    if (!path) throw new Error('The codex CLI was not found.')
    return codexSignIn(path, env, onEvent)
  },
```

- [ ] **Step 3: ACP agents**

In `src/providers/acp/provider.ts`, import `{ deviceLink, runLoginCli }` from `../sign-in`, add `SignInEvent` to the core type import, and add to the object `acpProvider` returns, after `signInCommand`:

```ts
    async startSignIn(env: Env, onEvent: (event: SignInEvent) => void) {
      const path = findAgentCli(spec, env, home(env))
      if (!path) throw new Error(`The ${spec.command} CLI was not found.`)
      return runLoginCli(path, spec.loginArgs, env, onEvent, deviceLink)
    },
```

- [ ] **Step 4: Verify and commit**

Run: `pnpm typecheck && pnpm test` → clean; PASS.

```bash
git add src/providers
git commit -m "feat(providers): sign in to Claude, Codex, and Grok from AgentDeck"
```

---

### Task 3: Host

**Files:**
- Modify: `src/ui/protocol.ts`, `webview/app/state.ts`, `src/ui/chat-surfaces.ts`, `src/extension.ts`, `package.json`
- Test: `test/webview/state.test.ts` (one test added)

- [ ] **Step 1: Write the failing test**

In `test/webview/state.test.ts`, add:

```ts
  it('tracks sign-in progress per provider and clears it when done', () => {
    const started = run({ type: 'signInProgress', providerId: 'claude', progress: { step: 'link', url: 'https://claude.ai/x' } })
    expect(started.signIns.claude).toEqual({ step: 'link', url: 'https://claude.ai/x' })
    expect(reduce(started, { type: 'signInProgress', providerId: 'claude', progress: null }).signIns).toEqual({})
  })
```

Run: `pnpm test test/webview/state.test.ts` → FAIL.

- [ ] **Step 2: Protocol and state**

In `src/ui/protocol.ts`, add:

```ts
/** Where a sign-in flow is; `null` clears it. */
export type SignInProgress =
  | { step: 'starting' }
  | { step: 'link'; url: string; code?: string }
  | { step: 'failed'; message: string }
```

add to `HostMessage`: `| { type: 'signInProgress'; providerId: string; progress: SignInProgress | null }`, and to `WebviewMessage`: `| { type: 'cancelSignIn'; providerId: string }`, `| { type: 'signInInTerminal'; providerId: string }`, `| { type: 'refreshProviders' }`.

In `webview/app/state.ts`: import `SignInProgress`; add `signIns: Record<string, SignInProgress>` to `ChatState` and `signIns: {}` to `initialState`; keep it in the `'empty'` case; add:

```ts
    case 'signInProgress': {
      const signIns = { ...state.signIns }
      if (message.progress) signIns[message.providerId] = message.progress
      else delete signIns[message.providerId]
      return { ...state, signIns }
    }
```

Run: `pnpm test` → PASS.

- [ ] **Step 3: Run flows in the host**

In `src/ui/chat-surfaces.ts`:
- import `SignInFlow` with the core types and `SignInProgress` with the protocol types;
- add a field: `private readonly signIns = new Map<string, { flow?: SignInFlow; progress: SignInProgress }>()`;
- rename the existing `signIn` method to `signInInTerminal` (body unchanged), and add:

```ts
  /** Runs the provider's login inside AgentDeck when it can; otherwise in a terminal. */
  private async signIn(surface: Surface, providerId?: string): Promise<void> {
    const provider = this.providers.get(providerId ?? this.providerOf(surface.sessionId))
    if (!provider) return
    if (!provider.startSignIn) return this.signInInTerminal(surface, provider.id)
    this.signIns.get(provider.id)?.flow?.cancel()
    this.setSignIn(provider.id, { step: 'starting' })
    try {
      const flow = await provider.startSignIn(await this.env(), (event) => {
        if (event.kind === 'link') {
          void vscode.env.openExternal(vscode.Uri.parse(event.url))
          this.setSignIn(provider.id, { step: 'link', url: event.url, code: event.code })
        } else if (event.kind === 'failed') {
          this.setSignIn(provider.id, { step: 'failed', message: event.message })
        } else {
          this.setSignIn(provider.id, null)
          this.states.delete(provider.id)
          void this.postProviders()
          for (const target of this.surfaces()) if (this.providerOf(target.sessionId) === provider.id) void this.postProvider(target)
        }
      })
      const current = this.signIns.get(provider.id)
      if (current) current.flow = flow
    } catch (error) {
      this.setSignIn(provider.id, { step: 'failed', message: error instanceof Error ? error.message : String(error) })
    }
  }

  private setSignIn(providerId: string, progress: SignInProgress | null): void {
    if (progress) this.signIns.set(providerId, { flow: this.signIns.get(providerId)?.flow, progress })
    else this.signIns.delete(providerId)
    this.broadcast({ type: 'signInProgress', providerId, progress })
  }

  private surfaces(): Surface[] {
    return [...[...this.panels.values()].map(({ surface }) => surface), ...this.blankPanels, ...(this.sidebar ? [this.sidebar] : [])]
  }
```

  (The callback must not reference `flow`: Codex reports its link before `startSignIn` resolves. The flow is attached to the entry once it resolves; `setSignIn` keeps it across progress updates.)
- change `signInInTerminal`'s signature to `private async signInInTerminal(surface: Surface, providerId?: string): Promise<void>` (it already resolves the provider from `providerId ?? this.providerOf(…)`);
- add cases to `handle`, before `case 'openFile'`:

```ts
      case 'cancelSignIn':
        this.signIns.get(message.providerId)?.flow?.cancel()
        this.setSignIn(message.providerId, null)
        return
      case 'signInInTerminal':
        return this.signInInTerminal(surface, message.providerId)
      case 'refreshProviders':
        this.states.clear()
        return this.postProviders()
```

- in the `'ready'` case, after posting quotas, add:

```ts
        for (const [providerId, { progress }] of this.signIns) this.post(surface, { type: 'signInProgress', providerId, progress })
```

- in `dispose`, add `for (const { flow } of this.signIns.values()) flow?.cancel()`;
- add a public method used by the extension:

```ts
  /** The provider chooser in its own tab: the welcome screen and the providers page. */
  openProviders(title = 'AgentDeck: Providers'): void {
    const panel = vscode.window.createWebviewPanel(PANEL_TYPE, title, vscode.ViewColumn.Active, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [this.assets()]
    })
    this.attachPanel(panel)
    panel.title = title
  }
```

- [ ] **Step 4: Welcome on first run; Manage Providers**

In `src/extension.ts`, add to `context.subscriptions.push(...)`:

```ts
    vscode.commands.registerCommand('agentdeck.manageProviders', () => surfaces.openProviders()),
```

and after the `push(...)` call:

```ts
  // First run: show the providers and how to start, once.
  if (!context.globalState.get('agentdeck.welcomed') && sessionManager.list().length === 0) {
    void context.globalState.update('agentdeck.welcomed', true)
    surfaces.openProviders('Welcome to AgentDeck')
  }
```

In `package.json` `contributes.commands`, add:

```json
      { "command": "agentdeck.manageProviders", "title": "Manage Providers", "category": "AgentDeck", "icon": "$(account)" }
```

and to `menus["view/title"]`:

```json
        { "command": "agentdeck.manageProviders", "when": "view == agentdeck.chat", "group": "navigation@3" }
```

- [ ] **Step 5: Verify and commit**

Run: `pnpm typecheck && pnpm test` → clean; PASS.

```bash
git add src/ui src/extension.ts package.json webview/app/state.ts test/webview/state.test.ts
git commit -m "feat(ui): run sign-in flows in the host, welcome on first run, and manage providers"
```

---

### Task 4: Welcome screen and the sign-in stepper

**Files:**
- Modify: `webview/app/components/empty-state.tsx` (full replacement), `webview/app/App.tsx`

- [ ] **Step 1: The chooser becomes the welcome screen**

`webview/app/components/empty-state.tsx`:

```tsx
import { Shimmer } from '@/components/ai-elements/shimmer'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { ProviderInfo, SignInProgress } from '../../../src/ui/protocol'
import { send } from '../host'
import { Codicon } from './codicon'
import { ProviderAvatar } from './provider-avatar'

const READY = new Set(['signed-in', 'unknown'])

/** Shown by a tab or the sidebar before a chat exists: who is ready, and how to get the rest ready. */
export function EmptyState({ providers, signIns }: { providers: ProviderInfo[]; signIns: Record<string, SignInProgress> }) {
  const ready = providers.filter((provider) => READY.has(provider.state.status)).length
  return (
    <div className="@container flex min-h-screen flex-col justify-center gap-5 p-4">
      <div className="mx-auto max-w-lg space-y-2 text-center">
        {providers.length > 0 && (
          <span className="inline-block rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
            {ready} of {providers.length} providers ready
          </span>
        )}
        <div className="text-lg font-semibold @[36rem]:text-2xl">Your agents, one chat</div>
        <p className="text-xs text-muted-foreground @[36rem]:text-sm">
          AgentDeck runs each provider's own CLI on your own subscription. Sign-ins stay with those CLIs; nothing is stored here.
        </p>
      </div>
      {providers.length === 0 ? (
        <Shimmer as="div" className="text-center text-xs">
          Checking providers…
        </Shimmer>
      ) : (
        <div className="mx-auto grid w-full max-w-4xl grid-cols-1 gap-3 @[44rem]:grid-cols-3">
          {providers.map((provider) => (
            <ProviderCard key={provider.id} provider={provider} progress={signIns[provider.id]} />
          ))}
        </div>
      )}
      <button
        type="button"
        className="mx-auto inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        onClick={() => send({ type: 'refreshProviders' })}
      >
        <Codicon name="refresh" size={12} />
        Check again
      </button>
    </div>
  )
}

function ProviderCard({ provider, progress }: { provider: ProviderInfo; progress?: SignInProgress }) {
  const { status, account, version } = provider.state
  const ready = READY.has(status)
  const badge = ready
    ? { label: 'Ready', className: 'bg-success/15 text-success' }
    : status === 'signed-out'
      ? { label: 'Signed out', className: 'bg-warning/15 text-warning' }
      : { label: 'Not installed', className: 'bg-muted text-muted-foreground' }
  return (
    <div className={cn('flex flex-col gap-3 rounded-lg border p-3', progress && 'border-ring')}>
      <div className="flex items-center gap-2.5">
        <ProviderAvatar providerId={provider.id} />
        <div className="min-w-0 flex-1">
          <div className="font-medium">{provider.label}</div>
          <div className="truncate text-xs text-muted-foreground">{version ? `v${version}` : status === 'not-installed' ? 'CLI not found' : ''}</div>
        </div>
        <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-medium', badge.className)}>{progress ? 'Signing in' : badge.label}</span>
      </div>
      {progress ? (
        <SignInSteps providerId={provider.id} label={provider.label} progress={progress} />
      ) : (
        <>
          <p className="flex-1 text-xs text-muted-foreground">
            {ready
              ? account
                ? `Signed in as ${account}.`
                : 'Ready to chat.'
              : status === 'signed-out'
                ? `Installed. Sign in with your ${provider.label} account to start chatting.`
                : `Install the ${provider.label} CLI, then press Check again.`}
          </p>
          {ready ? (
            <Button size="sm" onClick={() => send({ type: 'newChat', providerId: provider.id })}>
              Start a chat
            </Button>
          ) : status === 'signed-out' ? (
            <Button size="sm" variant="secondary" onClick={() => send({ type: 'signIn', providerId: provider.id })}>
              Sign in
            </Button>
          ) : (
            <Button size="sm" variant="secondary" asChild>
              <a href={provider.installUrl}>Installation guide</a>
            </Button>
          )}
        </>
      )}
    </div>
  )
}

function SignInSteps({ providerId, label, progress }: { providerId: string; label: string; progress: SignInProgress }) {
  const step = progress.step === 'starting' ? 1 : 2
  const steps = [
    { title: 'Start sign-in', detail: `Runs ${label}'s own login` },
    {
      title: 'Approve in your browser',
      detail: progress.step === 'link' && progress.code ? `Confirm the code ${progress.code}` : 'Opened in your browser'
    },
    { title: 'Confirm account', detail: 'Checked automatically' }
  ]
  return (
    <div className="space-y-2.5">
      {progress.step === 'failed' ? (
        <div className="space-y-2">
          <p className="text-xs whitespace-pre-wrap text-destructive">{progress.message}</p>
          <div className="flex flex-wrap gap-2">
            <Button size="xs" onClick={() => send({ type: 'signIn', providerId })}>
              Try again
            </Button>
            <Button size="xs" variant="secondary" onClick={() => send({ type: 'signInInTerminal', providerId })}>
              Sign in in terminal
            </Button>
            <Button size="xs" variant="ghost" onClick={() => send({ type: 'cancelSignIn', providerId })}>
              Dismiss
            </Button>
          </div>
        </div>
      ) : (
        <>
          <ol className="space-y-1.5">
            {steps.map((entry, index) => {
              const number = index + 1
              const state = number < step ? 'done' : number === step ? 'active' : 'todo'
              return (
                <li key={entry.title} className="flex items-start gap-2 text-xs">
                  {state === 'done' ? (
                    <Codicon name="pass-filled" className="mt-0.5 text-success" />
                  ) : (
                    <span
                      className={cn(
                        'mt-0.5 inline-flex size-3.5 shrink-0 items-center justify-center rounded-full border text-[9px]',
                        state === 'active' ? 'border-info text-info' : 'text-muted-foreground'
                      )}
                    >
                      {number}
                    </span>
                  )}
                  <div>
                    <div className={state === 'todo' ? 'text-muted-foreground' : 'font-medium'}>{entry.title}</div>
                    <div className="text-muted-foreground">{entry.detail}</div>
                  </div>
                </li>
              )
            })}
          </ol>
          <div className="flex flex-wrap items-center gap-2 border-t pt-2 text-xs text-muted-foreground">
            {progress.step === 'link' ? (
              <>
                <span className="flex-1">Browser didn't open?</span>
                <Button size="xs" variant="secondary" onClick={() => void navigator.clipboard.writeText(progress.url)}>
                  Copy sign-in link
                </Button>
              </>
            ) : (
              <span className="flex-1">Starting {label}'s login…</span>
            )}
            <Button size="xs" variant="ghost" onClick={() => send({ type: 'cancelSignIn', providerId })}>
              Cancel
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 2: App passes sign-ins**

In `webview/app/App.tsx`, change the empty-state line to `if (state.empty) return <EmptyState providers={state.providers} signIns={state.signIns} />`.

The sign-in banner (`sign-in-banner.tsx`) keeps sending `{ type: 'signIn' }`; that now runs the guided flow, and the banner shows nothing about progress. That is acceptable for this plan.

- [ ] **Step 3: Verify and commit**

Run: `pnpm typecheck && pnpm test` → clean; PASS.

```bash
git add webview/app
git commit -m "feat(webview): welcome screen with guided sign-in steps"
```

---

### Task 5: Preview, review, and hand-off

**Files:**
- Modify: `webview/preview/scenario.ts`

- [ ] **Step 1: A sign-in in progress**

In `webview/preview/scenario.ts`:
- change the `codex` provider to `{ ...claude, id: 'codex', label: 'Codex', state: { status: 'signed-out', version: '0.164.0' } }` and add `const grokInfo: ProviderInfo = { ...claude, id: 'grok', label: 'Grok', state: { status: 'not-installed' } }`;
- make `providers` list `[claude, codex, grokInfo]`;
- change the `new` scenario's messages to:

```ts
  [
    providers,
    { type: 'signInProgress', providerId: 'codex', progress: { step: 'link', url: 'https://auth.openai.com/oauth/authorize?x=1' } },
    { type: 'empty' }
  ]
```

- [ ] **Step 2: Screenshots**

Run:

```bash
pnpm build:preview && pnpm screenshot dark 1280x800 panel new && pnpm screenshot dark 340x1100 view new && pnpm screenshot light 1280x800 panel new
```

Open each PNG and check:
- Wide (1280): the pill reads **"1 of 3 providers ready"** (Claude ready, Codex signing in, Grok not installed); the heading "Your agents, one chat" and the sentence under it; three cards in a row. Claude: *Ready*, "Signed in as me@example.com.", *Start a chat*. Codex: *Signing in*, highlighted border, steps 1 done, 2 active ("Opened in your browser"), 3 pending, "Browser didn't open? Copy sign-in link · Cancel". Grok: *Not installed*, *Installation guide*. "Check again" below.
- Narrow (340): the same cards stacked in one column, nothing overflowing.
- Light: readable, same layout.

Fix layout defects only in `empty-state.tsx`; report each fix.

- [ ] **Step 3: Package and commit**

Run: `pnpm typecheck && pnpm test && pnpm run package` → clean; PASS; packaged.

```bash
git add webview/preview
git commit -m "test(webview): preview the welcome screen with a sign-in in progress"
```

- [ ] **Step 4: Hand off**

Ask the user to reinstall (`code --install-extension agentdeck-0.1.0.vsix --force`), reload, and check: *AgentDeck: Manage Providers* (or the account icon on the chat view) opens the providers screen; *Check again* refreshes it. To try a guided sign-in without losing a login they rely on, use Grok: run `grok logout` in a terminal, press *Check again* (Grok shows *Signed out*), press *Sign in* (the browser opens the xAI device page, the card shows the code), approve it, and the card turns *Ready* without touching the terminal.
