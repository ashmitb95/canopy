# Plan 14: Session operations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first. **Commit at every checkpoint** (each step whose check passes) so a usage limit cannot lose work; end each task with its named commit. Write files with the code itself; never extract code blocks from this plan with `sed` line ranges. Run each new test red before implementing. Never `git commit --amend`.

**Goal:** These operations around chats bring AgentDeck in line with AFK Pilot:
- **Fork a conversation** (Claude, Codex) into a new chat.
- **Unread markers** on chats whose turn finished while you weren't looking.
- **Rename and delete** from the chat header and the switcher.
- **A 30-day chat list.**
- ***Add to AgentDeck Chat*** from the Explorer and the editor tab, with a keybinding.
- **The Secondary Side Bar** as the chat view's default home.
- **Keeping the machine awake** while a turn runs.

Rewind is not part of this plan. It needs per-provider turn references; that work is planned separately as 14b.

**Architecture:**
- **Forking:** forking is an optional `ProviderSession.fork()` that returns the new native session id.
  - **Claude:** the SDK's `forkSession(id, { dir })`.
  - **Codex:** `thread/fork`.
  - **After the fork:** the manager creates a record for the new chat and copies the journal into it, so the fork opens with the same transcript and resumes in the provider.
- **Unread markers:** an `Unread` set in `workspaceState`.
  - **Marking:** the chat surfaces mark a chat unread when its turn ends or fails while it isn't visible.
  - **Clearing:** showing the chat clears the marker.
  - **Where markers appear:** the switcher and the Sessions tree both show them.
- **Keep-awake:** keep-awake runs `caffeinate -i` (macOS) or `systemd-inhibit` (Linux) while any chat is running; Windows is skipped.

**Tech Stack:** as before. `engines.vscode` becomes `^1.106.0`, the version that brought the `secondarySidebar` views container (the user runs 1.140).

---

### Task 1: Fork

**Files:**
- Modify: `src/core/types.ts`, `src/sessions/manager.ts`, `src/providers/claude/provider.ts`, `src/providers/codex/provider.ts`, `test/fake-provider.ts`, `test/sessions/manager.test.ts`

- [ ] **Step 1: Write the failing test**

In `test/fake-provider.ts`, add to `FakeSession`: `async fork(): Promise<string> { return `${this.nativeId}-fork` }`.

Add inside the `describe` block of `test/sessions/manager.test.ts`:

```ts
  it('forks a chat into a new one with the same transcript that resumes the forked native session', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.setLane(id, 'x')
    await manager.prompt(id, text('hello'))
    sessions[0].emit({ kind: 'message', id: 'm1', role: 'assistant', text: 'hi', streaming: false })
    sessions[0].emit({ kind: 'turn', id: 't1', state: 'ended' })
    const fork = await manager.fork(id)
    expect(fork).toMatchObject({ title: expect.stringMatching(/\(fork\)$/), hasTurns: true, laneId: 'x', nativeId: `${sessions[0].nativeId}-fork` })
    expect(fork.id).not.toBe(id)
    await manager.warm(fork.id)
    expect(sessions[1].options.resumeId).toBe(`${sessions[0].nativeId}-fork`)
    const snapshot = await new Promise<unknown>((resolve) => manager.subscribe(fork.id, (event) => event.type === 'snapshot' && resolve(event)))
    expect(snapshot).toMatchObject({ items: expect.arrayContaining([expect.objectContaining({ id: 'm1' })]) })
  })

  it('refuses to fork a chat with no turns yet', async () => {
    const { manager } = setup()
    const { id } = await manager.create('fake')
    await expect(manager.fork(id)).rejects.toThrow(/Send a message first/)
  })
```

(If `subscribe` does not emit a snapshot on subscription, check the existing tests for how a snapshot is obtained and use that; report.)

Run: `pnpm test test/sessions` → FAIL.

- [ ] **Step 2: Implement**

In `src/core/types.ts`, add `| 'fork'` to `Capability` and to `ProviderSession`:

```ts
  /** Copies the conversation into a new provider session; returns its native id. */
  fork?(): Promise<string>
```

In `src/sessions/manager.ts`, add after `rename`:

```ts
  /** A new chat with this chat's transcript, resuming a forked copy of the provider's session. */
  async fork(id: string): Promise<SessionRecord> {
    const live = this.load(id)
    if (!live.record.hasTurns) throw new Error('Send a message first; there is nothing to fork yet.')
    const session = live.session ?? (await this.connect(live))
    if (!session.fork) throw new Error('This provider cannot fork a conversation.')
    const nativeId = await session.fork()
    const now = new Date().toISOString()
    const record: SessionRecord = {
      ...structuredClone(live.record),
      id: randomUUID(),
      title: `${live.record.title} (fork)`,
      createdAt: now,
      updatedAt: now,
      nativeId,
      hasTurns: true
    }
    delete record.laneSeen
    await this.deps.store.put(record)
    const journal = new Journal(this.journalPath(record.id))
    for (const item of live.items.values()) journal.append(settled(item))
    journal.flush()
    this.changed.fire()
    return record
  }
```

In `src/providers/claude/provider.ts`:
- add `'fork'` to the capabilities;
- import `forkSession` from `@anthropic-ai/claude-agent-sdk` (a value import, next to the type import);
- add:

```ts
  async fork(): Promise<string> {
    const { sessionId } = await forkSession(this.nativeId, { dir: this.options.cwd })
    return sessionId
  }
```

In `src/providers/codex/provider.ts`:
- add `'fork'` to the capabilities;
- add:

```ts
  async fork(): Promise<string> {
    const result = await this.rpc.request<{ thread: { id: string } }>('thread/fork', { threadId: this.nativeId, excludeTurns: true })
    return result.thread.id
  }
```

Run: `pnpm typecheck && pnpm test` → clean; PASS.

- [ ] **Step 3: Commit**

```bash
git add src test
git commit -m "feat(sessions): fork a conversation into a new chat (Claude, Codex)"
```

---

### Task 2: Unread markers, the chat menu, and the 30-day list

**Files:**
- Create: `src/ui/unread.ts`
- Modify: `src/ui/protocol.ts`, `src/ui/chat-surfaces.ts`, `src/ui/sessions-tree.ts`, `src/extension.ts`, `package.json`, `webview/app/components/chat-header.tsx`, `webview/app/components/session-switcher.tsx`
- Test: `test/ui/unread.test.ts`

- [ ] **Step 1: Write the failing test**

`test/ui/unread.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { recentSessions } from '../../src/ui/unread'

const day = 86_400_000
const at = (daysAgo: number) => new Date(Date.UTC(2026, 9, 30) - daysAgo * day).toISOString()

describe('recentSessions', () => {
  it('keeps chats from the last 30 days, at most 100', () => {
    const records = [{ updatedAt: at(1) }, { updatedAt: at(29) }, { updatedAt: at(31) }]
    expect(recentSessions(records, Date.UTC(2026, 9, 30))).toEqual([{ updatedAt: at(1) }, { updatedAt: at(29) }])
    const many = Array.from({ length: 150 }, () => ({ updatedAt: at(0) }))
    expect(recentSessions(many, Date.UTC(2026, 9, 30))).toHaveLength(100)
  })
})
```

Run → FAIL.

- [ ] **Step 2: The unread store**

`src/ui/unread.ts`:

```ts
import * as vscode from 'vscode'

const KEY = 'agentdeck.unread'
const DAYS = 30
const MAX = 100

/** Chats whose turn ended (or failed) while they were out of sight, until shown again. */
export class Unread {
  private readonly changed = new vscode.EventEmitter<void>()
  readonly onDidChange = this.changed.event

  constructor(private readonly memento: vscode.Memento) {}

  has(id: string): boolean {
    return this.all().includes(id)
  }

  mark(id: string): void {
    if (this.has(id)) return
    void this.memento.update(KEY, [...this.all(), id]).then(() => this.changed.fire())
  }

  clear(id: string): void {
    if (!this.has(id)) return
    void this.memento.update(KEY, this.all().filter((other) => other !== id)).then(() => this.changed.fire())
  }

  private all(): string[] {
    return this.memento.get<string[]>(KEY) ?? []
  }
}

/** The switcher's list: the last 30 days of chats (already newest first), capped. */
export function recentSessions<T extends { updatedAt: string }>(records: T[], now = Date.now()): T[] {
  return records.filter((record) => now - Date.parse(record.updatedAt) <= DAYS * 86_400_000).slice(0, MAX)
}
```

Note: `test/ui/unread.test.ts` imports a module that imports `vscode`. If the test environment cannot load `vscode` (check how other `test/ui/*` tests avoid it), move `recentSessions` to `src/ui/recent.ts` (no vscode import) and import it from there in both places; report.

Run → PASS.

- [ ] **Step 3: Host**

In `src/ui/protocol.ts`:
- add `unread?: boolean` to `SessionSummary`;
- add webview messages `| { type: 'forkSession' }`, `| { type: 'renameSession'; sessionId?: string }`, `| { type: 'deleteSession'; sessionId?: string }`;
- add the host message `| { type: 'insertAttachments'; attachments: Attachment[] }`.

In `src/ui/chat-surfaces.ts`:
- add a constructor parameter `private readonly unread: Unread` (after `lanes`; update the call in `extension.ts`);
- in `attend`, before the existing `needs-input` handling, add:

```ts
    if ((reason === 'turn-ended' || reason === 'failed') && !this.visible(sessionId)) this.unread.mark(sessionId)
```

  (if `attend` destructures only `{ sessionId, reason }`, that is all this needs);
- at the end of `show(surface, sessionId)`, add `this.unread.clear(sessionId)`;
- subscribe in the constructor: `unread.onDidChange(() => this.postSessions())`;
- in `postSessions`, replace `.slice(0, 20)` with `recentSessions(…)` over the list (import it) and add `...(this.unread.has(record.id) ? { unread: true } : {})` to each summary;
- handle the new webview messages:

```ts
      case 'forkSession':
        if (sessionId) await vscode.commands.executeCommand('agentdeck.forkSession', sessionId)
        return
      case 'renameSession':
      case 'deleteSession': {
        const target = message.sessionId ?? sessionId
        const record = this.manager.list().find((entry) => entry.record.id === target)?.record
        if (record) {
          await vscode.commands.executeCommand(`agentdeck.${message.type}`, { kind: 'session', id: record.id, title: record.title })
        }
        return
      }
```

- add a public method used by *Add to AgentDeck Chat*:

```ts
  /** Puts attachments into the composer of the chat in front: the active tab, else the sidebar (shown first). */
  async insertAttachments(attachments: Attachment[]): Promise<void> {
    const active = [...this.panels.values()].find(({ panel }) => panel.active)?.surface
    if (active) return void this.post(active, { type: 'insertAttachments', attachments })
    await vscode.commands.executeCommand(`${SIDEBAR_VIEW}.focus`)
    if (this.sidebar) this.post(this.sidebar, { type: 'insertAttachments', attachments })
  }
```

In `src/ui/sessions-tree.ts`:
- add a constructor parameter `private readonly unread: Unread` and subscribe to `unread.onDidChange` like the manager;
- for session items, when `this.unread.has(node.id)` and the status is `idle`, use `new vscode.ThemeIcon('circle-filled', new vscode.ThemeColor('notificationsInfoIcon.foreground'))` as the icon and add `'Unread · '` to the tooltip.

In `src/extension.ts`:
- `const unread = new Unread(context.workspaceState)` before the tree and the surfaces; pass it to both;
- make the existing `agentdeck.renameSession` and `agentdeck.deleteSession` handlers accept `node: { id: string; title: string }` (they already only read those);
- register:

```ts
    vscode.commands.registerCommand('agentdeck.forkSession', async (target?: SessionNode | string) => {
      const id = typeof target === 'string' ? target : (target?.id ?? surfaces.activeSessionId())
      if (!id) return
      try {
        const fork = await sessionManager.fork(id)
        surfaces.openPanel(fork.id)
      } catch (error) {
        void vscode.window.showErrorMessage((error as Error).message)
      }
    }),
```

In `package.json`: command `agentdeck.forkSession` "Fork Conversation" (category AgentDeck); `view/item/context` for `viewItem == session` at `"1_open@4"`.

- [ ] **Step 4: Webview**

In `webview/app/components/chat-header.tsx`, add a `ChatMenu` (a `DropdownMenu` with a `kebab-vertical` codicon trigger, `size="icon-xs" variant="ghost"`) to both header layouts, right before `<StatusBadge …/>`, with items:
- *Fork conversation* (`send({ type: 'forkSession' })`), only when `state.provider?.capabilities.includes('fork')`;
- *Hand off to…* (`send({ type: 'handOff' })`);
- *Rename…* (`send({ type: 'renameSession' })`);
- separator, *Delete…* (`send({ type: 'deleteSession' })`) with `className="text-destructive"`.

In `webview/app/components/session-switcher.tsx`, inside each session `CommandItem`:
- when `session.unread`, render the title with `font-semibold` and a `size-1.5 rounded-full bg-info` dot before the time;
- add two hover actions at the end (`hidden group-hover/item:flex`, put `className="group/item"` on the `CommandItem`): a pencil and a trash `button`, each with `onPointerDown={(event) => event.stopPropagation()}` and `onClick={(event) => { event.stopPropagation(); send({ type: 'renameSession' | 'deleteSession', sessionId: session.id }) }}` and an `aria-label`.

In the webview's message handling (where `onHostMessage` is wired for the composer, or in `composer.tsx` with a `useEffect`), handle `insertAttachments` by calling `editor.current?.insert(message.attachments)`; make `reduce` in `state.ts` return `state` unchanged for it.

Run: `pnpm typecheck && pnpm test` → clean; PASS.

- [ ] **Step 5: Commit**

```bash
git add src webview test package.json
git commit -m "feat: unread markers, chat menu with fork/rename/delete, 30-day switcher"
```

---

### Task 3: Add to chat, Secondary Side Bar, keep-awake

**Files:**
- Create: `src/ui/keep-awake.ts`
- Modify: `src/extension.ts`, `package.json`

- [ ] **Step 1: Add to AgentDeck Chat**

In `src/extension.ts`, register (import `attachFile` from `./ui/attachments`; the attachments folder is the one `ChatSurfaces` uses: `join(storage, 'attachments')` with `storage` as defined at the top of `activate`):

```ts
    vscode.commands.registerCommand('agentdeck.addToChat', async (uri?: vscode.Uri, selected?: vscode.Uri[]) => {
      const uris = selected?.length ? selected : uri ? [uri] : vscode.window.activeTextEditor ? [vscode.window.activeTextEditor.document.uri] : []
      const files = uris.filter((candidate) => candidate.scheme === 'file')
      if (files.length === 0) return
      await surfaces.insertAttachments(files.map((file) => attachFile(join(storage, 'attachments'), file.fsPath, vscode.workspace.asRelativePath(file))))
    }),
```

In `package.json`:
- command `agentdeck.addToChat` "Add to AgentDeck Chat" (category AgentDeck, icon `$(comment-discussion)`);
- `menus.explorer/context`: `{ "command": "agentdeck.addToChat", "when": "resourceScheme == file", "group": "agentdeck@1" }`;
- `menus.editor/title/context`: the same entry;
- `contributes.keybindings`: `{ "command": "agentdeck.addToChat", "key": "ctrl+alt+a", "mac": "cmd+alt+a", "when": "editorTextFocus" }`.

- [ ] **Step 2: Secondary Side Bar**

In `package.json`:
- change `engines.vscode` to `"^1.106.0"` (keep the caret);
- in `viewsContainers`, add `"secondarySidebar": [{ "id": "agentdeck-chat", "title": "AgentDeck", "icon": "media/agentdeck.svg" }]`;
- in `views`, move the `agentdeck.chat` webview view from `"agentdeck"` into a new `"agentdeck-chat"` list (the Sessions tree stays in the activity bar container).

Check that every `when` clause, command, and `focus` call that names `agentdeck.chat` still works: the view id is unchanged, so they should. If `@types/vscode` is pinned below 1.106 and something no longer typechecks, report it rather than bumping the types.

- [ ] **Step 3: Keep-awake**

`src/ui/keep-awake.ts`:

```ts
import { type ChildProcess, spawn } from 'node:child_process'
import * as vscode from 'vscode'
import type { SessionManager } from '../sessions/manager'

/** Holds off idle sleep while any chat is running: caffeinate on macOS, systemd-inhibit on Linux. */
export class KeepAwake implements vscode.Disposable {
  private child: ChildProcess | undefined
  private readonly subscription: { dispose(): void }

  constructor(private readonly manager: SessionManager) {
    this.subscription = manager.onDidChange(() => this.update())
  }

  dispose(): void {
    this.subscription.dispose()
    this.release()
  }

  private update(): void {
    const enabled = vscode.workspace.getConfiguration('agentdeck').get<boolean>('keepAwake', true)
    const running = this.manager.list().some(({ status }) => status === 'running' || status === 'needs-input')
    if (enabled && running) this.hold()
    else this.release()
  }

  private hold(): void {
    if (this.child) return
    const command =
      process.platform === 'darwin'
        ? ['caffeinate', ['-i', '-w', String(process.pid)]]
        : process.platform === 'linux'
          ? ['systemd-inhibit', ['--what=idle:sleep', '--who=AgentDeck', '--why=An agent is running', 'sleep', 'infinity']]
          : undefined
    if (!command) return
    const child = spawn(command[0] as string, command[1] as string[], { stdio: 'ignore' })
    child.on('error', () => (this.child = undefined))
    child.on('exit', () => (this.child = undefined))
    this.child = child
  }

  private release(): void {
    this.child?.kill()
    this.child = undefined
  }
}
```

Check: `manager.onDidChange` must fire when a status changes. If it only fires on list changes (create, rename, delete), subscribe instead to each status change the same way `SessionsTree` refreshes its icons (read how the tree learns of `running`), and report what you used.

In `package.json`, add the setting `"agentdeck.keepAwake": { "type": "boolean", "default": true, "description": "Keep the computer from sleeping while a chat is running (macOS and Linux)." }`. In `src/extension.ts`, push `new KeepAwake(sessionManager)`.

- [ ] **Step 4: Verify, package, docs, commit**

Run: `pnpm typecheck && pnpm test && pnpm build && pnpm run package` → clean; PASS; built; packaged.

Run (macOS): `node -e "const c=require('child_process').spawn('caffeinate',['-i','-w',String(process.pid)]);setTimeout(()=>{console.log(c.exitCode===null?'CAFFEINATE RUNNING':'CAFFEINATE EXITED');c.kill()},500)"` → `CAFFEINATE RUNNING`.

In `docs/superpowers/plans/2026-10-28-mvp-overview.md`, add a row for plan 14 (`| 14 | [Session operations](2026-10-30-14-session-operations.md) | Fork, unread markers, chat menu, 30-day list, Add to AgentDeck Chat, Secondary Side Bar, keep-awake | Done |`). In `docs/roadmap.md`: *Fork conversation* ✓ (Claude, Codex); *Rewind* ○ → plan 14b; *History…* ✓; *Add to chat…* ✓; *Default to the Secondary Side Bar* ✓; *Keep the machine awake* ✓ (macOS, Linux); end the line starting `- **14 — Session operations:**` with ` ✓ done (rewind moves to 14b).` and add a line `- **14b — Rewind:** per-provider turn references; Claude resumeSessionAt and file checkpoints, Codex thread/revert.`

```bash
git add src package.json docs
git commit -m "feat: add to chat from Explorer, Secondary Side Bar default, keep-awake; plan 14 done"
```
