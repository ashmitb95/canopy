# MVP plan 2: Chat app foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first.

**Goal:** Replace the POC chat with the real chat app: a React webview built on shadcn and AI Elements, themed by the active VS Code theme, shown in editor tabs and in the sidebar, and wired to the `SessionManager` from plan 1. It renders messages, reasoning, tools (as compact lines), approvals, notices, queued prompts, and a composer with the editor-context pill, Send, and Stop.

**Architecture:** The extension host owns sessions (`SessionManager`) and surfaces (`ChatSurfaces`): each editor tab (`WebviewPanel`) and the sidebar (`WebviewView`) is a surface that subscribes to one session and forwards its `SessionEvent`s as `HostMessage`s. The webview is one React app whose state is a pure reducer over `HostMessage`s; it sends `WebviewMessage`s back. Styles come from Tailwind v4 with a token bridge that maps every shadcn token to a VS Code theme variable. A preview build of the same app runs in headless Chromium from a `file://` page, so UI work can be checked from screenshots without VS Code.

**Tech Stack:** React 19, Tailwind v4 (`@tailwindcss/cli`), shadcn 4.23 components, AI Elements (Conversation, Message, Reasoning, Shimmer) from the `elements.ai-sdk.dev` registry, Streamdown with its Shiki code plugin, `@vscode/codicons`, esbuild (ESM with code splitting for the webview), vitest.

**What the spike established** (scratch project, 2026-10-28; recorded here so executors do not rediscover it):
- `shadcn@4.23.0 add` works without a framework given a hand-written `components.json` and a root `tsconfig.json` `paths` entry for `@/*`. shadcn components land in `webview/components/ui/`. AI Elements installed from registry URLs land in a top-level `components/ai-elements/` regardless of aliases and must be moved to `webview/components/ai-elements/`.
- shadcn 4.23 components import `cn` from the `cn` package; AI Elements import it from `@/lib/utils`, which must exist and re-export it.
- AI Elements' `message.tsx` and `reasoning.tsx` load four Streamdown plugins (`cjk`, `code`, `math`, `mermaid`); `mermaid` and `math` add about 2.5 MB. Keep only `code`.
- Streamdown's code plugin uses Shiki with the JavaScript regex engine (no WebAssembly) and imports every grammar lazily. An ESM build with `splitting: true` keeps the entry script near 0.7 MB and loads grammars on demand.
- AI Elements' `tool`, `confirmation`, `prompt-input`, and `context` components are typed against the AI SDK's message parts, use lucide icons, and hard-code green/red; AgentDeck builds those cards itself on shadcn primitives with codicons and theme colors. `context.tsx` also fails to type-check against `ai@7`.
- Codicons from `codicon.css` are unlayered CSS, so they beat Tailwind's layered utilities: size icons with an inline `fontSize`, not `text-*` classes.

---

## File structure

| File | Responsibility |
|---|---|
| `components.json` | shadcn CLI configuration (aliases, Tailwind CSS path) |
| `webview/tsconfig.json` | TypeScript settings for the webview (DOM, JSX, `@/*` alias) |
| `webview/theme.css` | Tailwind entry and the VS Code → shadcn token bridge |
| `webview/lib/utils.ts` | `cn` re-export for AI Elements |
| `webview/components/ui/*` | shadcn components (generated, then committed) |
| `webview/components/ai-elements/*` | AI Elements components (generated, trimmed, committed) |
| `webview/main.tsx` | Mounts the app |
| `webview/app/host.ts` | VS Code webview API bridge |
| `webview/app/state.ts` | `ChatState` and the reducer over `HostMessage` |
| `webview/app/format.ts` | Small text helpers shared by components |
| `webview/app/App.tsx` | Layout: header, conversation, status, queue, composer |
| `webview/app/components/*.tsx` | Codicon, ProviderAvatar, StatusBadge, FilePill, ChatHeader, EmptyState, WorkingStatus, QueueList, Composer |
| `webview/app/items/*.tsx` | One component per `SessionItem` kind, plus the `ItemView` switch |
| `webview/preview/*` | Preview page, fake VS Code themes, and a scripted scenario |
| `src/ui/protocol.ts` | `HostMessage`, `WebviewMessage`, `EditorContext`, `ProviderInfo` |
| `src/ui/editor-context.ts` | Tracks the file and selection a prompt refers to |
| `src/ui/chat-surfaces.ts` | Editor-tab and sidebar webviews bound to sessions |
| `src/extension.ts` | Activation: wires manager, surfaces, commands (full rewrite) |
| `esbuild.mjs` | Extension, webview, and preview builds (full rewrite) |
| `scripts/screenshot.mjs` | Renders the preview to a PNG |
| `media/agentdeck.svg` | Activity bar icon |
| Removed: `src/claude-session.ts`, `media/chat.js`, `media/chat.css` | POC UI |

---

### Task 1: Webview toolchain and vendored components

**Files:**
- Create: `components.json`, `webview/tsconfig.json`, `webview/lib/utils.ts`, `webview/theme.css`
- Generated, then committed: `webview/components/ui/*`, `webview/components/ai-elements/*`
- Modify: `tsconfig.json`, `package.json`, `pnpm-workspace.yaml`

- [ ] **Step 1: Let shadcn resolve `@/` to `webview/`**

In the root `tsconfig.json`, add to `compilerOptions` (after `"types"`):

```json
    "baseUrl": ".",
    "paths": { "@/*": ["./webview/*"] }
```

The root project still includes only `src`, `scripts`, and `test`; this entry exists for the shadcn CLI.

- [ ] **Step 2: Add `components.json`**

`components.json`:

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": false,
  "tsx": true,
  "tailwind": { "config": "", "css": "webview/theme.css", "baseColor": "neutral", "cssVariables": true, "prefix": "" },
  "iconLibrary": "lucide",
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  }
}
```

- [ ] **Step 3: Allow the Tailwind CLI's native watcher to build**

In `pnpm-workspace.yaml`, under `allowBuilds:`, add:

```yaml
  '@parcel/watcher': true
```

- [ ] **Step 4: Install the build-time packages**

Run:

```bash
pnpm add -D tailwindcss@4.3.3 @tailwindcss/cli@4.3.3 tw-animate-css@1.4.0 @types/react@19 @types/react-dom@19 @vscode/codicons@0.0.46-24
pnpm add react@19.3.1 react-dom@19.3.1
```

Expected: both succeed. If pnpm writes a placeholder line under `allowBuilds` (text like `set this to true or false`), delete that line.

- [ ] **Step 5: Create a placeholder Tailwind entry so the CLI accepts the config**

`webview/theme.css` (replaced in Step 9):

```css
@import "tailwindcss";
```

- [ ] **Step 6: Add the shadcn components**

Run:

```bash
npx -y shadcn@4.23.0 add button badge collapsible dropdown-menu popover separator textarea tooltip --yes
```

Expected: files under `webview/components/ui/`. If the CLI asks to overwrite anything, answer no (in a non-interactive shell, prefix the command with `yes n |`).

- [ ] **Step 7: Add the AI Elements components and move them under `webview/`**

Run:

```bash
R=https://elements.ai-sdk.dev/api/registry
yes n | npx -y shadcn@4.23.0 add $R/conversation.json $R/message.json $R/reasoning.json $R/shimmer.json --yes
```

The CLI asks to overwrite shadcn files that already exist; `yes n |` answers no. It writes the AI Elements files to `components/ai-elements/` or `src/components/ai-elements/` depending on the project layout it detects. Move them:

```bash
mkdir -p webview/components
for dir in components src/components; do [ -d $dir/ai-elements ] && mv $dir/ai-elements webview/components/ && rmdir $dir; done
```

Expected: `webview/components/ai-elements/{conversation,message,reasoning,shimmer}.tsx` exist and neither `components/` nor `src/components/` remains. The CLI also adds any shadcn components they depend on (for example `button-group`) to `webview/components/ui/`.

- [ ] **Step 8: Add `@/lib/utils` and keep only the code plugin**

`webview/lib/utils.ts`:

```ts
export { cn } from 'cn'
```

In both `webview/components/ai-elements/message.tsx` and `webview/components/ai-elements/reasoning.tsx`:
- delete the three lines `import { cjk } from "@streamdown/cjk";`, `import { math } from "@streamdown/math";`, `import { mermaid } from "@streamdown/mermaid";`
- change `const streamdownPlugins = { cjk, code, math, mermaid };` to `const streamdownPlugins = { code };`

Then run (the shadcn components need `class-variance-authority`, which the CLI does not add):

```bash
pnpm add class-variance-authority@0.7.1
pnpm remove @streamdown/cjk @streamdown/math @streamdown/mermaid
grep -rn "streamdown/cjk\|streamdown/math\|streamdown/mermaid" webview || echo CLEAN
```

Expected: `CLEAN`.

- [ ] **Step 9: Write the theme bridge**

`webview/theme.css` (full replacement):

```css
@import "tailwindcss";
@import "tw-animate-css";

@source "./";
@source "../node_modules/streamdown/dist/*.js";

/* VS Code sets the theme kind as a class on <body>. */
@custom-variant dark (&:is(.vscode-dark *, .vscode-high-contrast:not(.vscode-high-contrast-light) *));

/*
 * The active VS Code theme is the only source of color: every token maps to a theme variable.
 * The last fallback on --border covers themes that define neither border variable.
 */
:root {
  --background: var(--vscode-editor-background);
  --foreground: var(--vscode-foreground);
  --card: var(--vscode-editorWidget-background);
  --card-foreground: var(--vscode-foreground);
  --popover: var(--vscode-editorWidget-background);
  --popover-foreground: var(--vscode-foreground);
  --primary: var(--vscode-button-background);
  --primary-foreground: var(--vscode-button-foreground);
  --secondary: var(--vscode-button-secondaryBackground);
  --secondary-foreground: var(--vscode-button-secondaryForeground);
  --muted: var(--vscode-textCodeBlock-background);
  --muted-foreground: var(--vscode-descriptionForeground);
  --accent: var(--vscode-list-hoverBackground);
  --accent-foreground: var(--vscode-foreground);
  --destructive: var(--vscode-errorForeground);
  --border: var(--vscode-widget-border, var(--vscode-panel-border, rgb(128 128 128 / 0.35)));
  --input: var(--vscode-input-background);
  --ring: var(--vscode-focusBorder);
  --success: var(--vscode-testing-iconPassed);
  --warning: var(--vscode-editorWarning-foreground);
  --info: var(--vscode-charts-blue);
  --code: var(--vscode-textCodeBlock-background);
  --diff-added: var(--vscode-diffEditor-insertedLineBackground);
  --diff-removed: var(--vscode-diffEditor-removedLineBackground);
  --selection: var(--vscode-list-activeSelectionBackground);
  --selection-foreground: var(--vscode-list-activeSelectionForeground);
  --badge: var(--vscode-badge-background);
  --badge-foreground: var(--vscode-badge-foreground);
  --radius: 8px;
}

/* The sidebar chat sits on the sidebar's background. */
body[data-surface="view"] {
  --background: var(--vscode-sideBar-background);
}

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-success: var(--success);
  --color-warning: var(--warning);
  --color-info: var(--info);
  --color-code: var(--code);
  --color-diff-added: var(--diff-added);
  --color-diff-removed: var(--diff-removed);
  --color-selection: var(--selection);
  --color-selection-foreground: var(--selection-foreground);
  --color-badge: var(--badge);
  --color-badge-foreground: var(--badge-foreground);
  --font-sans: var(--vscode-font-family);
  --font-mono: var(--vscode-editor-font-family);
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 2px);
}

@layer base {
  * {
    @apply border-border outline-ring/50;
  }
  html,
  body {
    margin: 0;
    padding: 0;
  }
  body {
    @apply bg-background text-foreground font-sans;
    font-size: var(--vscode-font-size);
  }
  code,
  pre,
  kbd {
    font-family: var(--vscode-editor-font-family);
  }
  .vscode-high-contrast [data-slot] {
    outline-color: var(--vscode-contrastBorder);
  }
}
```

- [ ] **Step 10: Add the webview TypeScript project**

`webview/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "strict": true,
    "skipLibCheck": true,
    "noEmit": true,
    "baseUrl": ".",
    "paths": { "@/*": ["./*"] },
    "types": ["node"]
  },
  "include": ["."]
}
```

`types: ["node"]` is there because the webview imports type definitions from `src/`, whose files reference Node types.

- [ ] **Step 11: Type-check the webview project**

In `package.json`, change the `typecheck` script to:

```json
    "typecheck": "tsc --noEmit && tsc --noEmit -p webview",
```

Run: `pnpm typecheck`
Expected: clean. If a vendored file fails to type-check, report the error before editing vendored code; the only edits expected in vendored files are the Step 8 plugin trims.

- [ ] **Step 12: Pin the versions the CLIs added**

The shadcn CLI adds dependencies with `^` ranges. Pin them to what was installed, leaving `engines.vscode` a range (an exact engine makes every other VS Code version refuse the VSIX):

```bash
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

Expected: no `^` left in `dependencies` or `devDependencies`, `engines.vscode` is still `^1.95.0`, and `pnpm install` succeeds.

- [ ] **Step 13: Commit**

```bash
git add components.json tsconfig.json webview package.json pnpm-lock.yaml pnpm-workspace.yaml
git commit -m "build(webview): add Tailwind v4, shadcn, and AI Elements with the VS Code theme bridge"
```

---

### Task 2: Protocol and chat state

**Files:**
- Create: `src/ui/protocol.ts`
- Create: `webview/app/state.ts`
- Test: `test/webview/state.test.ts`

- [ ] **Step 1: Write the protocol**

`src/ui/protocol.ts`:

```ts
import type { Capability, PermissionMode, ProviderState } from '../core/types'
import type { SessionEvent } from '../sessions/manager'

export type EditorContext = { path: string; label: string; range?: [number, number] }

export type ProviderInfo = {
  id: string
  label: string
  installUrl: string
  capabilities: Capability[]
  modes: readonly PermissionMode[]
  state: ProviderState
}

/** Extension host → webview. */
export type HostMessage =
  | { type: 'session'; sessionId: string; event: SessionEvent }
  | { type: 'title'; sessionId: string; title: string }
  | { type: 'provider'; provider: ProviderInfo }
  | { type: 'editorContext'; context: EditorContext | null }
  /** The sidebar has no session yet. */
  | { type: 'empty' }

/** Webview → extension host. */
export type WebviewMessage =
  | { type: 'ready' }
  | { type: 'prompt'; text: string; includeContext: boolean }
  | { type: 'cancel' }
  | { type: 'answer'; itemId: string; optionId: string }
  | { type: 'removeQueued'; queuedId: string }
  | { type: 'newChat' }
  | { type: 'signIn' }
  | { type: 'openFile'; path: string; line?: number }
```

- [ ] **Step 2: Write the failing reducer tests**

`test/webview/state.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import type { SessionEvent } from '../../src/sessions/manager'
import type { SessionRecord } from '../../src/sessions/store'
import type { HostMessage } from '../../src/ui/protocol'
import { type ChatState, initialState, reduce } from '../../webview/app/state'

const record: SessionRecord = {
  id: 's1',
  providerId: 'claude',
  title: 'Chat',
  createdAt: 't',
  updatedAt: 't',
  mode: 'ask',
  hasTurns: false,
  facts: {}
}
const reply = (id: string, text: string): SessionItem => ({ kind: 'message', id, role: 'assistant', text, streaming: false })
const session = (event: SessionEvent, sessionId = 's1'): HostMessage => ({ type: 'session', sessionId, event })
const snapshot = (items: SessionItem[] = [], sessionId = 's1'): HostMessage =>
  session({ type: 'snapshot', record: { ...record, id: sessionId }, status: 'idle', items, queue: [] }, sessionId)
const run = (...messages: HostMessage[]): ChatState => messages.reduce(reduce, initialState)

describe('chat state', () => {
  it('loads a snapshot', () => {
    const state = run(snapshot([reply('a', 'hi')]))
    expect(state).toMatchObject({ sessionId: 's1', record, status: 'idle', items: [reply('a', 'hi')], empty: false })
  })

  it('upserts items in place and appends new ones', () => {
    const state = run(
      snapshot([reply('a', 'h')]),
      session({ type: 'item', item: reply('b', 'x') }),
      session({ type: 'item', item: reply('a', 'hello') })
    )
    expect(state.items).toEqual([reply('a', 'hello'), reply('b', 'x')])
  })

  it('ignores events for a session it is not showing', () => {
    const state = run(snapshot(), session({ type: 'item', item: reply('a', 'x') }, 'other'))
    expect(state.items).toEqual([])
  })

  it('switches sessions on a new snapshot', () => {
    const state = run(snapshot([reply('a', 'x')]), snapshot([], 's2'))
    expect(state).toMatchObject({ sessionId: 's2', items: [] })
  })

  it('tracks status, queue, and facts', () => {
    const state = run(
      snapshot(),
      session({ type: 'status', status: 'running' }),
      session({ type: 'queue', queue: [{ id: 'q', parts: [{ type: 'text', text: 'next' }] }] }),
      session({ type: 'fact', fact: { kind: 'context', usedTokens: 10, maxTokens: 100 } })
    )
    expect(state.status).toBe('running')
    expect(state.queue).toHaveLength(1)
    expect(state.facts.context).toEqual({ kind: 'context', usedTokens: 10, maxTokens: 100 })
  })

  it('renames the session it is showing', () => {
    const state = run(
      snapshot(),
      { type: 'title', sessionId: 's1', title: 'Fix login' },
      { type: 'title', sessionId: 'other', title: 'Nope' }
    )
    expect(state.record?.title).toBe('Fix login')
  })

  it('keeps provider and editor context across an empty sidebar', () => {
    const provider = {
      id: 'claude',
      label: 'Claude',
      installUrl: 'u',
      capabilities: [],
      modes: ['ask' as const],
      state: { status: 'signed-in' as const }
    }
    const state = run(
      { type: 'provider', provider },
      { type: 'editorContext', context: { path: '/w/a.ts', label: 'a.ts' } },
      snapshot([reply('a', 'x')]),
      { type: 'empty' }
    )
    expect(state).toMatchObject({ empty: true, items: [], provider, editorContext: { path: '/w/a.ts' } })
    expect(state.sessionId).toBeUndefined()
  })
})
```

- [ ] **Step 3: Run it to verify it fails**

Run: `pnpm test test/webview/state.test.ts`
Expected: FAIL, cannot resolve `webview/app/state`.

- [ ] **Step 4: Implement**

`webview/app/state.ts`:

```ts
import type { SessionItem } from '../../src/core/types'
import type { QueuedPrompt, SessionEvent } from '../../src/sessions/manager'
import type { SessionRecord, SessionStatus } from '../../src/sessions/store'
import type { EditorContext, HostMessage, ProviderInfo } from '../../src/ui/protocol'

export type ChatState = {
  sessionId?: string
  record?: SessionRecord
  status: SessionStatus
  items: SessionItem[]
  queue: QueuedPrompt[]
  facts: SessionRecord['facts']
  provider?: ProviderInfo
  editorContext: EditorContext | null
  /** The sidebar has no session to show. */
  empty: boolean
}

export const initialState: ChatState = {
  status: 'idle',
  items: [],
  queue: [],
  facts: {},
  editorContext: null,
  empty: false
}

export function reduce(state: ChatState, message: HostMessage): ChatState {
  switch (message.type) {
    case 'provider':
      return { ...state, provider: message.provider }
    case 'editorContext':
      return { ...state, editorContext: message.context }
    case 'empty':
      return { ...initialState, provider: state.provider, editorContext: state.editorContext, empty: true }
    case 'title':
      if (message.sessionId !== state.sessionId || !state.record) return state
      return { ...state, record: { ...state.record, title: message.title } }
    case 'session':
      return sessionEvent(state, message.sessionId, message.event)
  }
}

function sessionEvent(state: ChatState, sessionId: string, event: SessionEvent): ChatState {
  if (event.type === 'snapshot') {
    return {
      ...state,
      empty: false,
      sessionId,
      record: event.record,
      status: event.status,
      items: event.items,
      queue: event.queue,
      facts: event.record.facts
    }
  }
  if (sessionId !== state.sessionId) return state
  switch (event.type) {
    case 'item':
      return { ...state, items: upsert(state.items, event.item) }
    case 'fact':
      return { ...state, facts: { ...state.facts, [event.fact.kind]: event.fact } }
    case 'status':
      return { ...state, status: event.status }
    case 'queue':
      return { ...state, queue: event.queue }
  }
}

function upsert(items: SessionItem[], item: SessionItem): SessionItem[] {
  const index = items.findIndex((existing) => existing.id === item.id)
  if (index === -1) return [...items, item]
  const next = items.slice()
  next[index] = item
  return next
}
```

- [ ] **Step 5: Run tests and typecheck**

Run: `pnpm test && pnpm typecheck`
Expected: PASS; typecheck clean.

- [ ] **Step 6: Commit**

```bash
git add src/ui/protocol.ts webview/app/state.ts test/webview/state.test.ts
git commit -m "feat(webview): add the host protocol and chat state reducer"
```

---

### Task 3: Builds and the screenshot preview

**Files:**
- Modify: `esbuild.mjs` (full replacement)
- Modify: `package.json` (scripts)
- Modify: `.vscodeignore` (full replacement)
- Create: `webview/main.tsx`, `webview/app/host.ts`, `webview/app/App.tsx` (minimal; Task 4 replaces `App.tsx`)
- Create: `webview/preview/index.html`, `webview/preview/themes.css`, `webview/preview/scenario.ts`
- Create: `scripts/screenshot.mjs`

- [ ] **Step 1: Replace the build script**

`esbuild.mjs`:

```js
import { execFileSync } from 'node:child_process'
import { cpSync, mkdirSync, rmSync } from 'node:fs'
import * as esbuild from 'esbuild'

const watch = process.argv.includes('--watch')
const preview = process.argv.includes('--preview')

const extension = {
  entryPoints: { extension: 'src/extension.ts', smoke: 'scripts/smoke.ts', 'record-claude': 'scripts/record-claude.ts' },
  outdir: 'dist',
  bundle: true,
  platform: 'node',
  format: 'cjs',
  target: 'node20',
  sourcemap: true,
  // The Agent SDK is ESM and reads import.meta.url, which a CJS bundle lacks; point it at the bundle file.
  define: { 'import.meta.url': '__importMetaUrl' },
  banner: { js: 'const __importMetaUrl = require("url").pathToFileURL(__filename).href;' },
  external: ['vscode']
}

const webview = {
  entryPoints: { main: 'webview/main.tsx' },
  outdir: 'dist/webview',
  bundle: true,
  format: 'esm',
  // Shiki's grammars load on demand as separate chunks instead of inflating the entry script.
  splitting: true,
  platform: 'browser',
  target: 'chrome120',
  jsx: 'automatic',
  tsconfig: 'webview/tsconfig.json',
  entryNames: '[name]',
  chunkNames: 'chunks/[name]-[hash]',
  minify: !watch,
  sourcemap: watch,
  define: { 'process.env.NODE_ENV': watch ? '"development"' : '"production"' }
}

// Classic scripts, so the preview page works from a file:// URL in headless Chromium.
const previewBuild = {
  ...webview,
  entryPoints: { main: 'webview/main.tsx', scenario: 'webview/preview/scenario.ts' },
  outdir: 'dist/preview',
  format: 'iife',
  splitting: false,
  minify: false
}

function styles(outdir) {
  mkdirSync(outdir, { recursive: true })
  execFileSync('node_modules/.bin/tailwindcss', ['-i', 'webview/theme.css', '-o', `${outdir}/webview.css`, '--minify'], {
    stdio: 'inherit'
  })
  cpSync('node_modules/@vscode/codicons/dist/codicon.css', `${outdir}/codicon.css`)
  cpSync('node_modules/@vscode/codicons/dist/codicon.ttf', `${outdir}/codicon.ttf`)
}

if (preview) {
  rmSync('dist/preview', { recursive: true, force: true })
  await esbuild.build(previewBuild)
  styles('dist/preview')
  cpSync('webview/preview/index.html', 'dist/preview/index.html')
  cpSync('webview/preview/themes.css', 'dist/preview/themes.css')
} else if (watch) {
  styles('dist/webview')
  await (await esbuild.context(extension)).watch()
  await (await esbuild.context(webview)).watch()
} else {
  // Chunk names carry hashes, so stale chunks would pile up without a clean build.
  rmSync('dist/webview', { recursive: true, force: true })
  await Promise.all([esbuild.build(extension), esbuild.build(webview)])
  styles('dist/webview')
}
```

- [ ] **Step 2: Add scripts**

In `package.json` `scripts`, add after `"watch"`:

```json
    "build:preview": "node esbuild.mjs --preview",
    "screenshot": "node scripts/screenshot.mjs",
```

- [ ] **Step 3: Ship only the extension bundle, the webview, and the icon**

`.vscodeignore`:

```
**
!dist/extension.js
!dist/webview/**
!media/agentdeck.svg
!package.json
```

- [ ] **Step 4: Add the webview bridge and a minimal app**

`webview/app/host.ts`:

```ts
import type { HostMessage, WebviewMessage } from '../../src/ui/protocol'

type VsCodeApi = { postMessage(message: unknown): void; getState(): unknown; setState(state: unknown): void }

declare function acquireVsCodeApi(): VsCodeApi

const api = acquireVsCodeApi()

export function send(message: WebviewMessage): void {
  api.postMessage(message)
}

/** Lets VS Code restore an editor tab's session after a reload. */
export function saveState(state: { sessionId: string }): void {
  api.setState(state)
}

export function onHostMessage(listener: (message: HostMessage) => void): () => void {
  const handler = (event: MessageEvent<HostMessage>) => listener(event.data)
  window.addEventListener('message', handler)
  return () => window.removeEventListener('message', handler)
}
```

`webview/app/App.tsx` (minimal; Task 4 replaces it):

```tsx
export function App() {
  return <div className="p-4 text-muted-foreground">AgentDeck</div>
}
```

`webview/main.tsx`:

```tsx
import { createRoot } from 'react-dom/client'
import { App } from './app/App'

createRoot(document.getElementById('root')!).render(<App />)
```

- [ ] **Step 5: Add the preview page**

`webview/preview/themes.css` (approximations of Dark Modern and Light Modern, only for previews):

```css
:root[data-preview-theme="dark"] {
  --vscode-font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --vscode-font-size: 13px;
  --vscode-editor-font-family: Menlo, Monaco, "Courier New", monospace;
  --vscode-editor-background: #1f1f1f;
  --vscode-sideBar-background: #181818;
  --vscode-foreground: #cccccc;
  --vscode-descriptionForeground: #9d9d9d;
  --vscode-editorWidget-background: #202020;
  --vscode-button-background: #0078d4;
  --vscode-button-foreground: #ffffff;
  --vscode-button-secondaryBackground: #313131;
  --vscode-button-secondaryForeground: #cccccc;
  --vscode-textCodeBlock-background: #2b2b2b;
  --vscode-list-hoverBackground: #2a2d2e;
  --vscode-errorForeground: #f85149;
  --vscode-widget-border: #313131;
  --vscode-input-background: #313131;
  --vscode-focusBorder: #0078d4;
  --vscode-testing-iconPassed: #73c991;
  --vscode-editorWarning-foreground: #cca700;
  --vscode-charts-blue: #3794ff;
  --vscode-diffEditor-insertedLineBackground: rgba(155, 185, 85, 0.2);
  --vscode-diffEditor-removedLineBackground: rgba(255, 0, 0, 0.2);
  --vscode-list-activeSelectionBackground: #04395e;
  --vscode-list-activeSelectionForeground: #ffffff;
  --vscode-badge-background: #616161;
  --vscode-badge-foreground: #f8f8f8;
}

:root[data-preview-theme="light"] {
  --vscode-font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --vscode-font-size: 13px;
  --vscode-editor-font-family: Menlo, Monaco, "Courier New", monospace;
  --vscode-editor-background: #ffffff;
  --vscode-sideBar-background: #f8f8f8;
  --vscode-foreground: #3b3b3b;
  --vscode-descriptionForeground: #717171;
  --vscode-editorWidget-background: #f8f8f8;
  --vscode-button-background: #005fb8;
  --vscode-button-foreground: #ffffff;
  --vscode-button-secondaryBackground: #e5e5e5;
  --vscode-button-secondaryForeground: #3b3b3b;
  --vscode-textCodeBlock-background: #f2f2f2;
  --vscode-list-hoverBackground: #f2f2f2;
  --vscode-errorForeground: #f85149;
  --vscode-widget-border: #e5e5e5;
  --vscode-input-background: #ffffff;
  --vscode-focusBorder: #005fb8;
  --vscode-testing-iconPassed: #388a34;
  --vscode-editorWarning-foreground: #bf8803;
  --vscode-charts-blue: #1a85ff;
  --vscode-diffEditor-insertedLineBackground: rgba(155, 185, 85, 0.2);
  --vscode-diffEditor-removedLineBackground: rgba(255, 0, 0, 0.2);
  --vscode-list-activeSelectionBackground: #e8e8e8;
  --vscode-list-activeSelectionForeground: #000000;
  --vscode-badge-background: #cccccc;
  --vscode-badge-foreground: #3b3b3b;
}
```

`webview/preview/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="themes.css">
<link rel="stylesheet" href="codicon.css">
<link rel="stylesheet" href="webview.css">
<script>
  // Stands in for VS Code: the theme variables, the body theme class, and the webview API.
  window.previewTheme = new URLSearchParams(location.search).get('theme') === 'light' ? 'light' : 'dark'
  document.documentElement.dataset.previewTheme = window.previewTheme
  window.acquireVsCodeApi = () => ({ postMessage() {}, getState() {}, setState() {} })
</script>
</head>
<body>
<script>document.body.classList.add(window.previewTheme === 'light' ? 'vscode-light' : 'vscode-dark')</script>
<div id="root"></div>
<script src="main.js"></script>
<script src="scenario.js"></script>
</body>
</html>
```

`webview/preview/scenario.ts` (one session exercising every item kind plan 2 renders):

```ts
import type { SessionItem } from '../../src/core/types'
import type { SessionRecord } from '../../src/sessions/store'
import type { HostMessage } from '../../src/ui/protocol'

const record: SessionRecord = {
  id: 's1',
  providerId: 'claude',
  title: 'Fix flaky retry test',
  createdAt: '2026-10-28T10:00:00.000Z',
  updatedAt: '2026-10-28T10:04:00.000Z',
  mode: 'ask',
  hasTurns: true,
  facts: {}
}

const items: SessionItem[] = [
  {
    kind: 'message',
    id: 'u1',
    role: 'user',
    parts: [
      { type: 'text', text: 'The retry test in api.test.ts fails about one run in five. Find out why and fix it.' },
      { type: 'file', path: '/work/src/api.test.ts', range: [40, 72] }
    ]
  },
  { kind: 'turn', id: 't1', state: 'started' },
  {
    kind: 'thought',
    id: 'th1',
    text: 'The failure rate suggests a timing race rather than a logic bug. The test uses fake timers, so the order of advanceTimersByTime against the retry scheduling matters.',
    streaming: false
  },
  { kind: 'tool', id: 'tool1', title: 'Read /work/src/retry.ts', toolKind: 'read', status: 'done', paths: ['/work/src/retry.ts'] },
  { kind: 'tool', id: 'tool2', title: 'Grep advanceTimersByTime', toolKind: 'search', status: 'done' },
  {
    kind: 'tool',
    id: 'tool3',
    title: 'Bash pnpm vitest run api.test.ts',
    toolKind: 'execute',
    status: 'failed',
    output: '✓ api.test.ts > parses response (3ms)\n× api.test.ts > retries with backoff'
  },
  {
    kind: 'message',
    id: 'a1',
    role: 'assistant',
    streaming: false,
    text: "Found it. The test advances the clock before `retry()` has scheduled its backoff, so the timer sometimes fires after the assertion.\n\nI'll schedule the delay synchronously:\n\n```ts\nawait sleep(delay)\nreturn attempt(n + 1)\n```"
  },
  {
    kind: 'diff',
    id: 'tool4:diff',
    path: '/work/src/retry.ts',
    oldText: 'setTimeout(() => attempt(n + 1), delay)',
    newText: 'await sleep(delay)\nreturn attempt(n + 1)'
  },
  {
    kind: 'approval',
    id: 'approval:1',
    title: 'Allow Claude to run this command?',
    detail: 'pnpm vitest run api.test.ts --repeat 20',
    options: [
      { id: 'allow', label: 'Allow once' },
      { id: 'always', label: 'Always allow' },
      { id: 'deny', label: 'Deny' }
    ]
  }
]

const messages: HostMessage[] = [
  {
    type: 'provider',
    provider: {
      id: 'claude',
      label: 'Claude',
      installUrl: 'https://example.invalid',
      capabilities: [],
      modes: ['ask'],
      state: { status: 'signed-in', account: 'me@example.com' }
    }
  },
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

// Posted after the app has mounted and subscribed.
setTimeout(() => {
  for (const message of messages) window.postMessage(message, '*')
}, 100)
```

- [ ] **Step 6: Add the screenshot script**

`scripts/screenshot.mjs`:

```js
// Renders dist/preview in headless Chromium and writes a PNG, so UI changes can be reviewed without VS Code.
import { execFileSync } from 'node:child_process'
import { existsSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join, resolve } from 'node:path'

const [theme = 'dark', size = '900x1200'] = process.argv.slice(2)
const [width, height] = size.split('x')
const out = resolve(`dist/preview/screenshot-${theme}.png`)
const browser = process.env.AGENTDECK_CHROME ?? findHeadlessShell()
if (!browser) {
  console.error('No headless Chromium found. Run `npx playwright install chromium-headless-shell` or set AGENTDECK_CHROME.')
  process.exit(1)
}
execFileSync(
  browser,
  [
    '--headless',
    '--disable-gpu',
    '--hide-scrollbars',
    `--screenshot=${out}`,
    `--window-size=${width},${height}`,
    '--virtual-time-budget=5000',
    `file://${resolve('dist/preview/index.html')}?theme=${theme}`
  ],
  { stdio: 'ignore' }
)
console.log(out)

function findHeadlessShell() {
  const cache =
    process.platform === 'darwin' ? join(homedir(), 'Library/Caches/ms-playwright') : join(homedir(), '.cache/ms-playwright')
  if (!existsSync(cache)) return undefined
  const name = process.platform === 'win32' ? 'chrome-headless-shell.exe' : 'chrome-headless-shell'
  const dirs = readdirSync(cache)
    .filter((dir) => dir.startsWith('chromium_headless_shell'))
    .sort()
    .reverse()
  for (const dir of dirs) {
    const match = readdirSync(join(cache, dir), { recursive: true }).find((file) => String(file).endsWith(name))
    if (match) return join(cache, dir, String(match))
  }
  return undefined
}
```

- [ ] **Step 7: Build everything and take a screenshot**

Run:

```bash
pnpm typecheck && pnpm build && ls dist/webview && pnpm build:preview && pnpm screenshot dark
```

Expected: `dist/webview` contains `main.js`, `webview.css`, `codicon.css`, `codicon.ttf`, and `chunks/`; the last command prints the path of `dist/preview/screenshot-dark.png`. The image shows the word "AgentDeck" in grey on a dark background (the minimal app ignores the scenario). If no headless Chromium is found, report it; do not install browsers without asking.

- [ ] **Step 8: Commit**

```bash
git add esbuild.mjs package.json .vscodeignore webview/main.tsx webview/app/host.ts webview/app/App.tsx webview/preview scripts/screenshot.mjs
git commit -m "build(webview): bundle the webview and add a screenshot preview"
```

---

### Task 4: Chat app components

**Files:**
- Create: `webview/app/format.ts`
- Create: `webview/app/components/{codicon,provider-avatar,status-badge,file-pill,chat-header,empty-state,working-status,queue-list,composer}.tsx`
- Create: `webview/app/items/{user-message,assistant-message,thought,tool-line,diff-line,plan-list,approval-card,notice,item-view}.tsx`
- Modify: `webview/app/App.tsx` (full replacement)

Look and feel follow the chat-tab mockup (`docs/design/mockups/2-chat-tab.html`): dense spacing, rounded cards with a 1 px border, a warning-tinted approval card with keyboard hints, a rounded composer with the file pill on top and the action button at the right.

- [ ] **Step 1: Shared helpers and small components**

`webview/app/format.ts`:

```ts
import type { PromptPart } from '../../src/core/types'

export function promptText(parts: PromptPart[]): string {
  return parts
    .filter((part): part is Extract<PromptPart, { type: 'text' }> => part.type === 'text')
    .map((part) => part.text)
    .join('\n\n')
}

export function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path
}
```

`webview/app/components/codicon.tsx`:

```tsx
import { cn } from '@/lib/utils'

/** codicon.css is unlayered and beats Tailwind's text-size utilities, so size goes inline. */
export function Codicon({
  name,
  size = 14,
  spin = false,
  className
}: {
  name: string
  size?: number
  spin?: boolean
  className?: string
}) {
  return (
    <i
      aria-hidden
      className={cn('codicon', `codicon-${name}`, spin && 'codicon-modifier-spin', className)}
      style={{ fontSize: size }}
    />
  )
}
```

`webview/app/components/provider-avatar.tsx`:

```tsx
import { cn } from '@/lib/utils'

const PROVIDERS: Record<string, { monogram: string; hue: string }> = {
  claude: { monogram: 'C', hue: '#d97757' }
}

export function ProviderAvatar({ providerId, className }: { providerId: string; className?: string }) {
  const { monogram, hue } = PROVIDERS[providerId] ?? { monogram: providerId.slice(0, 1).toUpperCase(), hue: '#888888' }
  return (
    <span
      className={cn('inline-flex size-7 shrink-0 items-center justify-center rounded-md text-xs font-semibold', className)}
      // Provider tints are the one color not taken from the theme; mixing with the theme keeps them legible.
      style={{
        background: `color-mix(in srgb, ${hue} 22%, var(--background))`,
        color: `color-mix(in srgb, ${hue} 80%, var(--foreground))`
      }}
    >
      {monogram}
    </span>
  )
}
```

`webview/app/components/status-badge.tsx`:

```tsx
import type { SessionStatus } from '../../../src/sessions/store'
import { cn } from '@/lib/utils'

const BADGES: Record<SessionStatus, { label: string; className: string } | null> = {
  idle: null,
  running: { label: 'Running', className: 'bg-info/15 text-info' },
  'needs-input': { label: 'Input', className: 'bg-warning/15 text-warning' },
  error: { label: 'Error', className: 'bg-destructive/15 text-destructive' },
  stopped: { label: 'Stopped', className: 'bg-muted text-muted-foreground' }
}

export function StatusBadge({ status }: { status: SessionStatus }) {
  const badge = BADGES[status]
  if (!badge) return null
  return (
    <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-medium', badge.className)}>{badge.label}</span>
  )
}
```

`webview/app/components/file-pill.tsx`:

```tsx
import { send } from '../host'
import { fileName } from '../format'
import { Codicon } from './codicon'

export function FilePill({
  path,
  range,
  label,
  onRemove
}: {
  path: string
  range?: [number, number]
  label?: string
  onRemove?: () => void
}) {
  return (
    <span className="inline-flex max-w-full items-center gap-1 rounded-md border bg-muted px-1.5 py-0.5 text-xs">
      <button
        type="button"
        title={path}
        className="inline-flex min-w-0 items-center gap-1 hover:underline"
        onClick={() => send({ type: 'openFile', path, line: range?.[0] })}
      >
        <Codicon name="file" size={12} />
        <span className="truncate">
          {label ?? fileName(path)}
          {range ? ` · L${range[0]}–${range[1]}` : ''}
        </span>
      </button>
      {onRemove && (
        <button
          type="button"
          aria-label="Remove file from the next message"
          className="text-muted-foreground hover:text-foreground"
          onClick={onRemove}
        >
          <Codicon name="close" size={12} />
        </button>
      )}
    </span>
  )
}
```

- [ ] **Step 2: Header, empty state, status, and queue**

`webview/app/components/chat-header.tsx`:

```tsx
import type { ChatState } from '../state'
import { ProviderAvatar } from './provider-avatar'
import { StatusBadge } from './status-badge'

export function ChatHeader({ state }: { state: ChatState }) {
  if (!state.record) return null
  return (
    <header className="flex items-center gap-2.5 border-b px-4 py-2.5">
      <ProviderAvatar providerId={state.record.providerId} />
      <div className="min-w-0 flex-1">
        <div className="truncate font-semibold">{state.record.title}</div>
        <div className="truncate text-xs text-muted-foreground">{state.provider?.label ?? state.record.providerId}</div>
      </div>
      <StatusBadge status={state.status} />
    </header>
  )
}
```

`webview/app/components/empty-state.tsx`:

```tsx
import { Button } from '@/components/ui/button'
import type { ProviderInfo } from '../../../src/ui/protocol'
import { send } from '../host'
import { Codicon } from './codicon'
import { ProviderAvatar } from './provider-avatar'

export function EmptyState({ provider }: { provider?: ProviderInfo }) {
  const status = provider?.state.status
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-3 p-6 text-center">
      <ProviderAvatar providerId={provider?.id ?? 'claude'} className="size-10 text-base" />
      <div className="font-semibold">{provider?.label ?? 'Claude'}</div>
      {status === 'not-installed' ? (
        <p className="text-sm text-muted-foreground">
          The {provider?.label} CLI is not installed. <a href={provider?.installUrl}>Install it</a>, then reopen this view.
        </p>
      ) : status === 'signed-out' ? (
        <Button size="sm" onClick={() => send({ type: 'signIn' })}>
          Sign in
        </Button>
      ) : (
        <Button size="sm" onClick={() => send({ type: 'newChat' })}>
          <Codicon name="add" />
          New chat
        </Button>
      )}
    </div>
  )
}
```

`webview/app/components/working-status.tsx`:

```tsx
import { Shimmer } from '@/components/ai-elements/shimmer'
import type { SessionStatus } from '../../../src/sessions/store'
import { Codicon } from './codicon'

export function WorkingStatus({ status }: { status: SessionStatus }) {
  if (status === 'running') {
    return (
      <Shimmer as="div" className="px-1 text-xs">
        Working…
      </Shimmer>
    )
  }
  if (status === 'needs-input') {
    return (
      <div className="flex items-center gap-1.5 px-1 text-xs text-warning">
        <Codicon name="loading" size={12} spin />
        Waiting for your approval
      </div>
    )
  }
  return null
}
```

`webview/app/components/queue-list.tsx`:

```tsx
import type { QueuedPrompt } from '../../../src/sessions/manager'
import { promptText } from '../format'
import { send } from '../host'
import { Codicon } from './codicon'

export function QueueList({ queue }: { queue: QueuedPrompt[] }) {
  if (queue.length === 0) return null
  return (
    <div className="space-y-1">
      {queue.map((queued) => (
        <div key={queued.id} className="flex items-center gap-2 rounded-md border bg-card px-3 py-1.5 text-sm">
          <span className="text-xs text-muted-foreground">Queued</span>
          <span className="min-w-0 flex-1 truncate">{promptText(queued.parts)}</span>
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

- [ ] **Step 3: Composer**

`webview/app/components/composer.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { send } from '../host'
import type { ChatState } from '../state'
import { Codicon } from './codicon'
import { FilePill } from './file-pill'

export function Composer({ state }: { state: ChatState }) {
  const [text, setText] = useState('')
  const [includeContext, setIncludeContext] = useState(true)
  const busy = state.status === 'running' || state.status === 'needs-input'
  const context = includeContext ? state.editorContext : null

  // A file the user removed is offered again once they switch to another file.
  useEffect(() => setIncludeContext(true), [state.editorContext?.path])

  const submit = () => {
    if (!text.trim()) return
    send({ type: 'prompt', text, includeContext: context !== null })
    setText('')
  }

  return (
    <div className="rounded-xl border bg-input/40 focus-within:border-ring">
      {context && (
        <div className="px-3 pt-2">
          <FilePill
            path={context.path}
            range={context.range}
            label={context.label}
            onRemove={() => setIncludeContext(false)}
          />
        </div>
      )}
      <Textarea
        value={text}
        rows={1}
        placeholder={`Ask ${state.provider?.label ?? 'the agent'}…`}
        className="max-h-48 min-h-10 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0 dark:bg-transparent"
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault()
            submit()
          }
        }}
      />
      <div className="flex items-center gap-1 px-2 pb-2">
        <div className="flex-1" />
        {busy ? (
          <Button key="stop" size="icon-sm" variant="secondary" aria-label="Stop" onClick={() => send({ type: 'cancel' })}>
            <Codicon name="debug-stop" />
          </Button>
        ) : (
          <Button key="send" size="icon-sm" aria-label="Send" disabled={!text.trim()} onClick={submit}>
            <Codicon name="send" />
          </Button>
        )}
      </div>
    </div>
  )
}
```

While a turn runs, Enter still submits: the host queues the prompt. The `key`s make React remount the button when it switches, instead of animating the disabled Send style into Stop.

- [ ] **Step 4: Item components**

`webview/app/items/user-message.tsx`:

```tsx
import { Message, MessageContent } from '@/components/ai-elements/message'
import type { PromptPart, UserMessage } from '../../../src/core/types'
import { FilePill } from '../components/file-pill'
import { promptText } from '../format'

export function UserMessageView({ item }: { item: UserMessage }) {
  const files = item.parts.filter((part): part is Extract<PromptPart, { type: 'file' }> => part.type === 'file')
  return (
    <Message from="user">
      <MessageContent>
        <div className="whitespace-pre-wrap">{promptText(item.parts)}</div>
        {files.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {files.map((file) => (
              <FilePill key={file.path} path={file.path} range={file.range} />
            ))}
          </div>
        )}
      </MessageContent>
    </Message>
  )
}
```

`webview/app/items/assistant-message.tsx`:

```tsx
import { Message, MessageContent, MessageResponse } from '@/components/ai-elements/message'
import type { AssistantMessage } from '../../../src/core/types'

export function AssistantMessageView({ item }: { item: AssistantMessage }) {
  return (
    <Message from="assistant">
      <MessageContent>
        <MessageResponse isAnimating={item.streaming}>{item.text}</MessageResponse>
      </MessageContent>
    </Message>
  )
}
```

`webview/app/items/thought.tsx`:

```tsx
import { Reasoning, ReasoningContent, ReasoningTrigger } from '@/components/ai-elements/reasoning'
import type { Thought } from '../../../src/core/types'

export function ThoughtView({ item }: { item: Thought }) {
  return (
    <Reasoning isStreaming={item.streaming}>
      <ReasoningTrigger />
      <ReasoningContent>{item.text}</ReasoningContent>
    </Reasoning>
  )
}
```

`webview/app/items/tool-line.tsx` (plan 3 replaces this with collapsible tool cards):

```tsx
import type { ToolItem, ToolKind } from '../../../src/core/types'
import { Codicon } from '../components/codicon'

export const TOOL_ICONS: Record<ToolKind, string> = {
  read: 'file',
  edit: 'edit',
  execute: 'terminal',
  search: 'search',
  fetch: 'globe',
  mcp: 'plug',
  other: 'tools'
}

export function ToolStatusIcon({ status }: { status: ToolItem['status'] }) {
  if (status === 'running') return <Codicon name="loading" spin className="text-muted-foreground" />
  if (status === 'failed') return <Codicon name="error" className="text-destructive" />
  return <Codicon name="check" className="text-success" />
}

export function ToolLine({ item }: { item: ToolItem }) {
  return (
    <div className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs">
      <Codicon name={TOOL_ICONS[item.toolKind]} className="text-muted-foreground" />
      <span className="min-w-0 flex-1 truncate font-mono">{item.title}</span>
      <ToolStatusIcon status={item.status} />
    </div>
  )
}
```

`webview/app/items/diff-line.tsx` (plan 3 replaces this with diff cards):

```tsx
import type { DiffItem } from '../../../src/core/types'
import { Codicon } from '../components/codicon'
import { fileName } from '../format'

export function DiffLine({ item }: { item: DiffItem }) {
  return (
    <div className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs">
      <Codicon name="diff" className="text-muted-foreground" />
      <span className="min-w-0 flex-1 truncate font-mono" title={item.path}>
        {item.oldText === null ? 'Created' : 'Edited'} {fileName(item.path)}
      </span>
    </div>
  )
}
```

`webview/app/items/plan-list.tsx` (plan 3 replaces this with a plan card):

```tsx
import type { PlanItem } from '../../../src/core/types'
import { Codicon } from '../components/codicon'

const ICONS = { pending: 'circle-large-outline', in_progress: 'loading', done: 'pass-filled' } as const

export function PlanList({ item }: { item: PlanItem }) {
  return (
    <ul className="space-y-1 rounded-md border px-3 py-2 text-sm">
      {item.entries.map((entry, index) => (
        <li key={index} className="flex items-center gap-2">
          <Codicon name={ICONS[entry.status]} spin={entry.status === 'in_progress'} className="text-muted-foreground" />
          <span className={entry.status === 'done' ? 'text-muted-foreground line-through' : ''}>{entry.text}</span>
        </li>
      ))}
    </ul>
  )
}
```

`webview/app/items/approval-card.tsx`:

```tsx
import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import type { ApprovalItem, SessionItem } from '../../../src/core/types'
import { Codicon } from '../components/codicon'
import { send } from '../host'

function answer(item: ApprovalItem, optionId: string): void {
  send({ type: 'answer', itemId: item.id, optionId })
}

function Kbd({ children }: { children: string }) {
  return <kbd className="ml-1 rounded border border-current/30 px-1 text-[10px] leading-4 opacity-80">{children}</kbd>
}

export function ApprovalCard({ item }: { item: ApprovalItem }) {
  if (item.resolved) {
    const label =
      item.resolved === 'expired' ? 'Expired' : (item.options.find((option) => option.id === item.resolved)?.label ?? item.resolved)
    return (
      <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
        <Codicon name="shield" size={12} />
        <span className="truncate">{item.title}</span>
        <span>· {label}</span>
      </div>
    )
  }
  const [primary, ...others] = item.options.filter((option) => option.id !== 'deny')
  const deny = item.options.find((option) => option.id === 'deny')
  return (
    <div className="space-y-2.5 rounded-lg border border-warning/50 bg-warning/5 p-3">
      <div className="flex items-center gap-2 font-medium">
        <Codicon name="shield" className="text-warning" />
        {item.title}
      </div>
      {item.detail && (
        <pre className="max-h-40 overflow-auto rounded-md bg-code px-3 py-2 text-xs whitespace-pre-wrap">{item.detail}</pre>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {primary && (
          <Button size="sm" onClick={() => answer(item, primary.id)}>
            {primary.label}
            <Kbd>⏎</Kbd>
          </Button>
        )}
        {others.map((option) => (
          <Button key={option.id} size="sm" variant="secondary" onClick={() => answer(item, option.id)}>
            {option.label}
          </Button>
        ))}
        {deny && (
          <Button size="sm" variant="ghost" className="ml-auto" onClick={() => answer(item, deny.id)}>
            {deny.label}
            <Kbd>esc</Kbd>
          </Button>
        )}
      </div>
    </div>
  )
}

/** Enter allows and Escape denies the oldest pending approval, unless the user is typing. */
export function useApprovalKeys(items: SessionItem[]): void {
  const pending = items.find((item): item is ApprovalItem => item.kind === 'approval' && !item.resolved)
  useEffect(() => {
    if (!pending) return
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.closest('textarea, input, [contenteditable="true"]')) return
      const allow = pending.options.find((option) => option.id !== 'deny')
      if (event.key === 'Enter' && allow) answer(pending, allow.id)
      else if (event.key === 'Escape') answer(pending, 'deny')
      else return
      event.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pending])
}
```

`webview/app/items/notice.tsx`:

```tsx
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { NoticeItem } from '../../../src/core/types'
import { Codicon } from '../components/codicon'
import { send } from '../host'

const TONES = {
  error: { icon: 'error', className: 'border-destructive/50 bg-destructive/5' },
  warning: { icon: 'warning', className: 'border-warning/50 bg-warning/5' },
  info: { icon: 'info', className: 'bg-muted' }
} as const

export function NoticeView({ item }: { item: NoticeItem }) {
  const tone = TONES[item.level]
  return (
    <div className={cn('flex items-start gap-2 rounded-md border px-3 py-2 text-sm', tone.className)}>
      <Codicon name={tone.icon} className="mt-0.5" />
      <div className="min-w-0 flex-1 whitespace-pre-wrap">{item.text}</div>
      {item.action === 'sign-in' && (
        <Button size="xs" variant="secondary" onClick={() => send({ type: 'signIn' })}>
          Sign in
        </Button>
      )}
    </div>
  )
}
```

`webview/app/items/item-view.tsx`:

```tsx
import type { SessionItem } from '../../../src/core/types'
import { ApprovalCard } from './approval-card'
import { AssistantMessageView } from './assistant-message'
import { DiffLine } from './diff-line'
import { NoticeView } from './notice'
import { PlanList } from './plan-list'
import { ThoughtView } from './thought'
import { ToolLine } from './tool-line'
import { UserMessageView } from './user-message'

export function ItemView({ item }: { item: SessionItem }) {
  switch (item.kind) {
    case 'message':
      return item.role === 'user' ? <UserMessageView item={item} /> : <AssistantMessageView item={item} />
    case 'thought':
      return <ThoughtView item={item} />
    case 'tool':
      return <ToolLine item={item} />
    case 'diff':
      return <DiffLine item={item} />
    case 'plan':
      return <PlanList item={item} />
    case 'approval':
      return <ApprovalCard item={item} />
    case 'notice':
      return <NoticeView item={item} />
    case 'turn':
      return null
  }
}
```

- [ ] **Step 5: The app**

`webview/app/App.tsx` (full replacement):

```tsx
import { useEffect, useReducer } from 'react'
import { Conversation, ConversationContent, ConversationScrollButton } from '@/components/ai-elements/conversation'
import { TooltipProvider } from '@/components/ui/tooltip'
import { ChatHeader } from './components/chat-header'
import { Composer } from './components/composer'
import { EmptyState } from './components/empty-state'
import { QueueList } from './components/queue-list'
import { WorkingStatus } from './components/working-status'
import { onHostMessage, saveState, send } from './host'
import { useApprovalKeys } from './items/approval-card'
import { ItemView } from './items/item-view'
import { initialState, reduce } from './state'

export function App() {
  const [state, dispatch] = useReducer(reduce, initialState)

  useEffect(() => {
    const unsubscribe = onHostMessage(dispatch)
    send({ type: 'ready' })
    return unsubscribe
  }, [])

  useEffect(() => {
    if (state.sessionId) saveState({ sessionId: state.sessionId })
  }, [state.sessionId])

  useApprovalKeys(state.items)

  if (state.empty) return <EmptyState provider={state.provider} />

  return (
    <TooltipProvider>
      <div className="flex h-screen flex-col">
        <ChatHeader state={state} />
        <Conversation className="min-h-0 flex-1">
          <ConversationContent className="gap-3 px-4 py-4">
            {state.items.map((item) => (
              <ItemView key={item.id} item={item} />
            ))}
          </ConversationContent>
          <ConversationScrollButton />
        </Conversation>
        <div className="space-y-2 px-3 pb-3">
          <WorkingStatus status={state.status} />
          <QueueList queue={state.queue} />
          <Composer state={state} />
        </div>
      </div>
    </TooltipProvider>
  )
}
```

- [ ] **Step 6: Type-check, build, and review the screenshots**

Run:

```bash
pnpm typecheck && pnpm test && pnpm build:preview && pnpm screenshot dark && pnpm screenshot light
```

Expected: typecheck clean, tests pass, two PNGs written. Open both images (an agent can read PNG files) and check against the chat-tab mockup:
- header with the "C" avatar, title "Fix flaky retry test", and an amber "Input" badge;
- a right-aligned user bubble with the text and an `api.test.ts · L40–72` pill;
- a collapsed "Thought for…" reasoning row;
- three tool lines (two green checks, one red error);
- the assistant reply with inline code and a highlighted TypeScript block;
- an "Edited retry.ts" line;
- an amber-bordered approval card with the command in a code box and the *Allow once ⏎*, *Always allow*, *Deny esc* buttons;
- "Waiting for your approval", the queued message, and the composer with the `src/api.test.ts · L40–72` pill and a Stop button.

The light screenshot must show the same layout with dark text on white. Any element that renders unstyled, invisible, or with a hard-coded color is a defect to fix before committing.

- [ ] **Step 7: Commit**

```bash
git add webview/app
git commit -m "feat(webview): render sessions with AI Elements and themed shadcn cards"
```

---

### Task 5: Editor context and chat surfaces in the host

**Files:**
- Create: `src/ui/editor-context.ts`
- Create: `src/ui/chat-surfaces.ts`

These files import `vscode`, so they are verified by type-checking here and by the manual check in Task 6.

- [ ] **Step 1: Editor context tracker**

`src/ui/editor-context.ts`:

```ts
import * as vscode from 'vscode'
import type { PromptPart } from '../core/types'
import type { EditorContext } from './protocol'

/** The file and selection a prompt refers to. A chat webview takes focus, so the last file editor is remembered. */
export class EditorContextTracker implements vscode.Disposable {
  private last: vscode.TextEditor | undefined
  private readonly changed = new vscode.EventEmitter<EditorContext | null>()
  readonly onDidChange = this.changed.event
  private readonly subscriptions: vscode.Disposable[]

  constructor() {
    const active = vscode.window.activeTextEditor
    this.last = isFileEditor(active) ? active : undefined
    this.subscriptions = [
      this.changed,
      vscode.window.onDidChangeActiveTextEditor((editor) => {
        if (!isFileEditor(editor)) return
        this.last = editor
        this.changed.fire(this.current())
      }),
      vscode.window.onDidChangeTextEditorSelection(({ textEditor }) => {
        if (textEditor === this.last) this.changed.fire(this.current())
      }),
      vscode.workspace.onDidCloseTextDocument((document) => {
        if (document !== this.last?.document) return
        this.last = undefined
        this.changed.fire(this.current())
      })
    ]
  }

  current(): EditorContext | null {
    const editor = this.last ?? vscode.window.visibleTextEditors.find(isFileEditor)
    if (!editor) return null
    const { selection } = editor
    return {
      path: editor.document.uri.fsPath,
      label: vscode.workspace.asRelativePath(editor.document.uri),
      range: selection.isEmpty ? undefined : [selection.start.line + 1, selection.end.line + 1]
    }
  }

  part(): PromptPart | null {
    const context = this.current()
    return context ? { type: 'file', path: context.path, range: context.range } : null
  }

  dispose(): void {
    for (const subscription of this.subscriptions) subscription.dispose()
  }
}

function isFileEditor(editor: vscode.TextEditor | undefined): editor is vscode.TextEditor {
  return editor?.document.uri.scheme === 'file'
}
```

- [ ] **Step 2: Chat surfaces**

`src/ui/chat-surfaces.ts`:

```ts
import { randomBytes } from 'node:crypto'
import * as vscode from 'vscode'
import type { Disposable } from '../core/emitter'
import type { PromptPart, ProviderDefinition, ProviderState } from '../core/types'
import type { Env } from '../env'
import type { SessionManager } from '../sessions/manager'
import type { EditorContextTracker } from './editor-context'
import type { HostMessage, WebviewMessage } from './protocol'

export const PANEL_TYPE = 'agentdeck.chatPanel'
export const SIDEBAR_VIEW = 'agentdeck.chat'
const SIDEBAR_SESSION_KEY = 'agentdeck.sidebarSession'
const DEFAULT_PROVIDER = 'claude'

type SurfaceKind = 'panel' | 'view'

/** One webview showing one session at a time. */
type Surface = {
  readonly webview: vscode.Webview
  readonly kind: SurfaceKind
  sessionId?: string
  subscription?: Disposable
  listener?: vscode.Disposable
}

/** Editor tabs and the sidebar chat. Each subscribes to a session and relays its events. */
export class ChatSurfaces
  implements vscode.WebviewViewProvider, vscode.WebviewPanelSerializer<{ sessionId?: string }>, vscode.Disposable
{
  private readonly panels = new Map<string, { panel: vscode.WebviewPanel; surface: Surface }>()
  private sidebar: Surface | undefined
  private readonly states = new Map<string, ProviderState>()
  private readonly subscriptions: { dispose(): void }[] = []

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly manager: SessionManager,
    private readonly providers: ReadonlyMap<string, ProviderDefinition>,
    private readonly env: () => Promise<Env>,
    private readonly editor: EditorContextTracker
  ) {
    this.subscriptions.push(
      manager.onDidChange(() => this.refreshTitles()),
      editor.onDidChange((editorContext) => this.broadcast({ type: 'editorContext', context: editorContext }))
    )
  }

  async newChat(where: SurfaceKind): Promise<void> {
    const record = await this.manager.create(DEFAULT_PROVIDER)
    if (where === 'panel') this.openPanel(record.id)
    else await this.showInSidebar(record.id)
  }

  openPanel(sessionId: string): void {
    const open = this.panels.get(sessionId)
    if (open) return open.panel.reveal()
    const panel = vscode.window.createWebviewPanel(PANEL_TYPE, this.title(sessionId), vscode.ViewColumn.Beside, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [this.assets()]
    })
    this.attachPanel(panel, sessionId)
  }

  async showInSidebar(sessionId: string): Promise<void> {
    await this.context.workspaceState.update(SIDEBAR_SESSION_KEY, sessionId)
    await vscode.commands.executeCommand(`${SIDEBAR_VIEW}.focus`)
    if (this.sidebar) this.show(this.sidebar, sessionId)
  }

  openSidebarInEditor(): void {
    if (this.sidebar?.sessionId) this.openPanel(this.sidebar.sessionId)
  }

  resolveWebviewView(view: vscode.WebviewView): void {
    view.webview.options = { enableScripts: true, localResourceRoots: [this.assets()] }
    view.webview.html = this.html(view.webview, 'view')
    const surface = this.surface(view.webview, 'view', this.sidebarSession())
    this.sidebar = surface
    view.onDidDispose(() => {
      this.release(surface)
      if (this.sidebar === surface) this.sidebar = undefined
    })
  }

  async deserializeWebviewPanel(panel: vscode.WebviewPanel, state: { sessionId?: string } | undefined): Promise<void> {
    if (!state?.sessionId || !this.exists(state.sessionId)) return panel.dispose()
    this.attachPanel(panel, state.sessionId)
  }

  dispose(): void {
    for (const subscription of this.subscriptions) subscription.dispose()
    for (const { surface } of this.panels.values()) this.release(surface)
    if (this.sidebar) this.release(this.sidebar)
  }

  private attachPanel(panel: vscode.WebviewPanel, sessionId: string): void {
    panel.webview.options = { enableScripts: true, localResourceRoots: [this.assets()] }
    panel.webview.html = this.html(panel.webview, 'panel')
    panel.title = this.title(sessionId)
    const surface = this.surface(panel.webview, 'panel', sessionId)
    this.panels.set(sessionId, { panel, surface })
    panel.onDidDispose(() => {
      this.release(surface)
      this.panels.delete(sessionId)
    })
  }

  private surface(webview: vscode.Webview, kind: SurfaceKind, sessionId: string | undefined): Surface {
    const surface: Surface = { webview, kind, sessionId }
    surface.listener = webview.onDidReceiveMessage((message: WebviewMessage) =>
      this.handle(surface, message).catch((error: unknown) =>
        vscode.window.showErrorMessage(`AgentDeck: ${error instanceof Error ? error.message : String(error)}`)
      )
    )
    return surface
  }

  private release(surface: Surface): void {
    surface.subscription?.dispose()
    surface.listener?.dispose()
  }

  private async handle(surface: Surface, message: WebviewMessage): Promise<void> {
    const sessionId = surface.sessionId
    switch (message.type) {
      case 'ready':
        this.post(surface, { type: 'editorContext', context: this.editor.current() })
        await this.postProvider(surface)
        if (sessionId) this.show(surface, sessionId)
        else this.post(surface, { type: 'empty' })
        return
      case 'prompt': {
        const target = sessionId ?? (await this.createFor(surface))
        const parts: PromptPart[] = [{ type: 'text', text: message.text }]
        const file = message.includeContext ? this.editor.part() : null
        if (file) parts.push(file)
        return this.manager.prompt(target, parts)
      }
      case 'cancel':
        if (sessionId) await this.manager.cancel(sessionId)
        return
      case 'answer':
        if (sessionId) this.manager.answer(sessionId, message.itemId, message.optionId)
        return
      case 'removeQueued':
        if (sessionId) this.manager.removeQueued(sessionId, message.queuedId)
        return
      case 'newChat':
        return this.newChat(surface.kind)
      case 'signIn':
        return this.signIn(surface)
      case 'openFile': {
        const document = await vscode.workspace.openTextDocument(message.path)
        const line = Math.max((message.line ?? 1) - 1, 0)
        await vscode.window.showTextDocument(document, {
          viewColumn: vscode.ViewColumn.One,
          selection: new vscode.Range(line, 0, line, 0)
        })
        return
      }
    }
  }

  private show(surface: Surface, sessionId: string): void {
    surface.subscription?.dispose()
    surface.sessionId = sessionId
    surface.subscription = this.manager.subscribe(sessionId, (event) =>
      this.post(surface, { type: 'session', sessionId, event })
    )
    void this.manager.warm(sessionId)
  }

  private async createFor(surface: Surface): Promise<string> {
    const record = await this.manager.create(DEFAULT_PROVIDER)
    if (surface.kind === 'view') await this.showInSidebar(record.id)
    else this.show(surface, record.id)
    return record.id
  }

  private async postProvider(surface: Surface): Promise<void> {
    const providerId = this.providerOf(surface.sessionId)
    const provider = this.providers.get(providerId)
    if (!provider) return
    const state = this.states.get(providerId) ?? (await this.probe(provider))
    this.post(surface, {
      type: 'provider',
      provider: {
        id: provider.id,
        label: provider.label,
        installUrl: provider.cli.installUrl,
        capabilities: [...provider.capabilities],
        modes: provider.modes,
        state
      }
    })
  }

  private async probe(provider: ProviderDefinition): Promise<ProviderState> {
    const state = await provider.probe(await this.env())
    this.states.set(provider.id, state)
    return state
  }

  /** Runs the provider's own login in a terminal, then re-checks once the terminal closes. */
  private async signIn(surface: Surface): Promise<void> {
    const provider = this.providers.get(this.providerOf(surface.sessionId))
    if (!provider) return
    const terminal = vscode.window.createTerminal({ name: `${provider.label} sign-in` })
    terminal.show()
    terminal.sendText(provider.signInCommand)
    const closed = vscode.window.onDidCloseTerminal((closedTerminal) => {
      if (closedTerminal !== terminal) return
      closed.dispose()
      this.states.delete(provider.id)
      void this.postProvider(surface)
    })
  }

  private refreshTitles(): void {
    for (const [sessionId, { panel, surface }] of this.panels) {
      const title = this.title(sessionId)
      if (panel.title !== title) panel.title = title
      this.post(surface, { type: 'title', sessionId, title })
    }
    const sidebarSession = this.sidebar?.sessionId
    if (this.sidebar && sidebarSession) {
      this.post(this.sidebar, { type: 'title', sessionId: sidebarSession, title: this.title(sidebarSession) })
    }
  }

  private broadcast(message: HostMessage): void {
    for (const { surface } of this.panels.values()) this.post(surface, message)
    if (this.sidebar) this.post(this.sidebar, message)
  }

  private post(surface: Surface, message: HostMessage): void {
    void surface.webview.postMessage(message)
  }

  private sidebarSession(): string | undefined {
    const id = this.context.workspaceState.get<string>(SIDEBAR_SESSION_KEY)
    return id && this.exists(id) ? id : undefined
  }

  private exists(sessionId: string): boolean {
    return this.manager.list().some(({ record }) => record.id === sessionId)
  }

  private providerOf(sessionId: string | undefined): string {
    if (!sessionId) return DEFAULT_PROVIDER
    return this.manager.list().find(({ record }) => record.id === sessionId)?.record.providerId ?? DEFAULT_PROVIDER
  }

  private title(sessionId: string): string {
    return this.manager.list().find(({ record }) => record.id === sessionId)?.record.title ?? 'AgentDeck'
  }

  private assets(): vscode.Uri {
    return vscode.Uri.joinPath(this.context.extensionUri, 'dist', 'webview')
  }

  private html(webview: vscode.Webview, kind: SurfaceKind): string {
    const nonce = randomBytes(16).toString('base64')
    const asset = (name: string) => webview.asWebviewUri(vscode.Uri.joinPath(this.assets(), name))
    // Scripts run by nonce; the entry module imports its code-split chunks from the webview origin.
    // Styles allow inline because React, Radix, and Shiki set style attributes.
    const csp = [
      "default-src 'none'",
      `img-src ${webview.cspSource} data:`,
      `font-src ${webview.cspSource}`,
      `style-src ${webview.cspSource} 'unsafe-inline'`,
      `script-src 'nonce-${nonce}' ${webview.cspSource}`
    ].join('; ')
    return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="${asset('codicon.css')}">
<link rel="stylesheet" href="${asset('webview.css')}">
</head>
<body data-surface="${kind}">
<div id="root"></div>
<script type="module" nonce="${nonce}" src="${asset('main.js')}"></script>
</body>
</html>`
  }
}
```

- [ ] **Step 3: Typecheck**

Run: `pnpm typecheck`
Expected: clean. `manager.onDidChange(...)` returns the core `Disposable`, which fits the `{ dispose(): void }[]` list.

- [ ] **Step 4: Commit**

```bash
git add src/ui/editor-context.ts src/ui/chat-surfaces.ts
git commit -m "feat(ui): host chats in editor tabs and the sidebar"
```

---

### Task 6: Activation, contributions, and removing the POC

**Files:**
- Modify: `src/extension.ts` (full replacement)
- Modify: `package.json` (`activationEvents`, `contributes`)
- Create: `media/agentdeck.svg`
- Delete: `src/claude-session.ts`, `media/chat.js`, `media/chat.css`
- Modify: `README.md` (status and try-it steps)

- [ ] **Step 1: Activation**

`src/extension.ts`:

```ts
import { homedir } from 'node:os'
import { join } from 'node:path'
import * as vscode from 'vscode'
import { captureEnv, type Env } from './env'
import { claudeProvider } from './providers/claude/provider'
import { SessionManager } from './sessions/manager'
import { SessionStore } from './sessions/store'
import { ChatSurfaces, PANEL_TYPE, SIDEBAR_VIEW } from './ui/chat-surfaces'
import { EditorContextTracker } from './ui/editor-context'

let manager: SessionManager | undefined

export function activate(context: vscode.ExtensionContext): void {
  let env: Promise<Env> | undefined
  const getEnv = () => (env ??= captureEnv())
  const providers = new Map([[claudeProvider.id, claudeProvider]])
  const storage = (context.storageUri ?? context.globalStorageUri).fsPath
  manager = new SessionManager({
    providers,
    store: new SessionStore(context.workspaceState),
    journalDir: join(storage, 'sessions'),
    cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? homedir(),
    env: getEnv
  })
  const editor = new EditorContextTracker()
  const surfaces = new ChatSurfaces(context, manager, providers, getEnv, editor)
  context.subscriptions.push(
    editor,
    surfaces,
    vscode.window.registerWebviewViewProvider(SIDEBAR_VIEW, surfaces, { webviewOptions: { retainContextWhenHidden: true } }),
    vscode.window.registerWebviewPanelSerializer(PANEL_TYPE, surfaces),
    vscode.commands.registerCommand('agentdeck.newChat', () => surfaces.newChat('panel')),
    vscode.commands.registerCommand('agentdeck.sidebar.newChat', () => surfaces.newChat('view')),
    vscode.commands.registerCommand('agentdeck.openInEditor', () => surfaces.openSidebarInEditor())
  )
}

export async function deactivate(): Promise<void> {
  await manager?.dispose()
}
```

- [ ] **Step 2: Contributions**

In `package.json`, replace `"activationEvents": []` and the whole `"contributes"` object with:

```json
  "activationEvents": [
    "onWebviewPanel:agentdeck.chatPanel"
  ],
  "contributes": {
    "viewsContainers": {
      "activitybar": [
        { "id": "agentdeck", "title": "AgentDeck", "icon": "media/agentdeck.svg" }
      ]
    },
    "views": {
      "agentdeck": [
        { "type": "webview", "id": "agentdeck.chat", "name": "Chat" }
      ]
    },
    "commands": [
      { "command": "agentdeck.newChat", "title": "New Claude Chat in Editor", "category": "AgentDeck", "icon": "$(add)" },
      { "command": "agentdeck.sidebar.newChat", "title": "New Chat", "category": "AgentDeck", "icon": "$(add)" },
      { "command": "agentdeck.openInEditor", "title": "Open Chat in Editor", "category": "AgentDeck", "icon": "$(link-external)" }
    ],
    "menus": {
      "view/title": [
        { "command": "agentdeck.sidebar.newChat", "when": "view == agentdeck.chat", "group": "navigation@1" },
        { "command": "agentdeck.openInEditor", "when": "view == agentdeck.chat", "group": "navigation@2" }
      ]
    }
  },
```

- [ ] **Step 3: Activity bar icon**

`media/agentdeck.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4M7 9h6M7 12h10"/></svg>
```

- [ ] **Step 4: Remove the POC**

```bash
git rm src/claude-session.ts media/chat.js media/chat.css
grep -rn "claude-session\|media/chat" src scripts test esbuild.mjs package.json || echo CLEAN
```

Expected: `CLEAN`.

- [ ] **Step 5: README**

In `README.md`, replace the `**Status:**` paragraph with:

```markdown
**Status:** MVP in progress. Claude chats run in editor tabs and in the AgentDeck sidebar, persist across reloads, and resume where they left off. Codex, the sessions list, and the model, mode, and MCP controls are next (see the MVP plans).
```

and replace the line `Reload VS Code, open a file, and run **AgentDeck: New Claude Chat** from the command palette.` with:

```markdown
Reload VS Code, then open the AgentDeck view in the activity bar, or run **AgentDeck: New Claude Chat in Editor** from the command palette.

`pnpm build:preview && pnpm screenshot dark` renders the chat UI with sample data to `dist/preview/screenshot-dark.png` (needs Playwright's headless Chromium).
```

- [ ] **Step 6: Verify everything that can run headless**

Run:

```bash
pnpm typecheck && pnpm test && pnpm build && pnpm run package && node dist/smoke.js
```

Expected: typecheck clean; all tests pass; the VSIX is packaged and lists `extension/dist/webview/main.js` (`unzip -l agentdeck-0.0.1.vsix | grep webview/main.js`); the smoke prints `SMOKE OK`.

- [ ] **Step 7: Commit**

```bash
git add -A src package.json media README.md
git commit -m "feat: open chats in tabs and the sidebar; remove the POC UI"
```

- [ ] **Step 8: Hand off for the manual check**

Stop and ask the user to run this check, since it needs a VS Code window:
1. `code --install-extension agentdeck-0.0.1.vsix --force`, then reload VS Code.
2. Open the AgentDeck activity bar view: it shows Claude with *New chat* (or *Sign in*).
3. Start a chat from the sidebar, open a file with a selection, and ask Claude to edit it. Expect the file pill in the composer, streamed reply, reasoning row, tool lines, an approval card (Enter allows), and the edit applied.
4. Send a second message while Claude works: it shows as *Queued* and sends after the turn.
5. *Open Chat in Editor* (view title button): the same session opens in a tab, and both update live.
6. Reload the window: the tab comes back with its history, and the next message continues the conversation.
7. Switch to a light theme: the chat follows it.

## Done when

- `pnpm typecheck`, `pnpm test`, and `node dist/smoke.js` pass.
- The dark and light preview screenshots match the checklist in Task 4.
- The user has run the manual check in Task 6 Step 8.
