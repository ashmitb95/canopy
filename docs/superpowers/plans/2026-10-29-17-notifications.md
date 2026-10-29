# Plan 17: Notifications — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first. **Commit at every checkpoint** (each step whose check passes) so a usage limit cannot lose work; end each task with its named commit. Write files with the code itself; never extract code blocks from this plan with `sed` line ranges. Run each new test red before implementing.

**Goal:** AgentDeck notifies natively from its own session events, with claude-notifier's behaviour (decision 35). It plays a sound and shows an OS notification when:
- a chat finishes a turn;
- a chat needs an approval;
- a chat asks a question;
- a turn fails.

The notification names the workspace, the lane, the provider and the chat, and says what happened, for example "edited 2 files · ran 5 commands", the command awaiting approval, or the question asked.

Carried over from claude-notifier:
- a level per event, with sound per event;
- volume;
- a minimum duration before "finished" notifies;
- muting while you are looking at the chat.

The CLIs AgentDeck spawns get `CLAUDE_NOTIFIER_DISABLE=1`, so claude-notifier's hooks stay quiet for them.

**Architecture:** This plan reuses claude-notifier's source at `~/projects/claude-notifier/src/notifications/`, but only in spirit: no code is imported from it.
- **Richer `Attention` events.** The session manager's `Attention` events become richer:
  - **needs input:** says which kind of prompt it is and its text;
  - **turn ended:** carries the duration and counts the edits and commands in the turn;
  - **failed:** a new event, with the error.
- **Pure modules** in `src/notify/`:
  - composing the banner (a port of claude-notifier's `compose`);
  - the command that plays a sound on each platform;
  - the command that shows a popup on each platform.
- **The notifier** (`src/ui/notifier.ts`) reads the `agentdeck.notifications.*` settings, decides whether to notify, and runs those commands.
- **Popups:**
  - **macOS:** `terminal-notifier`, when installed, so that clicking a popup focuses VS Code; otherwise `osascript`.
  - **Windows:** PowerShell.
  - **Linux:** `notify-send`.

**Tech Stack:** as before.

---

### Task 1: Richer attention events

**Files:**
- Modify: `src/sessions/manager.ts`, `test/sessions/manager.test.ts`

- [ ] **Step 1: Update and add tests**

In `test/sessions/manager.test.ts`, in *needs input while an approval is pending and forwards the answer*, change the expectation to:

```ts
    expect(attention).toEqual([{ sessionId: id, reason: 'needs-input', prompt: { kind: 'approval', text: 'Allow Bash?' } }])
```

and add inside the `describe` block:

```ts
  it('reports what a finished turn did, and failures', async () => {
    const { manager, sessions } = setup()
    const attention: Attention[] = []
    manager.onAttention((event) => attention.push(event))
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('go'))
    sessions[0].emit({ kind: 'diff', id: 'd1', path: '/w/a.ts', oldText: 'a', newText: 'b' })
    sessions[0].emit({ kind: 'diff', id: 'd2', path: '/w/a.ts', oldText: 'b', newText: 'c' })
    sessions[0].emit({ kind: 'diff', id: 'd3', path: '/w/b.ts', oldText: null, newText: 'x' })
    sessions[0].emit({ kind: 'tool', id: 't1', title: 'pnpm test', toolKind: 'execute', status: 'done' })
    sessions[0].emit({ kind: 'tool', id: 't2', title: 'read', toolKind: 'read', status: 'done' })
    sessions[0].emit({ kind: 'turn', id: 'turn1', state: 'ended' })
    expect(attention).toEqual([{ sessionId: id, reason: 'turn-ended', durationMs: expect.any(Number), edits: 2, commands: 1 }])
  })

  it('counts only the latest turn', async () => {
    const { manager, sessions } = setup()
    const attention: Attention[] = []
    manager.onAttention((event) => attention.push(event))
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('one'))
    sessions[0].emit({ kind: 'diff', id: 'd1', path: '/w/a.ts', oldText: 'a', newText: 'b' })
    sessions[0].emit({ kind: 'turn', id: 'turn1', state: 'ended' })
    await manager.prompt(id, text('two'))
    sessions[0].emit({ kind: 'turn', id: 'turn2', state: 'ended' })
    expect(attention[1]).toMatchObject({ reason: 'turn-ended', edits: 0, commands: 0 })
  })

  it('says which question is waiting', async () => {
    const { manager, sessions } = setup()
    const attention: Attention[] = []
    manager.onAttention((event) => attention.push(event))
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('ask'))
    sessions[0].emit({
      kind: 'question',
      id: 'question:1',
      questions: [{ id: 'q1', question: 'Which color?', multiSelect: false, allowOther: true, options: [] }]
    })
    expect(attention).toEqual([{ sessionId: id, reason: 'needs-input', prompt: { kind: 'question', text: 'Which color?' } }])
  })
```

If an existing test triggers a failure (`fail`) and checks attention, it now also sees `{ reason: 'failed', … }`; adjust only such expectations, and report them.

Run: `pnpm test test/sessions` → FAIL.

- [ ] **Step 2: Implement**

In `src/sessions/manager.ts`:
- replace the `Attention` type with:

```ts
export type Attention =
  | { sessionId: string; reason: 'needs-input'; prompt: { kind: 'approval' | 'question'; text: string } }
  | { sessionId: string; reason: 'turn-ended'; durationMs: number; edits: number; commands: number }
  | { sessionId: string; reason: 'failed'; text: string }
```

- add a field to `Live`: `turnStartedAt?: number`, and in `send`, next to `this.setStatus(live, 'running')`, set `live.turnStartedAt = Date.now()`;
- change the `upsert` line that calls `promptChanged` to pass the item: `this.promptChanged(live, item)`, and change `promptChanged` to:

```ts
  private promptChanged(live: Live, item: ApprovalItem | QuestionItem): void {
    if (item.resolved === undefined) {
      live.prompts.add(item.id)
      this.setStatus(live, 'needs-input')
      const prompt =
        item.kind === 'approval'
          ? { kind: 'approval' as const, text: [item.title, item.detail?.split('\n')[0]].filter(Boolean).join(': ') }
          : { kind: 'question' as const, text: item.questions[0]?.question ?? item.title ?? 'Question' }
      this.attention.fire({ sessionId: live.record.id, reason: 'needs-input', prompt })
      return
    }
    live.prompts.delete(item.id)
    if (live.prompts.size === 0 && live.status === 'needs-input') this.setStatus(live, 'running')
  }
```

  (import `ApprovalItem` and `QuestionItem` types);
- in `turnEnded`, replace `this.attention.fire({ sessionId: live.record.id, reason: 'turn-ended' })` with:

```ts
    const { edits, commands } = lastTurnWork(live.items)
    const durationMs = live.turnStartedAt ? Date.now() - live.turnStartedAt : 0
    this.attention.fire({ sessionId: live.record.id, reason: 'turn-ended', durationMs, edits, commands })
```

- in `fail`, after `this.setStatus(live, 'error')`, add `this.attention.fire({ sessionId: live.record.id, reason: 'failed', text })`;
- add at module level:

```ts
/** Files edited and commands run since the last user message. */
function lastTurnWork(items: Map<string, SessionItem>): { edits: number; commands: number } {
  let files = new Set<string>()
  let commands = 0
  for (const item of items.values()) {
    if (item.kind === 'message' && item.role === 'user') {
      files = new Set()
      commands = 0
    } else if (item.kind === 'diff') files.add(item.path)
    else if (item.kind === 'tool' && item.toolKind === 'execute') commands++
  }
  return { edits: files.size, commands }
}
```

Run: `pnpm test && pnpm typecheck` → PASS; clean (the existing consumers only read `sessionId` and `reason`).

- [ ] **Step 3: Commit**

```bash
git add src/sessions/manager.ts test/sessions/manager.test.ts
git commit -m "feat(sessions): attention events say what happened"
```

---

### Task 2: Banner, sound, and popup commands

**Files:**
- Create: `src/notify/compose.ts`, `src/notify/sound.ts`, `src/notify/popup.ts`
- Test: `test/notify/notify.test.ts`

- [ ] **Step 1: Write the failing tests**

`test/notify/notify.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { banner, compose } from '../../src/notify/compose'
import { popupCommand } from '../../src/notify/popup'
import { soundCommand } from '../../src/notify/sound'

describe('compose', () => {
  it('frames the workspace and event, the chat, then the detail', () => {
    expect(compose({ workspace: 'docsum', event: '✅ finished', chat: 'retry-fix · Codex: Fix the retry', detail: ['Edited 2 files · ran 5 commands'] })).toEqual({
      title: 'docsum | ✅ finished',
      body: '• retry-fix · Codex: Fix the retry •\n\nEdited 2 files · ran 5 commands'
    })
  })

  it('shortens a long chat title at a word', () => {
    const { body } = compose({ workspace: 'w', event: 'e', chat: 'word '.repeat(60), detail: ['a', 'b'] })
    expect(body.split('\n')[0].length).toBeLessThanOrEqual(40)
    expect(body.split('\n')[0]).toMatch(/…/)
  })
})

describe('banner', () => {
  const chat = { workspace: 'docsum', lane: 'retry-fix', provider: 'Codex', title: 'Fix the retry' }

  it('describes a finished turn by its work', () => {
    expect(banner(chat, { reason: 'turn-ended', durationMs: 1, edits: 2, commands: 5 })).toEqual({
      event: 'finished',
      title: 'docsum | ✅ finished',
      body: '• retry-fix · Codex: Fix the retry •\n\nEdited 2 files · ran 5 commands'
    })
    expect(banner({ ...chat, lane: undefined }, { reason: 'turn-ended', durationMs: 1, edits: 1, commands: 0 }).body).toBe(
      '• Codex: Fix the retry •\n\nEdited 1 file'
    )
    expect(banner(chat, { reason: 'turn-ended', durationMs: 1, edits: 0, commands: 0 }).body).toBe('• retry-fix · Codex: Fix the retry •\n\nReplied')
  })

  it('shows the approval, the question, or the failure', () => {
    expect(banner(chat, { reason: 'needs-input', prompt: { kind: 'approval', text: 'Allow Codex to run this command?: pnpm db:migrate' } })).toMatchObject({
      event: 'approval',
      title: 'docsum | ❗ needs approval'
    })
    expect(banner(chat, { reason: 'needs-input', prompt: { kind: 'question', text: 'Which TTL?' } })).toMatchObject({
      event: 'question',
      title: 'docsum | ❓ question',
      body: '• retry-fix · Codex: Fix the retry •\n\nWhich TTL?'
    })
    expect(banner(chat, { reason: 'failed', text: 'boom\nstack' })).toMatchObject({ event: 'failed', title: 'docsum | ✖ failed', body: expect.stringMatching(/boom$/) })
  })
})

describe('soundCommand', () => {
  it('plays system sounds per platform with volume where supported', () => {
    expect(soundCommand('darwin', 'Hero', 0.5)).toEqual({ file: 'afplay', args: ['-v', '0.5', '/System/Library/Sounds/Hero.aiff'] })
    expect(soundCommand('linux', 'Hero', 1)).toMatchObject({ shell: expect.stringContaining('complete.oga') })
    expect(soundCommand('win32', 'Hero', 1)).toMatchObject({ shell: expect.stringContaining('powershell') })
  })
})

describe('popupCommand', () => {
  it('uses terminal-notifier when available, else osascript', () => {
    expect(popupCommand('darwin', 'T', 'B', { terminalNotifier: '/opt/homebrew/bin/terminal-notifier', focus: 'code /w' })).toEqual({
      file: '/opt/homebrew/bin/terminal-notifier',
      args: ['-title', 'T', '-message', 'B', '-execute', 'code /w']
    })
    expect(popupCommand('darwin', 'T "x"', 'B', {})).toEqual({ file: 'osascript', args: ['-e', 'display notification "B" with title "T \\"x\\""'] })
    expect(popupCommand('linux', 'T', 'B', {})).toEqual({ file: 'notify-send', args: ['T', 'B'] })
    expect(popupCommand('win32', "T's", 'B', {})).toMatchObject({ shell: expect.stringContaining('powershell') })
  })
})
```

Run: `pnpm test test/notify` → FAIL.

- [ ] **Step 2: Implement**

`src/notify/compose.ts`:

```ts
import type { Attention } from '../sessions/manager'

// From claude-notifier: ~40 characters per banner line, four body lines.
const LINE = 40
const BODY_LINES = 4
const CHROME = 4

export const EVENTS = {
  finished: '✅ finished',
  approval: '❗ needs approval',
  question: '❓ question',
  failed: '✖ failed'
} as const

export type NotifyEvent = keyof typeof EVENTS

function truncate(text: string, max: number): string {
  if (text.length <= max) return text
  const cut = text.slice(0, max - 1)
  const space = cut.lastIndexOf(' ')
  return `${space > max / 2 ? cut.slice(0, space) : cut}…`
}

/** The banner frame: the detail takes the lines it needs, the chat title the rest. */
export function compose(input: { workspace: string; event: string; chat: string; detail: string[] }): { title: string; body: string } {
  const spare = Math.max(1, BODY_LINES - input.detail.length - (input.detail.length > 0 ? 1 : 0))
  const lines = [`• ${truncate(input.chat, spare * LINE - CHROME)} •`]
  if (input.detail.length > 0) lines.push('', ...input.detail)
  return { title: `${input.workspace} | ${input.event}`, body: lines.join('\n') }
}

export type ChatLabel = { workspace: string; lane?: string; provider: string; title: string }
type AttentionDetail = Attention extends infer A ? (A extends { sessionId: string } ? Omit<A, 'sessionId'> : never) : never

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? '' : 's'}`

function work(edits: number, commands: number): string {
  const parts = [edits > 0 ? `Edited ${plural(edits, 'file')}` : '', commands > 0 ? `ran ${plural(commands, 'command')}` : ''].filter(Boolean)
  if (parts.length === 0) return 'Replied'
  const text = parts.join(' · ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** What the notification says for an attention event. */
export function banner(chat: ChatLabel, attention: AttentionDetail): { event: NotifyEvent; title: string; body: string } {
  const label = `${chat.lane ? `${chat.lane} · ` : ''}${chat.provider}: ${chat.title}`
  const [event, detail]: [NotifyEvent, string] =
    attention.reason === 'turn-ended'
      ? ['finished', work(attention.edits, attention.commands)]
      : attention.reason === 'failed'
        ? ['failed', attention.text.split('\n')[0]]
        : [attention.prompt.kind === 'approval' ? 'approval' : 'question', attention.prompt.text]
  return { event, ...compose({ workspace: chat.workspace, event: EVENTS[event], chat: label, detail: [truncate(detail, LINE * 2)] }) }
}
```

`src/notify/sound.ts`:

```ts
// System sounds, as in claude-notifier. Windows ignores volume; Linux plays freedesktop sounds.
const MAC_DIR = '/System/Library/Sounds'
export const SOUNDS = ['Basso', 'Blow', 'Bottle', 'Frog', 'Funk', 'Glass', 'Hero', 'Morse', 'Ping', 'Pop', 'Purr', 'Sosumi', 'Submarine', 'Tink'] as const

const LINUX_DIR = '/usr/share/sounds/freedesktop/stereo'
const LINUX: Record<string, string> = {
  Basso: 'dialog-warning',
  Blow: 'service-logout',
  Bottle: 'bell',
  Frog: 'message-new-instant',
  Funk: 'message-new-instant',
  Glass: 'bell',
  Hero: 'complete',
  Morse: 'message',
  Ping: 'message',
  Pop: 'dialog-information',
  Purr: 'service-login',
  Sosumi: 'dialog-warning',
  Submarine: 'alarm-clock-elapsed',
  Tink: 'bell'
}
const WINDOWS: Record<string, string> = { Basso: 'Windows Critical Stop', Hero: 'tada', Glass: 'chimes', Ping: 'notify', Funk: 'chord' }

export type Command = { file: string; args: string[] } | { shell: string }

const shQuote = (text: string) => `'${text.replace(/'/g, `'\\''`)}'`

export function soundCommand(platform: NodeJS.Platform, sound: string, volume: number): Command {
  if (platform === 'darwin') return { file: 'afplay', args: ['-v', String(volume), `${MAC_DIR}/${sound}.aiff`] }
  if (platform === 'win32') {
    const path = `C:\\Windows\\Media\\${WINDOWS[sound] ?? 'Windows Notify'}.wav`
    const script = `$s='${path.replace(/'/g, "''")}'; if(Test-Path $s){(New-Object Media.SoundPlayer $s).PlaySync()}`
    return { shell: `powershell -NoProfile -NonInteractive -EncodedCommand ${Buffer.from(script, 'utf16le').toString('base64')}` }
  }
  const path = shQuote(`${LINUX_DIR}/${LINUX[sound] ?? 'complete'}.oga`)
  return { shell: `pw-play --volume=${volume} ${path} 2>/dev/null || paplay --volume=${Math.round(volume * 65536)} ${path} 2>/dev/null` }
}
```

`src/notify/popup.ts`:

```ts
import type { Command } from './sound'

/** An OS notification. On macOS, terminal-notifier makes a click bring VS Code forward (`focus` is the shell command it runs). */
export function popupCommand(
  platform: NodeJS.Platform,
  title: string,
  body: string,
  options: { terminalNotifier?: string; focus?: string }
): Command {
  if (platform === 'darwin') {
    if (options.terminalNotifier) {
      return { file: options.terminalNotifier, args: ['-title', title, '-message', body, ...(options.focus ? ['-execute', options.focus] : [])] }
    }
    const escape = (text: string) => text.replace(/[\\"]/g, '\\$&')
    return { file: 'osascript', args: ['-e', `display notification "${escape(body)}" with title "${escape(title)}"`] }
  }
  if (platform === 'win32') {
    const quote = (text: string) => text.replace(/'/g, "''")
    const script = `Add-Type -AssemblyName System.Windows.Forms; $n=New-Object System.Windows.Forms.NotifyIcon; $n.Icon=[System.Drawing.SystemIcons]::Information; $n.Visible=$true; $n.ShowBalloonTip(4000,'${quote(title)}','${quote(body)}',[System.Windows.Forms.ToolTipIcon]::None); Start-Sleep -m 500; $n.Dispose()`
    return { shell: `powershell -NoProfile -NonInteractive -EncodedCommand ${Buffer.from(script, 'utf16le').toString('base64')}` }
  }
  return { file: 'notify-send', args: [title, body] }
}
```

Run: `pnpm test test/notify` → PASS.

- [ ] **Step 3: Commit**

```bash
git add src/notify test/notify
git commit -m "feat(notify): banner text, sound, and popup commands per platform"
```

---

### Task 3: The notifier

**Files:**
- Create: `src/ui/notifier.ts`
- Modify: `src/ui/chat-surfaces.ts`, `src/extension.ts`, `package.json`

- [ ] **Step 1: Settings**

In `package.json`, add a `contributes.configuration` section (or extend the existing one, following its style), titled "AgentDeck":

```json
"agentdeck.notifications.finished.level": { "type": "string", "enum": ["sound+popup", "sound", "popup", "off"], "default": "sound+popup", "description": "When a chat finishes a turn." },
"agentdeck.notifications.finished.sound": { "type": "string", "enum": ["Basso", "Blow", "Bottle", "Frog", "Funk", "Glass", "Hero", "Morse", "Ping", "Pop", "Purr", "Sosumi", "Submarine", "Tink"], "default": "Hero" },
"agentdeck.notifications.approval.level": { "type": "string", "enum": ["sound+popup", "sound", "popup", "off"], "default": "sound+popup", "description": "When a chat needs an approval." },
"agentdeck.notifications.approval.sound": { "type": "string", "enum": [same list], "default": "Glass" },
"agentdeck.notifications.question.level": { …, "default": "sound+popup", "description": "When a chat asks a question." },
"agentdeck.notifications.question.sound": { …, "default": "Ping" },
"agentdeck.notifications.failed.level": { …, "default": "sound+popup", "description": "When a turn fails." },
"agentdeck.notifications.failed.sound": { …, "default": "Basso" },
"agentdeck.notifications.volume": { "type": "number", "minimum": 0, "maximum": 2, "default": 1, "description": "Sound volume (1 = system volume; macOS and Linux)." },
"agentdeck.notifications.minDurationSeconds": { "type": "number", "minimum": 0, "default": 10, "description": "Only notify that a turn finished when it ran at least this long." },
"agentdeck.notifications.muteWhenFocused": { "type": "boolean", "default": true, "description": "Stay quiet while VS Code is focused and the chat is visible." }
```

(write each enum out in full in the JSON; `[same list]` above means the 14 names). Also add a command `agentdeck.testNotification` "Test Notification" (category AgentDeck).

- [ ] **Step 2: The notifier**

In `src/ui/chat-surfaces.ts`, make `visible(sessionId)` public (rename nothing; change `private visible` to `visible`).

`src/ui/notifier.ts`:

```ts
import { execFile, exec } from 'node:child_process'
import { accessSync, constants } from 'node:fs'
import { basename, join } from 'node:path'
import * as vscode from 'vscode'
import type { Disposable } from '../core/emitter'
import { banner, type ChatLabel, type NotifyEvent } from '../notify/compose'
import { popupCommand } from '../notify/popup'
import { type Command, soundCommand } from '../notify/sound'
import type { Attention, SessionManager } from '../sessions/manager'

type Level = 'sound+popup' | 'sound' | 'popup' | 'off'

function run(command: Command): void {
  if ('file' in command) execFile(command.file, command.args, () => {})
  else exec(command.shell, { timeout: 10_000 }, () => {})
}

function findTerminalNotifier(): string | undefined {
  if (process.platform !== 'darwin') return undefined
  for (const candidate of ['/opt/homebrew/bin/terminal-notifier', '/usr/local/bin/terminal-notifier']) {
    try {
      accessSync(candidate, constants.X_OK)
      return candidate
    } catch {
      // Not here.
    }
  }
  return undefined
}

/** Native notifications from AgentDeck's own session events (decision 35). */
export class Notifier implements vscode.Disposable {
  private readonly subscription: Disposable
  private readonly terminalNotifier = findTerminalNotifier()

  constructor(
    private readonly manager: SessionManager,
    private readonly labels: ReadonlyMap<string, string>,
    private readonly isVisible: (sessionId: string) => boolean
  ) {
    this.subscription = manager.onAttention((attention) => this.notify(attention))
  }

  /** Shows one notification of the given event for the most recent chat, for trying settings out. */
  test(event: NotifyEvent): void {
    const record = this.manager.list()[0]?.record
    const chat: ChatLabel = { workspace: this.workspace(), provider: record ? this.label(record.providerId) : 'Claude', title: record?.title ?? 'Test chat' }
    const detail =
      event === 'finished'
        ? ({ reason: 'turn-ended', durationMs: 60_000, edits: 2, commands: 3 } as const)
        : event === 'failed'
          ? ({ reason: 'failed', text: 'Something went wrong' } as const)
          : ({ reason: 'needs-input', prompt: { kind: event === 'approval' ? 'approval' : 'question', text: event === 'approval' ? 'Allow Bash?: pnpm test' : 'Which option?' } } as const)
    this.deliver(event, banner(chat, detail), true)
  }

  dispose(): void {
    this.subscription.dispose()
  }

  private notify(attention: Attention): void {
    const record = this.manager.list().find((entry) => entry.record.id === attention.sessionId)?.record
    if (!record) return
    const config = vscode.workspace.getConfiguration('agentdeck.notifications')
    if (attention.reason === 'turn-ended' && attention.durationMs < config.get<number>('minDurationSeconds', 10) * 1000) return
    if (config.get<boolean>('muteWhenFocused', true) && vscode.window.state.focused && this.isVisible(record.id)) return
    const { sessionId: _id, ...detail } = attention
    const shown = banner(
      { workspace: this.workspace(), ...(record.laneId ? { lane: record.laneId } : {}), provider: this.label(record.providerId), title: record.title },
      detail
    )
    this.deliver(shown.event, shown, false)
  }

  private deliver(event: NotifyEvent, shown: { title: string; body: string }, force: boolean): void {
    const config = vscode.workspace.getConfiguration('agentdeck.notifications')
    const level = config.get<Level>(`${event}.level`, 'sound+popup')
    if (level === 'off' && !force) return
    if (level.includes('sound') || force) {
      run(soundCommand(process.platform, config.get<string>(`${event}.sound`, 'Hero'), config.get<number>('volume', 1)))
    }
    if (level.includes('popup') || force) {
      const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
      const codeCli = join(vscode.env.appRoot, 'bin', 'code')
      const focus = folder ? `'${codeCli.replace(/'/g, `'\\''`)}' '${folder.replace(/'/g, `'\\''`)}'` : undefined
      run(popupCommand(process.platform, shown.title, shown.body, { terminalNotifier: this.terminalNotifier, focus }))
    }
  }

  private workspace(): string {
    const file = vscode.workspace.workspaceFile
    if (file?.scheme === 'file') return basename(file.fsPath).replace(/\.code-workspace$/, '')
    return vscode.workspace.workspaceFolders?.[0]?.name ?? 'AgentDeck'
  }

  private label(providerId: string): string {
    return this.labels.get(providerId) ?? providerId
  }
}
```

(if the linter rejects the unused `_id`, build `detail` without `sessionId` another way and report.)

- [ ] **Step 3: Wiring**

In `src/extension.ts`:
- import `Notifier` from `./ui/notifier`;
- change `const getEnv = () => (env ??= captureEnv())` to:

```ts
  // claude-notifier's hooks stay quiet for the CLIs AgentDeck runs; AgentDeck notifies itself.
  const getEnv = () => (env ??= captureEnv().then((captured) => ({ ...captured, CLAUDE_NOTIFIER_DISABLE: '1' })))
```

- after `surfaces` is created, add `const notifier = new Notifier(sessionManager, new Map([...providers].map(([id, provider]) => [id, provider.label])), (id) => surfaces.visible(id))` and push `notifier` plus:

```ts
    vscode.commands.registerCommand('agentdeck.testNotification', async () => {
      const event = await vscode.window.showQuickPick(['finished', 'approval', 'question', 'failed'], { placeHolder: 'Which notification?' })
      if (event) notifier.test(event as 'finished' | 'approval' | 'question' | 'failed')
    }),
```

Run: `pnpm typecheck && pnpm test && pnpm build` → clean; PASS; built.

- [ ] **Step 4: Live check**

Run (macOS): `node -e "require('child_process').execFile('afplay', ['-v','0.5','/System/Library/Sounds/Hero.aiff'], e => console.log(e ? 'SOUND FAILED ' + e.message : 'SOUND OK'))"` → `SOUND OK`. (This only checks the command shape works on this machine; the in-editor check is the user's.)

- [ ] **Step 5: Package, docs, commit**

Run: `pnpm test && pnpm run package` → PASS; packaged.

In `docs/superpowers/plans/2026-10-28-mvp-overview.md`, add a row:

```
| 17 | [Notifications](2026-10-29-17-notifications.md) | Native sound and popups for finished turns, approvals, questions, and failures; claude-notifier's settings; `CLAUDE_NOTIFIER_DISABLE` for spawned CLIs | Done |
```

In `docs/roadmap.md`, make the line starting `- **17 — Notifications**` end with ` ✓ done.`

```bash
git add src package.json docs
git commit -m "feat(notify): native notifications for turns, approvals, questions, and failures"
```
