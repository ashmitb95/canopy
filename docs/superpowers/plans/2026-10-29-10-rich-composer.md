# Plan 10: Rich composer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first. Plans 1–9 are complete.

**Goal:** Replace the composer's textarea with the rich composer from the spec (*Composer* section): `@` file mentions from a workspace search, `/` commands and skills from the session's command list, attachments through *Upload from computer…* and *Add file from workspace…*, pasted images, and large pastes collapsed into a pill. Prompts carry these as `PromptPart`s all the way to each provider: Claude gets image blocks, Codex gets skill and local-image inputs, ACP agents get image blocks when they accept them.

**Architecture:** The editor is TipTap 3 with a stripped StarterKit, one `Mention` extension with two triggers (`@` → file, `/` → command), and two inline atom nodes (`imageAttachment`, `pastedText`). Suggestion menus are React components mounted by TipTap's own `props.mount()` (Floating UI positioning). Enter sends unless a menu is open. `toParts()` turns the editor's JSON into `PromptPart[]` (pure, tested). The webview asks the host for file matches and attachments through a small request/reply channel. Images are copied into the extension's storage (`<storage>/attachments/<uuid>.<ext>`) and referenced by path; the transcript shows them through a webview URI of that folder. Each provider lists its commands as a `commands` fact.

**Tech Stack:** TipTap 3.32.0 (`@tiptap/core`, `@tiptap/react`, `@tiptap/pm`, `@tiptap/starter-kit`, `@tiptap/extension-mention`, `@tiptap/extension-placeholder`, `@tiptap/suggestion`).

**Verified before writing** (2026-10-29, scratch project):
- The editor code in Task 4 type-checks against TipTap 3.32.0 and renders in headless Chromium: `Mention.configure({ suggestions: [...] })` takes several triggers, each with its own `pluginKey`; inserted mentions carry `mentionSuggestionChar`; the atom node renders as a non-editable pill. `@tiptap/core` must be a direct dependency (pnpm is strict).
- `SuggestionProps.mount(element)` positions the popup and returns an unmount function; `ReactRenderer` renders the menu.
- Claude's `supportedCommands()` returns `{ name, description, argumentHint }[]`. Codex's `skills/list { cwds }` returns `{ data: [{ skills: [{ name, description, shortDescription?, path, enabled }] }] }`, and a skill is invoked with the input `{ type: 'skill', name, path }`; images go as `{ type: 'localImage', path }`. ACP agents send `available_commands_update { availableCommands: [{ name, description }] }`; Grok advertises `promptCapabilities.image: true` and takes `{ type: 'image', mimeType, data }` blocks.
- Codicons used: `attach`, `cloud-upload`, `mention`, `file-media`.

---

## File structure

| File | Responsibility |
|---|---|
| `src/core/types.ts` | `command`, `pasted`, `image` prompt parts; `commands` fact |
| `src/providers/encode.ts` | Text encoding of all parts; image helper |
| `src/providers/{claude,codex,acp}/provider.ts` | Commands facts; images and skills per provider |
| `src/providers/acp/translate.ts` | `available_commands_update` type |
| `src/ui/protocol.ts`, `webview/app/state.ts` | Prompt parts; request/reply; assets |
| `src/ui/rank-files.ts`, `src/ui/file-search.ts` | The `@` menu's file list |
| `src/ui/attachments.ts` | Attachment store |
| `src/ui/chat-surfaces.ts` | Requests, attachments folder in the webview roots |
| `webview/app/host.ts` | `ask()` request/reply |
| `webview/app/composer/{prompt-document,nodes,suggestion-menu,prompt-editor}.tsx?` | The editor |
| `webview/app/components/composer.tsx`, `webview/app/items/{user-message,turn-footer}.tsx`, `webview/app/assets.ts` | Wiring and transcript rendering |
| `webview/theme.css` | Editor and pill styles |

---

### Task 1: Prompt parts and encoding

**Files:**
- Modify: `src/core/types.ts`, `src/providers/encode.ts`
- Test: `test/providers/encode.test.ts` (tests added)

- [ ] **Step 1: Write the failing tests**

In `test/providers/encode.test.ts`, change the import to `import { encodePrompt, imageParts } from '../../src/providers/encode'` and add inside the `describe` block:

```ts
  it('puts slash commands first', () => {
    expect(encodePrompt([{ type: 'command', name: 'review' }, { type: 'text', text: 'focus on the API' }], '/w')).toBe('/review focus on the API')
  })

  it('includes pasted text and leaves images out of the text', () => {
    const parts = [
      { type: 'text' as const, text: 'Why does this fail?' },
      { type: 'pasted' as const, text: 'Error: boom\n  at x' },
      { type: 'image' as const, path: '/s/a.png', mimeType: 'image/png', name: 'a.png' }
    ]
    expect(encodePrompt(parts, '/w')).toBe('Why does this fail?\n\nError: boom\n  at x')
    expect(imageParts(parts)).toEqual([{ type: 'image', path: '/s/a.png', mimeType: 'image/png', name: 'a.png' }])
  })
```

Run: `pnpm test test/providers/encode.test.ts` → FAIL.

- [ ] **Step 2: Types**

In `src/core/types.ts`, replace `PromptPart` with:

```ts
export type PromptPart =
  | { type: 'text'; text: string }
  | { type: 'file'; path: string; range?: [number, number] }
  | { type: 'command'; name: string }
  | { type: 'pasted'; text: string }
  /** An image in AgentDeck's attachment store. */
  | { type: 'image'; path: string; mimeType: string; name: string }
```

and add, before `SessionFact`:

```ts
/** A slash command or skill the composer's `/` menu offers. */
export type CommandOption = { name: string; description?: string }
```

and to `SessionFact`: `| { kind: 'commands'; items: CommandOption[] }`.

- [ ] **Step 3: Encoding**

In `src/providers/encode.ts`, replace `encodePrompt` and its doc comment with:

```ts
/** The prompt as text: slash commands lead, files become editor-context blocks, images travel separately. */
export function encodePrompt(parts: PromptPart[], cwd: string): string {
  const commands = parts.flatMap((part) => (part.type === 'command' ? [`/${part.name}`] : []))
  const body = parts
    .flatMap((part) => {
      switch (part.type) {
        case 'text':
        case 'pasted':
          return [part.text]
        case 'file':
          return [editorContext(part.path, part.range, cwd)]
        default:
          return []
      }
    })
    .join('\n\n')
  return commands.length > 0 ? [commands.join(' '), body].filter(Boolean).join(' ') : body
}

export function imageParts(parts: PromptPart[]): Extract<PromptPart, { type: 'image' }>[] {
  return parts.filter((part): part is Extract<PromptPart, { type: 'image' }> => part.type === 'image')
}
```

Run: `pnpm test && pnpm typecheck` → PASS; typecheck may flag `webview/app/format.ts`'s `promptText` or other switch statements over `PromptPart`; fix only by handling the new part types where the compiler points (no behaviour changes beyond ignoring them). Report each.

- [ ] **Step 4: Commit**

```bash
git add src test
git commit -m "feat: add command, pasted, and image prompt parts"
```

---

### Task 2: Commands and images per provider

**Files:**
- Modify: `src/providers/claude/provider.ts`, `src/providers/codex/provider.ts`, `src/providers/acp/provider.ts`, `src/providers/acp/translate.ts`

Verified by typecheck here and by the live smokes in Task 6.

- [ ] **Step 1: Claude**

In `src/providers/claude/provider.ts`:
- add `import { readFileSync } from 'node:fs'` and change the encode import to `import { encodePrompt, imageParts } from '../encode'`;
- replace the `inbox.push({...})` call in `prompt` with:

```ts
    const text = encodePrompt(parts, this.options.cwd)
    const images = imageParts(parts)
    const content =
      images.length === 0
        ? text
        : [
            { type: 'text' as const, text },
            ...images.map((image) => ({
              type: 'image' as const,
              source: {
                type: 'base64' as const,
                media_type: image.mimeType as 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp',
                data: readFileSync(image.path).toString('base64')
              }
            }))
          ]
    this.inbox.push({ type: 'user', message: { role: 'user', content }, parent_tool_use_id: null })
```

- in `loadFacts`, right after the `model` fact is fired, add:

```ts
    try {
      const commands = await this.query.supportedCommands()
      this.facts.fire({
        kind: 'commands',
        items: commands.map((command) => ({ name: command.name, description: command.description || undefined }))
      })
    } catch {
      // The / menu then lists nothing.
    }
```

- [ ] **Step 2: Codex**

In `src/providers/codex/provider.ts`:
- change the encode import to `import { encodePrompt, imageParts } from '../encode'`;
- add a field `private readonly skills = new Map<string, string>()` (skill name → path);
- replace the `input:` line in `prompt` with:

```ts
      input: [
        ...parts.flatMap((part) =>
          part.type === 'command' && this.skills.has(part.name)
            ? [{ type: 'skill', name: part.name, path: this.skills.get(part.name) }]
            : []
        ),
        {
          type: 'text',
          text: encodePrompt(
            parts.filter((part) => !(part.type === 'command' && this.skills.has(part.name))),
            this.options.cwd
          ),
          text_elements: []
        },
        ...imageParts(parts).map((image) => ({ type: 'localImage', path: image.path }))
      ],
```

- in `loadFacts`, after the `model` fact, add:

```ts
    try {
      const { data } = await this.rpc.request<{
        data: { skills: { name: string; description: string; shortDescription?: string; path: string; enabled: boolean }[] }[]
      }>('skills/list', { cwds: [this.options.cwd] })
      const skills = data.flatMap((entry) => entry.skills).filter((skill) => skill.enabled)
      for (const skill of skills) this.skills.set(skill.name, skill.path)
      this.facts.fire({
        kind: 'commands',
        items: skills.map((skill) => ({ name: skill.name, description: skill.shortDescription ?? skill.description }))
      })
    } catch {
      // The / menu then lists nothing.
    }
```

- [ ] **Step 3: ACP**

In `src/providers/acp/translate.ts`, replace the last member of the `SessionUpdate` union with:

```ts
  | { sessionUpdate: 'available_commands_update'; availableCommands?: { name: string; description?: string | null }[] }
  | { sessionUpdate: 'session_info_update' | 'current_mode_update' | 'usage_update' }
```

In `src/providers/acp/provider.ts`:
- add `import { randomUUID } from 'node:crypto'` and `import { readFileSync } from 'node:fs'`; add `CommandOption` to the core type import; change the encode import to `import { encodePrompt, imageParts } from '../encode'`;
- add fields:

```ts
  private imagesAccepted = false
  private commands: CommandOption[] = []
```

- replace the `rpc.onNotification(...)` call in the constructor with:

```ts
    rpc.onNotification(({ method, params }) => {
      if (method !== 'session/update') return
      const update = (params as { update: SessionUpdate }).update
      if (update.sessionUpdate === 'available_commands_update') {
        this.commands = (update.availableCommands ?? []).map((command) => ({
          name: command.name,
          description: command.description ?? undefined
        }))
        this.facts.fire({ kind: 'commands', items: this.commands })
      } else if (!this.replaying) {
        // session/load replays the conversation; the journal already holds it.
        this.translator.feed(update)
      }
    })
```

- in `handshake`, change the `initialize` result type to also include `agentCapabilities?: { loadSession?: boolean; promptCapabilities?: { image?: boolean } }` and add right after the request: `this.imagesAccepted = init.agentCapabilities?.promptCapabilities?.image === true`;
- in `announce`, add at the end: `if (this.commands.length > 0) this.facts.fire({ kind: 'commands', items: this.commands })` (commands that arrived before the caller subscribed);
- in `prompt`, replace the `prompt: [{ type: 'text', text: encodePrompt(parts, this.options.cwd) }]` property with:

```ts
        prompt: [
          { type: 'text', text: encodePrompt(parts, this.options.cwd) },
          ...(this.imagesAccepted
            ? imageParts(parts).map((image) => ({ type: 'image', mimeType: image.mimeType, data: readFileSync(image.path).toString('base64') }))
            : [])
        ]
```

  and add before `this.translator.startTurn()`:

```ts
    if (imageParts(parts).length > 0 && !this.imagesAccepted) {
      this.items.fire({
        kind: 'notice',
        id: `notice:${randomUUID()}`,
        level: 'warning',
        text: `${this.spec.label} does not accept images, so they were left out of this message.`
      })
    }
```

- [ ] **Step 4: Verify and commit**

Run: `pnpm typecheck && pnpm test` → clean; PASS.

```bash
git add src/providers
git commit -m "feat(providers): list commands and send images and skills per provider"
```

---

### Task 3: Host — requests, file search, attachments

**Files:**
- Modify: `src/ui/protocol.ts`, `webview/app/state.ts`, `src/ui/chat-surfaces.ts`, `webview/app/items/turn-footer.tsx`
- Create: `src/ui/rank-files.ts`, `src/ui/file-search.ts`, `src/ui/attachments.ts`
- Test: `test/ui/rank-files.test.ts`, `test/ui/attachments.test.ts`

- [ ] **Step 1: Write the failing tests**

`test/ui/rank-files.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { rankFiles } from '../../src/ui/rank-files'

const files = ['src/api/retry.ts', 'src/api.test.ts', 'docs/retry-notes.md', 'src/server/router.ts', 'README.md']

describe('rankFiles', () => {
  it('ranks name prefixes, then name matches, then path matches, then subsequences', () => {
    expect(rankFiles(files, 'retry', new Set())).toEqual(['src/api/retry.ts', 'docs/retry-notes.md'])
    expect(rankFiles(files, 'api', new Set())).toEqual(['src/api.test.ts', 'src/api/retry.ts'])
    expect(rankFiles(files, 'srvr', new Set())).toEqual(['src/server/router.ts'])
  })

  it('puts recently opened files first and lists everything for an empty query', () => {
    expect(rankFiles(files, '', new Set(['README.md']))[0]).toBe('README.md')
    expect(rankFiles(files, '', new Set())).toHaveLength(files.length)
  })

  it('limits the list', () => {
    expect(rankFiles(files, '', new Set(), 2)).toHaveLength(2)
  })
})
```

`test/ui/attachments.test.ts`:

```ts
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { attachFile, saveImage } from '../../src/ui/attachments'

describe('attachments', () => {
  it('stores an image under a new name', () => {
    const dir = join(mkdtempSync(join(tmpdir(), 'agentdeck-att-')), 'attachments')
    const image = saveImage(dir, 'shot.png', 'image/png', Buffer.from('png-bytes'))
    expect(image).toMatchObject({ kind: 'image', mimeType: 'image/png', name: 'shot.png' })
    expect(image.kind === 'image' && image.path.startsWith(dir) && image.path.endsWith('.png')).toBe(true)
    expect(readFileSync(image.path, 'utf8')).toBe('png-bytes')
  })

  it('copies picked images and references other files in place', () => {
    const root = mkdtempSync(join(tmpdir(), 'agentdeck-att-'))
    const dir = join(root, 'attachments')
    writeFileSync(join(root, 'diagram.jpg'), 'jpg-bytes')
    writeFileSync(join(root, 'notes.ts'), 'code')
    const image = attachFile(dir, join(root, 'diagram.jpg'), 'diagram.jpg')
    expect(image).toMatchObject({ kind: 'image', mimeType: 'image/jpeg', name: 'diagram.jpg' })
    expect(image.kind === 'image' && existsSync(image.path)).toBe(true)
    expect(attachFile(dir, join(root, 'notes.ts'), 'notes.ts')).toEqual({ kind: 'file', path: join(root, 'notes.ts'), label: 'notes.ts' })
  })
})
```

Run: `pnpm test test/ui` → FAIL.

- [ ] **Step 2: Protocol and state**

In `src/ui/protocol.ts`:
- import `PromptPart` with the other core types;
- add:

```ts
export type FileMatch = { path: string; label: string }

export type Attachment = { kind: 'image'; path: string; mimeType: string; name: string } | { kind: 'file'; path: string; label: string }
```

- in `WebviewMessage`, replace `| { type: 'prompt'; text: string; includeContext: boolean }` with `| { type: 'prompt'; parts: PromptPart[]; includeContext: boolean }`, and add:

```ts
  | { type: 'searchFiles'; requestId: number; query: string }
  | { type: 'pickAttachments'; requestId: number }
  | { type: 'saveImage'; requestId: number; name: string; mimeType: string; data: string }
```

- in `HostMessage`, add:

```ts
  /** The answer to a webview request with the same requestId. */
  | { type: 'reply'; requestId: number; value: unknown }
  /** Webview URI of the attachment store, for showing attached images. */
  | { type: 'assets'; attachments: string }
```

In `webview/app/state.ts`: add `attachmentsUri?: string` to `ChatState`; add cases:

```ts
    case 'assets':
      return { ...state, attachmentsUri: message.attachments }
    case 'reply':
      return state
```

In `webview/app/items/turn-footer.tsx`, change the retry button's message to `{ type: 'prompt', parts: footer.prompt?.parts ?? [], includeContext: false }` and drop the now-unused `promptText` import.

- [ ] **Step 3: File ranking, search, and the attachment store**

`src/ui/rank-files.ts`:

```ts
/** Orders workspace files for the @ menu: recently opened first, then name prefixes, name matches, path matches, subsequences. */
export function rankFiles(labels: string[], query: string, recent: ReadonlySet<string>, limit = 20): string[] {
  const needle = query.toLowerCase()
  return labels
    .flatMap((label) => {
      const lower = label.toLowerCase()
      const name = lower.slice(lower.lastIndexOf('/') + 1)
      const score = !needle
        ? 3
        : name.startsWith(needle)
          ? 0
          : name.includes(needle)
            ? 1
            : lower.includes(needle)
              ? 2
              : isSubsequence(lower, needle)
                ? 3
                : -1
      return score < 0 ? [] : [{ label, score: score - (recent.has(label) ? 10 : 0) }]
    })
    .sort((a, b) => a.score - b.score || a.label.length - b.label.length || a.label.localeCompare(b.label))
    .slice(0, limit)
    .map((entry) => entry.label)
}

function isSubsequence(text: string, needle: string): boolean {
  let index = 0
  for (const char of text) if (char === needle[index]) index++
  return index === needle.length
}
```

`src/ui/file-search.ts`:

```ts
import * as vscode from 'vscode'
import type { FileMatch } from './protocol'
import { rankFiles } from './rank-files'

const EXCLUDE = '**/{node_modules,.git,dist,out,build,.next,coverage}/**'
const MAX_FILES = 20_000

/** Workspace files for the @ menu, listed once and listed again after files are created or deleted. */
export class FileSearch implements vscode.Disposable {
  private files: Promise<Map<string, string>> | undefined
  private readonly watcher = vscode.workspace.createFileSystemWatcher('**/*', false, true, false)
  private readonly subscriptions = [
    this.watcher,
    this.watcher.onDidCreate(() => (this.files = undefined)),
    this.watcher.onDidDelete(() => (this.files = undefined))
  ]

  async search(query: string): Promise<FileMatch[]> {
    // findFiles returns a Thenable; Promise.resolve makes it a Promise that can be cached and awaited.
    this.files ??= Promise.resolve(vscode.workspace.findFiles('**/*', EXCLUDE, MAX_FILES)).then(
      (uris) => new Map(uris.map((uri) => [vscode.workspace.asRelativePath(uri), uri.fsPath]))
    )
    const files = await this.files
    const recent = new Set(
      vscode.window.tabGroups.all
        .flatMap((group) => group.tabs)
        .flatMap((tab) => (tab.input instanceof vscode.TabInputText ? [vscode.workspace.asRelativePath(tab.input.uri)] : []))
    )
    return rankFiles([...files.keys()], query, recent).map((label) => ({ label, path: files.get(label) ?? label }))
  }

  dispose(): void {
    for (const subscription of this.subscriptions) subscription.dispose()
  }
}
```

`src/ui/attachments.ts`:

```ts
import { randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { basename, extname, join } from 'node:path'
import type { Attachment } from './protocol'

const IMAGE_TYPES: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp'
}

/** Images are copied into the extension's storage, so the transcript can show them after the original moves. */
export function saveImage(dir: string, name: string, mimeType: string, data: Buffer): Attachment {
  mkdirSync(dir, { recursive: true })
  const extension = Object.entries(IMAGE_TYPES).find(([, type]) => type === mimeType)?.[0] ?? '.png'
  const path = join(dir, `${randomUUID()}${extension}`)
  writeFileSync(path, data)
  return { kind: 'image', path, mimeType, name }
}

/** A picked image is stored like a pasted one; any other file is referenced where it is. */
export function attachFile(dir: string, source: string, label: string): Attachment {
  const type = IMAGE_TYPES[extname(source).toLowerCase()]
  return type ? saveImage(dir, basename(source), type, readFileSync(source)) : { kind: 'file', path: source, label }
}
```

Run: `pnpm test` → PASS.

- [ ] **Step 4: Host routing**

In `src/ui/chat-surfaces.ts`:
- add imports: `import { join } from 'node:path'`, `import { attachFile, saveImage } from './attachments'`, `import { FileSearch } from './file-search'`;
- add fields:

```ts
  private readonly files = new FileSearch()
  private readonly attachmentsDir: string
```

  and set `this.attachmentsDir = join((context.storageUri ?? context.globalStorageUri).fsPath, 'attachments')` at the start of the constructor body; add `this.files.dispose()` to `dispose`;
- add a method and use it everywhere: replace every `localResourceRoots: [this.assets()]` in the file with `localResourceRoots: this.roots()`, and add:

```ts
  /** The webview may load the bundle and attached images. */
  private roots(): vscode.Uri[] {
    return [this.assets(), vscode.Uri.file(this.attachmentsDir)]
  }
```

- in the `'ready'` case, add after the `editorContext` post:

```ts
        this.post(surface, {
          type: 'assets',
          attachments: surface.webview.asWebviewUri(vscode.Uri.file(this.attachmentsDir)).toString()
        })
```

- in the `'prompt'` case, replace `const parts: PromptPart[] = [{ type: 'text', text: message.text }]` with `const parts: PromptPart[] = [...message.parts]`;
- add cases before `case 'openFile'`:

```ts
      case 'searchFiles':
        return this.reply(surface, message.requestId, await this.files.search(message.query))
      case 'pickAttachments': {
        const uris = await vscode.window.showOpenDialog({ canSelectMany: true, openLabel: 'Attach' })
        const attachments = (uris ?? []).map((uri) => attachFile(this.attachmentsDir, uri.fsPath, vscode.workspace.asRelativePath(uri)))
        return this.reply(surface, message.requestId, attachments)
      }
      case 'saveImage':
        return this.reply(
          surface,
          message.requestId,
          saveImage(this.attachmentsDir, message.name, message.mimeType, Buffer.from(message.data, 'base64'))
        )
```

- add:

```ts
  private reply(surface: Surface, requestId: number, value: unknown): void {
    this.post(surface, { type: 'reply', requestId, value })
  }
```

Run: `pnpm typecheck` → expected errors only in `webview/app/components/composer.tsx` (it still sends `text`; Task 4 replaces it). Any other error: stop and report.

- [ ] **Step 5: Commit**

```bash
git add src/ui webview/app/state.ts webview/app/items/turn-footer.tsx test/ui
git commit -m "feat(ui): file search, attachment store, and request/reply for the composer"
```

---

### Task 4: The editor

**Files:**
- Modify: `package.json` (dependencies), `webview/app/host.ts`, `webview/theme.css`, `webview/app/components/composer.tsx` (full replacement)
- Create: `webview/app/composer/prompt-document.ts`, `webview/app/composer/nodes.ts`, `webview/app/composer/suggestion-menu.tsx`, `webview/app/composer/prompt-editor.tsx`
- Test: `test/webview/prompt-document.test.ts`

- [ ] **Step 1: Install TipTap**

```bash
pnpm add @tiptap/core@3.32.0 @tiptap/react@3.32.0 @tiptap/pm@3.32.0 @tiptap/starter-kit@3.32.0 @tiptap/extension-mention@3.32.0 @tiptap/extension-placeholder@3.32.0 @tiptap/suggestion@3.32.0
```

If pnpm writes `^` ranges, change them to exact versions by editing those seven lines in `package.json` (do not re-serialize the file).

- [ ] **Step 2: Write the failing test**

`test/webview/prompt-document.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { toParts } from '../../webview/app/composer/prompt-document'

const doc = (...paragraphs: object[][]) => ({ type: 'doc', content: paragraphs.map((content) => ({ type: 'paragraph', content })) })
const text = (value: string) => ({ type: 'text', text: value })

describe('toParts', () => {
  it('turns mentions and pills into parts and merges text', () => {
    expect(
      toParts(
        doc(
          [{ type: 'mention', attrs: { id: 'review', label: 'review', mentionSuggestionChar: '/' } }, text(' the retry change in ')],
          [{ type: 'mention', attrs: { id: '/w/src/retry.ts', label: 'src/retry.ts', mentionSuggestionChar: '@' } }, text(' please')],
          [{ type: 'imageAttachment', attrs: { path: '/s/a.png', mimeType: 'image/png', name: 'a.png' } }],
          [{ type: 'pastedText', attrs: { text: 'line 1\nline 2' } }]
        )
      )
    ).toEqual([
      { type: 'command', name: 'review' },
      { type: 'text', text: 'the retry change in' },
      { type: 'file', path: '/w/src/retry.ts' },
      { type: 'text', text: 'please' },
      { type: 'image', path: '/s/a.png', mimeType: 'image/png', name: 'a.png' },
      { type: 'pasted', text: 'line 1\nline 2' }
    ])
  })

  it('keeps line breaks inside text and drops empty text', () => {
    expect(toParts(doc([text('one')], [text('two'), { type: 'hardBreak' }, text('three')], []))).toEqual([
      { type: 'text', text: 'one\ntwo\nthree' }
    ])
    expect(toParts(doc([]))).toEqual([])
  })
})
```

Run: `pnpm test test/webview/prompt-document.test.ts` → FAIL.

- [ ] **Step 3: The document model**

`webview/app/composer/prompt-document.ts`:

```ts
import type { JSONContent } from '@tiptap/core'
import type { PromptPart } from '../../../src/core/types'

/** The composer's document as prompt parts: mentions and pills become their own parts, text between them merges. */
export function toParts(doc: JSONContent): PromptPart[] {
  const parts: PromptPart[] = []
  let text = ''
  const flush = () => {
    if (text.trim()) parts.push({ type: 'text', text: text.trim() })
    text = ''
  }
  ;(doc.content ?? []).forEach((block, index) => {
    if (index > 0) text += '\n'
    for (const node of block.content ?? []) {
      const attrs = node.attrs ?? {}
      if (node.type === 'text') text += node.text ?? ''
      else if (node.type === 'hardBreak') text += '\n'
      else {
        flush()
        if (node.type === 'mention' && attrs.mentionSuggestionChar === '/') parts.push({ type: 'command', name: String(attrs.id) })
        else if (node.type === 'mention') parts.push({ type: 'file', path: String(attrs.id) })
        else if (node.type === 'imageAttachment') {
          parts.push({ type: 'image', path: String(attrs.path), mimeType: String(attrs.mimeType), name: String(attrs.name) })
        } else if (node.type === 'pastedText') parts.push({ type: 'pasted', text: String(attrs.text) })
      }
    }
  })
  flush()
  return parts
}
```

Run: `pnpm test` → PASS.

- [ ] **Step 4: Request/reply in the webview**

Append to `webview/app/host.ts`:

```ts
type Request = Extract<WebviewMessage, { requestId: number }>
type WithoutRequestId<T> = T extends unknown ? Omit<T, 'requestId'> : never

let nextRequest = 0
const replies = new Map<number, (value: unknown) => void>()

window.addEventListener('message', (event: MessageEvent<HostMessage>) => {
  if (event.data?.type !== 'reply') return
  replies.get(event.data.requestId)?.(event.data.value)
  replies.delete(event.data.requestId)
})

/** Sends a request to the extension host and resolves with its reply. */
export function ask<T>(message: WithoutRequestId<Request>): Promise<T> {
  const requestId = ++nextRequest
  return new Promise<T>((resolve) => {
    replies.set(requestId, resolve as (value: unknown) => void)
    send({ ...message, requestId } as Request)
  })
}
```

- [ ] **Step 5: Nodes and the suggestion menu**

`webview/app/composer/nodes.ts`:

```ts
import { Extension, mergeAttributes, Node } from '@tiptap/core'
import { type EditorState, PluginKey } from '@tiptap/pm/state'

export const fileMenu = new PluginKey('fileMenu')
export const commandMenu = new PluginKey('commandMenu')

function menuOpen(state: EditorState): boolean {
  return [fileMenu, commandMenu].some((key) => key.getState(state)?.active)
}

/** Enter sends; while an @ or / menu is open it picks the highlighted entry instead. Shift+Enter adds a line. */
export const SubmitOnEnter = Extension.create<{ onSubmit: () => void }>({
  name: 'submitOnEnter',
  priority: 1000,
  addOptions: () => ({ onSubmit: () => {} }),
  addKeyboardShortcuts() {
    return {
      Enter: ({ editor }) => {
        if (menuOpen(editor.state)) return false
        this.options.onSubmit()
        return true
      }
    }
  }
})

/** An image in AgentDeck's attachment store. */
export const ImageAttachment = Node.create({
  name: 'imageAttachment',
  group: 'inline',
  inline: true,
  atom: true,
  addAttributes: () => ({ path: { default: '' }, mimeType: { default: 'image/png' }, name: { default: 'image' } }),
  parseHTML: () => [{ tag: 'span[data-pill="image"]' }],
  renderHTML: ({ node, HTMLAttributes }) => [
    'span',
    mergeAttributes(HTMLAttributes, { 'data-pill': 'image' }),
    ['i', { class: 'codicon codicon-file-media' }],
    ` ${node.attrs.name}`
  ],
  renderText: ({ node }) => `[image: ${node.attrs.name}]`
})

export const PASTE_LINES = 40

/** A long paste, kept whole but shown as one pill. */
export const PastedText = Node.create({
  name: 'pastedText',
  group: 'inline',
  inline: true,
  atom: true,
  addAttributes: () => ({ text: { default: '' } }),
  parseHTML: () => [{ tag: 'span[data-pill="pasted"]' }],
  renderHTML: ({ node, HTMLAttributes }) => [
    'span',
    mergeAttributes(HTMLAttributes, { 'data-pill': 'pasted', title: String(node.attrs.text).slice(0, 2000) }),
    `Pasted text · ${String(node.attrs.text).split('\n').length} lines`
  ],
  renderText: ({ node }) => String(node.attrs.text)
})
```

`webview/app/composer/suggestion-menu.tsx`:

```tsx
import type { SuggestionOptions } from '@tiptap/suggestion'
import { ReactRenderer } from '@tiptap/react'
import { forwardRef, useEffect, useImperativeHandle, useState } from 'react'
import { cn } from '@/lib/utils'

export type MenuItem = { id: string; label: string; description?: string }
type MenuProps = { items: MenuItem[]; command: (item: MenuItem) => void; heading: string; loading: boolean }
type MenuHandle = { onKeyDown: (event: KeyboardEvent) => boolean }

const SuggestionMenu = forwardRef<MenuHandle, MenuProps>(function SuggestionMenu({ items, command, heading, loading }, ref) {
  const [active, setActive] = useState(0)
  useEffect(() => setActive(0), [items])
  useImperativeHandle(
    ref,
    () => ({
      onKeyDown: (event) => {
        if (items.length === 0) return false
        if (event.key === 'ArrowDown') setActive((index) => (index + 1) % items.length)
        else if (event.key === 'ArrowUp') setActive((index) => (index + items.length - 1) % items.length)
        else if (event.key === 'Enter' || event.key === 'Tab') command(items[active])
        else return false
        return true
      }
    }),
    [items, active, command]
  )
  return (
    <div className="z-50 w-80 overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md">
      <div className="border-b px-2 py-1 text-[11px] text-muted-foreground">{heading}</div>
      {items.length === 0 ? (
        <div className="px-2 py-2 text-xs text-muted-foreground">{loading ? 'Searching…' : 'No matches'}</div>
      ) : (
        <ul className="max-h-64 overflow-auto py-1">
          {items.map((item, index) => (
            <li key={item.id}>
              <button
                type="button"
                className={cn('flex w-full flex-col items-start px-2 py-1 text-left text-xs', index === active && 'bg-accent')}
                onMouseEnter={() => setActive(index)}
                onMouseDown={(event) => {
                  event.preventDefault()
                  command(item)
                }}
              >
                <span className="max-w-full truncate font-medium">{item.label}</span>
                {item.description && <span className="line-clamp-1 text-muted-foreground">{item.description}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
})

/** Renders a TipTap suggestion as a floating menu; TipTap's mount() keeps it anchored to the cursor. */
export function renderMenu(heading: string): SuggestionOptions<MenuItem>['render'] {
  return () => {
    let renderer: ReactRenderer<MenuHandle, MenuProps> | undefined
    let unmount: (() => void) | undefined
    return {
      onStart: (props) => {
        renderer = new ReactRenderer(SuggestionMenu, {
          props: { items: props.items, command: props.command, heading, loading: props.loading },
          editor: props.editor
        })
        unmount = props.mount(renderer.element as HTMLElement)
      },
      onUpdate: (props) => renderer?.updateProps({ items: props.items, command: props.command, heading, loading: props.loading }),
      onKeyDown: ({ event }) => renderer?.ref?.onKeyDown(event) ?? false,
      onExit: () => {
        unmount?.()
        renderer?.destroy()
      }
    }
  }
}
```

- [ ] **Step 6: The editor component**

`webview/app/composer/prompt-editor.tsx`:

```tsx
import { mergeAttributes } from '@tiptap/core'
import Mention from '@tiptap/extension-mention'
import Placeholder from '@tiptap/extension-placeholder'
import { EditorContent, type JSONContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { forwardRef, useImperativeHandle, useRef } from 'react'
import type { CommandOption, PromptPart } from '../../../src/core/types'
import type { Attachment, FileMatch } from '../../../src/ui/protocol'
import { ask } from '../host'
import { commandMenu, fileMenu, ImageAttachment, PASTE_LINES, PastedText, SubmitOnEnter } from './nodes'
import { toParts } from './prompt-document'
import { renderMenu } from './suggestion-menu'

export type PromptEditorHandle = {
  submit: () => void
  insert: (attachments: Attachment[]) => void
  /** Types @ so the file menu opens. */
  mention: () => void
}

type Props = {
  placeholder: string
  commands: CommandOption[]
  onSubmit: (parts: PromptPart[]) => void
  onEmptyChange: (empty: boolean) => void
}

function attachmentNode(attachment: Attachment): JSONContent {
  return attachment.kind === 'image'
    ? { type: 'imageAttachment', attrs: { path: attachment.path, mimeType: attachment.mimeType, name: attachment.name } }
    : { type: 'mention', attrs: { id: attachment.path, label: attachment.label, mentionSuggestionChar: '@' } }
}

function toBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let index = 0; index < bytes.length; index += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000))
  }
  return btoa(binary)
}

export const PromptEditor = forwardRef<PromptEditorHandle, Props>(function PromptEditor(
  { placeholder, commands, onSubmit, onEmptyChange },
  ref
) {
  const placeholderRef = useRef(placeholder)
  placeholderRef.current = placeholder
  const commandsRef = useRef(commands)
  commandsRef.current = commands
  const submitRef = useRef(() => {})

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        blockquote: false,
        bold: false,
        bulletList: false,
        code: false,
        codeBlock: false,
        dropcursor: false,
        gapcursor: false,
        heading: false,
        horizontalRule: false,
        italic: false,
        link: false,
        listItem: false,
        orderedList: false,
        strike: false,
        trailingNode: false,
        underline: false
      }),
      Placeholder.configure({ placeholder: () => placeholderRef.current }),
      Mention.configure({
        HTMLAttributes: { 'data-pill': 'mention' },
        deleteTriggerWithBackspace: true,
        renderText: ({ node }) => `${node.attrs.mentionSuggestionChar ?? '@'}${node.attrs.label ?? node.attrs.id}`,
        renderHTML: ({ options, node }) => [
          'span',
          mergeAttributes({ 'data-type': 'mention' }, options.HTMLAttributes),
          `${node.attrs.mentionSuggestionChar ?? '@'}${node.attrs.label ?? node.attrs.id}`
        ],
        suggestions: [
          {
            char: '@',
            pluginKey: fileMenu,
            items: async ({ query }) =>
              (await ask<FileMatch[]>({ type: 'searchFiles', query })).map((file) => ({ id: file.path, label: file.label })),
            render: renderMenu('Files')
          },
          {
            char: '/',
            pluginKey: commandMenu,
            items: ({ query }) =>
              commandsRef.current
                .filter((command) => command.name.toLowerCase().includes(query.toLowerCase()))
                .slice(0, 30)
                .map((command) => ({ id: command.name, label: command.name, description: command.description })),
            render: renderMenu('Commands and skills')
          }
        ]
      }),
      ImageAttachment,
      PastedText,
      SubmitOnEnter.configure({ onSubmit: () => submitRef.current() })
    ],
    editorProps: {
      attributes: { class: 'prompt-editor', role: 'textbox', 'aria-multiline': 'true', 'aria-label': 'Message' },
      handlePaste: (_view, event) => {
        const images = [...(event.clipboardData?.files ?? [])].filter((file) => file.type.startsWith('image/'))
        if (images.length > 0) {
          void Promise.all(
            images.map(async (file) =>
              ask<Attachment>({ type: 'saveImage', name: file.name || 'pasted image', mimeType: file.type, data: toBase64(await file.arrayBuffer()) })
            )
          ).then(insert)
          return true
        }
        const text = event.clipboardData?.getData('text/plain') ?? ''
        if (text.split('\n').length <= PASTE_LINES) return false
        editor?.chain().focus().insertContent([{ type: 'pastedText', attrs: { text } }, { type: 'text', text: ' ' }]).run()
        return true
      }
    },
    onUpdate: ({ editor: current }) => onEmptyChange(current.isEmpty)
  })

  const insert = (attachments: Attachment[]) => {
    if (!editor || attachments.length === 0) return
    editor.chain().focus().insertContent([...attachments.map(attachmentNode), { type: 'text', text: ' ' }]).run()
  }

  submitRef.current = () => {
    if (!editor) return
    const parts = toParts(editor.getJSON())
    if (parts.length === 0) return
    onSubmit(parts)
    editor.commands.clearContent(true)
  }

  useImperativeHandle(ref, () => ({
    submit: () => submitRef.current(),
    insert,
    mention: () => editor?.chain().focus().insertContent('@').run()
  }))

  return <EditorContent editor={editor} />
})
```

- [ ] **Step 7: Editor styles**

Append to `webview/theme.css`:

```css
@layer components {
  .prompt-editor {
    max-height: 12rem;
    min-height: 2.5rem;
    overflow-y: auto;
    padding: 0.5rem 0.75rem;
    font-size: var(--vscode-font-size);
    outline: none;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .prompt-editor p {
    margin: 0;
  }
  .prompt-editor p.is-editor-empty:first-child::before {
    content: attr(data-placeholder);
    float: left;
    height: 0;
    pointer-events: none;
    color: var(--muted-foreground);
  }
  .prompt-editor [data-pill] {
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--muted);
    padding: 0 4px;
    font-size: 0.9em;
    white-space: nowrap;
  }
  .prompt-editor [data-pill] .codicon {
    font-size: 12px;
    vertical-align: -1px;
  }
}
```

- [ ] **Step 8: Composer**

`webview/app/components/composer.tsx` (full replacement):

```tsx
import { type RefObject, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import type { PromptPart } from '../../../src/core/types'
import type { Attachment } from '../../../src/ui/protocol'
import { PromptEditor, type PromptEditorHandle } from '../composer/prompt-editor'
import { ask, send } from '../host'
import type { ChatState } from '../state'
import { Codicon } from './codicon'
import { ContextMeter } from './context-meter'
import { FilePill } from './file-pill'
import { McpPopover } from './mcp-popover'
import { ModelPicker } from './model-picker'
import { ModePicker } from './mode-picker'

function AttachMenu({ editor }: { editor: RefObject<PromptEditorHandle | null> }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="icon-xs" variant="ghost" className="shrink-0 text-muted-foreground" aria-label="Attach">
          <Codicon name="attach" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem
          onSelect={async () => editor.current?.insert(await ask<Attachment[]>({ type: 'pickAttachments' }))}
        >
          <Codicon name="cloud-upload" />
          Upload from computer…
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => editor.current?.mention()}>
          <Codicon name="mention" />
          Add file from workspace…
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function Composer({ state }: { state: ChatState }) {
  const editor = useRef<PromptEditorHandle>(null)
  const [empty, setEmpty] = useState(true)
  const [includeContext, setIncludeContext] = useState(true)
  const busy = state.status === 'running' || state.status === 'needs-input'
  const context = includeContext ? state.editorContext : null
  const commands = state.facts.commands?.kind === 'commands' ? state.facts.commands.items : []

  // A file the user removed is offered again once they switch to another file.
  useEffect(() => setIncludeContext(true), [state.editorContext?.path])

  const submit = (parts: PromptPart[]) => send({ type: 'prompt', parts, includeContext: context !== null })

  return (
    <div className="@container rounded-xl border bg-input/40 focus-within:border-ring">
      {context && (
        <div className="px-3 pt-2">
          <FilePill path={context.path} range={context.range} label={context.label} onRemove={() => setIncludeContext(false)} />
        </div>
      )}
      <PromptEditor
        ref={editor}
        placeholder={busy ? 'Queue a follow-up…' : `Ask ${state.provider?.label ?? 'the agent'}… @ for files, / for commands`}
        commands={commands}
        onSubmit={submit}
        onEmptyChange={setEmpty}
      />
      <div className="flex items-center gap-1 px-2 pb-2">
        <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-hidden">
          <AttachMenu editor={editor} />
          <ModelPicker fact={state.facts.model?.kind === 'model' ? state.facts.model : undefined} />
          <ModePicker
            current={state.facts.mode?.kind === 'mode' ? state.facts.mode.current : (state.record?.mode ?? 'ask')}
            available={state.provider?.modes ?? []}
          />
          <McpPopover fact={state.facts.mcp?.kind === 'mcp' ? state.facts.mcp : undefined} />
        </div>
        <ContextMeter fact={state.facts.context?.kind === 'context' ? state.facts.context : undefined} />
        {busy ? (
          <Button key="stop" size="icon-sm" variant="secondary" className="shrink-0" aria-label="Stop" onClick={() => send({ type: 'cancel' })}>
            <Codicon name="debug-stop" />
          </Button>
        ) : (
          <Button key="send" size="icon-sm" className="shrink-0" aria-label="Send" disabled={empty} onClick={() => editor.current?.submit()}>
            <Codicon name="send" />
          </Button>
        )}
      </div>
    </div>
  )
}
```

While a turn runs, Enter still sends (the host queues the prompt); Stop replaces Send.

- [ ] **Step 9: Verify and commit**

Run: `pnpm typecheck && pnpm test` → clean; PASS.

```bash
git add package.json pnpm-lock.yaml webview test/webview/prompt-document.test.ts
git commit -m "feat(webview): rich composer with @ files, / commands, attachments, and pasted pills"
```

---

### Task 5: Show parts in the transcript

**Files:**
- Create: `webview/app/assets.ts`
- Modify: `webview/app/items/user-message.tsx` (full replacement), `webview/app/App.tsx`

- [ ] **Step 1: Assets context**

`webview/app/assets.ts`:

```ts
import { createContext, useContext } from 'react'
import { fileName } from './format'

/** Webview URI of the attachment store; images in prompts are shown from there. */
export const AttachmentsContext = createContext<string | undefined>(undefined)

export function useAttachmentSrc(path: string): string | undefined {
  const base = useContext(AttachmentsContext)
  return base ? `${base}/${fileName(path)}` : undefined
}
```

In `webview/app/App.tsx`, import `AttachmentsContext` from `./assets` and wrap the returned `<TooltipProvider>…</TooltipProvider>` in `<AttachmentsContext.Provider value={state.attachmentsUri}>…</AttachmentsContext.Provider>`.

- [ ] **Step 2: User message**

`webview/app/items/user-message.tsx` (full replacement):

```tsx
import { Message, MessageContent } from '@/components/ai-elements/message'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { PromptPart, UserMessage } from '../../../src/core/types'
import { useAttachmentSrc } from '../assets'
import { Codicon } from '../components/codicon'
import { FilePill } from '../components/file-pill'
import { promptText } from '../format'

type Part<T extends PromptPart['type']> = Extract<PromptPart, { type: T }>

function ImageThumb({ image }: { image: Part<'image'> }) {
  const src = useAttachmentSrc(image.path)
  return src ? (
    <img src={src} alt={image.name} title={image.name} className="h-20 max-w-40 rounded border object-cover" />
  ) : (
    <span className="rounded border px-1.5 py-0.5 text-xs">{image.name}</span>
  )
}

function Pasted({ text }: { text: string }) {
  return (
    <Collapsible className="group rounded-md border text-xs">
      <CollapsibleTrigger className="flex w-full items-center gap-1.5 px-2 py-1 text-left text-muted-foreground">
        <Codicon name="note" size={12} />
        Pasted text · {text.split('\n').length} lines
        <Codicon name="chevron-down" size={12} className="ml-auto transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <pre className="max-h-60 overflow-auto border-t px-2 py-1.5 whitespace-pre-wrap">{text}</pre>
      </CollapsibleContent>
    </Collapsible>
  )
}

export function UserMessageView({ item }: { item: UserMessage }) {
  const of = <T extends PromptPart['type']>(type: T) => item.parts.filter((part): part is Part<T> => part.type === type)
  const commands = of('command')
  const files = of('file')
  const images = of('image')
  const text = promptText(item.parts)
  return (
    <Message from="user">
      <MessageContent>
        {(commands.length > 0 || text) && (
          <div className="whitespace-pre-wrap">
            {commands.map((command) => (
              <span key={command.name} className="mr-1 rounded border bg-muted px-1 font-mono text-xs">
                /{command.name}
              </span>
            ))}
            {text}
          </div>
        )}
        {of('pasted').map((pasted, index) => (
          <Pasted key={index} text={pasted.text} />
        ))}
        {images.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {images.map((image) => (
              <ImageThumb key={image.path} image={image} />
            ))}
          </div>
        )}
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

- [ ] **Step 3: Verify and commit**

Run: `pnpm typecheck && pnpm test` → clean; PASS.

```bash
git add webview/app
git commit -m "feat(webview): show commands, images, and pasted text in sent messages"
```

---

### Task 6: Preview, live checks, hand-off

**Files:**
- Modify: `webview/preview/scenario.ts`

- [ ] **Step 1: Preview data**

In `webview/preview/scenario.ts`, change the `u0` message's `parts` to:

```ts
    parts: [
      { type: 'command', name: 'review' },
      { type: 'text', text: 'Add a retry helper with exponential backoff.' },
      { type: 'pasted', text: Array.from({ length: 48 }, (_, line) => `log line ${line + 1}`).join('\n') }
    ]
```

and add to the `chat` messages (after `providers`): `{ type: 'assets', attachments: 'about:blank' }`.

- [ ] **Step 2: Screenshots**

Run: `pnpm build:preview && pnpm screenshot dark 900x1700 panel && pnpm screenshot dark 340x1000 view`
Open both and check: the first user message shows a `/review` pill before its text and a collapsed *Pasted text · 48 lines* row; the composer shows the placeholder "Queue a follow-up…" and an attach (paperclip) button left of the model picker; nothing overflows at 340 px. Fix layout defects only in files this plan touched.

- [ ] **Step 3: Live checks**

Run: `pnpm typecheck && pnpm test && pnpm build && node dist/smoke.js claude && node dist/smoke.js codex && node dist/smoke.js grok && pnpm run package`
Expected: `SMOKE OK` three times (prompts are now `PromptPart[]` with only text, so behaviour is unchanged); packaged.

- [ ] **Step 4: Commit**

```bash
git add webview/preview
git commit -m "test(webview): preview commands and pasted text in messages"
```

- [ ] **Step 5: Hand off**

Ask the user to reinstall (`code --install-extension agentdeck-0.1.0.vsix --force`), reload, and check in a chat: typing `@` lists workspace files (open files first) and Enter inserts a pill; typing `/` lists the provider's commands or skills (Claude: its slash commands; Codex: skills; Grok: its commands); Enter sends unless a menu is open, Shift+Enter adds a line; pasting a screenshot adds an image pill and the sent message shows the thumbnail, and the agent describes the image; pasting more than 40 lines shows a *Pasted text* pill; *Upload from computer…* attaches a picked file; Grok shows a warning instead of silently dropping images only if it stops accepting them.
