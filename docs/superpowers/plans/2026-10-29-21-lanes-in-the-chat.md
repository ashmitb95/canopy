# Plan 21: Lanes in the chat — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first. **Commit at every checkpoint** (each step whose check passes) so a usage limit cannot lose work; end each task with its named commit. Write files with the code itself; never extract code blocks from this plan with `sed` line ranges. Run each new test red before implementing.

**Goal:** The chat itself shows which lane it is on, and you can change that without leaving the chat. The sidebar's session switcher groups chats by lane, and *Review lane changes* opens everything a lane changed in every repo in one multi-diff editor.

**Architecture:** decision 36. A lane chip in the composer sits next to the mode picker. It lists the lanes, *No lane*, *New lane…*, and *Review lane changes*.

**The host:**
- **Lanes message:** it posts a `lanes` message whenever the lanes or chats change. It is sent only when lanes are available (a folder is open); otherwise the chip stays hidden.
- **Lane message:** it posts a `lane` message telling each surface which lane its chat is on.
- **Chat list:** the session summaries carry `laneId`, so the switcher can group them.

**Lane changes:**
- **What counts:** a lane's changes are everything since it left base in each of its checkouts: commits, uncommitted edits, and untracked files.
- **How they're computed:** `git merge-base` plus `git diff --name-status` plus `git ls-files --others`.
- **How they're shown:** a `agentdeck-git:` content provider serves the base side of each file.

**Tech Stack:** as before.

---

## File structure

| File | Responsibility |
|---|---|
| `src/lanes/lanes.ts` | `laneDescription` moves here (pure, usable by the webview) |
| `src/lanes/changes.ts` | Files a lane changed in one checkout |
| `src/ui/lane-changes.ts` | Base-side content provider; open a lane's changes in the multi-diff editor |
| `src/ui/protocol.ts`, `src/ui/chat-surfaces.ts` | `lanes`/`lane` messages; `setLane`, `newLane`, `reviewLane` |
| `webview/app/state.ts`, `webview/app/lanes.ts` | Lane state; grouping recent sessions |
| `webview/app/components/lane-picker.tsx`, `composer.tsx`, `session-switcher.tsx` | The chip; grouped switcher |
| `src/ui/sessions-tree.ts`, `src/extension.ts`, `package.json` | Wiring; *Review Lane Changes* on a lane |

---

### Task 1: Lane description and lane changes

**Files:**
- Modify: `src/lanes/lanes.ts`, `src/ui/sessions-tree.ts`, `src/extension.ts`
- Create: `src/lanes/changes.ts`
- Test: `test/lanes/changes.test.ts`, `test/lanes/lanes.test.ts`

- [ ] **Step 1: Write the failing tests**

Add to `test/lanes/lanes.test.ts` (import `laneDescription` from `../../src/lanes/lanes` with the others):

```ts
describe('laneDescription', () => {
  it('says where the lane lives in each repo, with uncommitted files', () => {
    expect(laneDescription(deriveLanes(repos).find((lane) => lane.name === 'retry-fix') ?? { name: '', repos: [] })).toBe(
      'api main ●2 · ui worktree ●1'
    )
    expect(laneDescription({ name: 'p', repos: [] })).toBe('no checkout')
  })
})
```

`test/lanes/changes.test.ts`:

```ts
import { rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { checkoutChanges } from '../../src/lanes/changes'
import { repo, run, workspace } from './repos'

describe('checkoutChanges', () => {
  it('lists commits since base, uncommitted edits, and untracked files', async () => {
    const api = repo(join(workspace(), 'api'))
    writeFileSync(join(api, 'gone.txt'), 'x')
    run(api, 'add', '.')
    run(api, 'commit', '-q', '-m', 'gone')
    run(api, 'checkout', '-q', '-b', 'lane')
    writeFileSync(join(api, 'README.md'), 'changed')
    rmSync(join(api, 'gone.txt'))
    run(api, 'commit', '-q', '-am', 'work')
    writeFileSync(join(api, 'committed-later.txt'), 'y')
    run(api, 'add', '.')
    run(api, 'commit', '-q', '-m', 'add')
    writeFileSync(join(api, 'README.md'), 'changed again')
    writeFileSync(join(api, 'new.txt'), 'n')
    const changes = await checkoutChanges(api, 'main')
    const base = run(api, 'rev-parse', 'main').trim()
    expect(changes.sort((a, b) => (a.path < b.path ? -1 : 1))).toEqual([
      { path: join(api, 'README.md'), status: 'modified', ref: base },
      { path: join(api, 'committed-later.txt'), status: 'added', ref: base },
      { path: join(api, 'gone.txt'), status: 'deleted', ref: base },
      { path: join(api, 'new.txt'), status: 'added', ref: base }
    ])
  })
})
```

Run: `pnpm test test/lanes/changes.test.ts test/lanes/lanes.test.ts` → FAIL.

- [ ] **Step 2: Implement**

In `src/lanes/lanes.ts`, add (moved from `src/ui/sessions-tree.ts`):

```ts
/** "api main ●2 · ui worktree": where the lane's code lives in each repo, with uncommitted files. */
export function laneDescription(lane: Lane): string {
  if (lane.repos.length === 0) return 'no checkout'
  return lane.repos.map((repo) => `${repo.repo} ${repo.location}${repo.dirty > 0 ? ` ●${repo.dirty}` : ''}`).join(' · ')
}
```

In `src/ui/sessions-tree.ts`, delete `laneDescription` there and import it from `../lanes/lanes` (with `deriveLanes` and `Lane`). In `src/extension.ts`, import `laneDescription` from `./lanes/lanes` instead of `./ui/sessions-tree`.

`src/lanes/changes.ts`:

```ts
import { join } from 'node:path'
import { git } from './git'

export type FileChange = { path: string; status: 'added' | 'modified' | 'deleted'; ref: string }

/** Everything a checkout changed since it left `base`: commits, uncommitted edits, and untracked files. `ref` is the merge base. */
export async function checkoutChanges(checkout: string, base: string): Promise<FileChange[]> {
  const ref = (await git(checkout, ['merge-base', base, 'HEAD'])).trim()
  const fields = (await git(checkout, ['diff', '--name-status', '--no-renames', '-z', ref])).split('\0').filter(Boolean)
  const changes: FileChange[] = []
  for (let index = 0; index + 1 < fields.length; index += 2) {
    const letter = fields[index]
    changes.push({
      path: join(checkout, fields[index + 1]),
      status: letter === 'A' ? 'added' : letter === 'D' ? 'deleted' : 'modified',
      ref
    })
  }
  const untracked = (await git(checkout, ['ls-files', '--others', '--exclude-standard', '-z'])).split('\0').filter(Boolean)
  for (const file of untracked) changes.push({ path: join(checkout, file), status: 'added', ref })
  return changes
}
```

Run: `pnpm test test/lanes && pnpm typecheck` → PASS; clean.

- [ ] **Step 3: Commit**

```bash
git add src/lanes src/ui/sessions-tree.ts src/extension.ts test/lanes
git commit -m "feat(lanes): what a lane changed per checkout; lane description is shared"
```

---

### Task 2: Protocol and host

**Files:**
- Modify: `src/ui/protocol.ts`, `src/ui/chat-surfaces.ts`

- [ ] **Step 1: Protocol**

In `src/ui/protocol.ts`:
- add `export type LaneInfo = { name: string; where: string }`;
- add `laneId?: string` to `SessionSummary`;
- add host messages: `| { type: 'lanes'; lanes: LaneInfo[] }` and `| { type: 'lane'; sessionId: string; laneId?: string }`;
- add webview messages: `| { type: 'setLane'; laneId?: string }`, `| { type: 'newLane' }`, `| { type: 'reviewLane'; laneId: string }`.

- [ ] **Step 2: Host**

In `src/ui/chat-surfaces.ts`:
- import `LaneInfo` with the protocol types and `type Event` from `../core/emitter`;
- add and export, above the class:

```ts
/** Lanes for the chat's lane chip; absent when no folder is open. */
export type LaneSource = { list(): LaneInfo[]; onDidChange: Event<void> }
```

- add a constructor parameter after `diffs`: `private readonly lanes?: LaneSource`;
- in the constructor's `subscriptions.push(…)`, change the `manager.onDidChange` handler body to also call `this.postLanes()`, and add `...(lanes ? [lanes.onDidChange(() => this.postLanes())] : []),`;
- in `case 'ready'`, after `this.postSessions(surface)`, add `this.postLanes(surface)`;
- in `postSessions`, add `...(record.laneId ? { laneId: record.laneId } : {})` to each summary;
- add the cases to the webview message switch (next to `'reviewChanges'`):

```ts
      case 'setLane':
        if (sessionId) await this.manager.setLane(sessionId, message.laneId)
        return
      case 'newLane':
        await vscode.commands.executeCommand('agentdeck.newLane')
        return
      case 'reviewLane':
        await vscode.commands.executeCommand('agentdeck.reviewLane', message.laneId)
        return
```

- add the method after `postSessions`:

```ts
  /** Every surface gets the lane list and the lane its own chat is on. */
  private postLanes(only?: Surface): void {
    if (!this.lanes) return
    const lanes = this.lanes.list()
    const surfaces = only ? [only] : [...[...this.panels.values()].map(({ surface }) => surface), ...this.blankPanels, ...(this.sidebar ? [this.sidebar] : [])]
    for (const surface of surfaces) {
      this.post(surface, { type: 'lanes', lanes })
      if (!surface.sessionId) continue
      const laneId = this.manager.list().find(({ record }) => record.id === surface.sessionId)?.record.laneId
      this.post(surface, { type: 'lane', sessionId: surface.sessionId, ...(laneId ? { laneId } : {}) })
    }
  }
```

  (if `blankPanels` is not iterable as `Surface`s, adapt to how `broadcast` iterates it and report);
- in `show(surface, sessionId)` (where a surface starts showing a session), call `this.postLanes(surface)` at the end, so a newly shown chat gets its lane.

Run: `pnpm typecheck` → errors only in `src/extension.ts` if the constructor call needs the new argument (it is optional, so none expected) and in `webview` for unhandled message types (Task 3).

- [ ] **Step 3: Commit**

```bash
git add src/ui
git commit -m "feat(ui): lanes and each chat's lane reach the webview"
```

---

### Task 3: The lane chip and the grouped switcher

**Files:**
- Modify: `webview/app/state.ts`, `webview/app/components/composer.tsx`, `webview/app/components/session-switcher.tsx`
- Create: `webview/app/lanes.ts`, `webview/app/components/lane-picker.tsx`
- Test: `test/webview/state.test.ts`, `test/webview/lanes.test.ts`

- [ ] **Step 1: Write the failing tests**

Add inside the `describe` block of `test/webview/state.test.ts`:

```ts
  it('keeps the lane list and the lane of the chat it shows', () => {
    let state = reduce(initialState, { type: 'session', sessionId: 's1', event: { type: 'snapshot', record, status: 'idle', items: [], queue: [] } })
    state = reduce(state, { type: 'lanes', lanes: [{ name: 'x', where: 'api main' }] })
    state = reduce(state, { type: 'lane', sessionId: 's1', laneId: 'x' })
    expect(state.lanes).toEqual([{ name: 'x', where: 'api main' }])
    expect(state.record?.laneId).toBe('x')
    state = reduce(state, { type: 'lane', sessionId: 'other', laneId: 'y' })
    expect(state.record?.laneId).toBe('x')
    state = reduce(state, { type: 'lane', sessionId: 's1' })
    expect(state.record?.laneId).toBeUndefined()
  })
```

`test/webview/lanes.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { SessionSummary } from '../../src/ui/protocol'
import { groupRecent } from '../../webview/app/lanes'

const session = (id: string, laneId?: string): SessionSummary => ({
  id,
  title: id,
  providerId: 'claude',
  status: 'idle',
  updatedAt: 't',
  inTab: false,
  ...(laneId ? { laneId } : {})
})

describe('groupRecent', () => {
  it('is one Recent group when no chat is on a lane', () => {
    const sessions = [session('a'), session('b')]
    expect(groupRecent(sessions)).toEqual([{ heading: 'Recent', sessions }])
  })

  it('groups by lane in order of most recent chat, then No lane', () => {
    expect(groupRecent([session('a', 'x'), session('b'), session('c', 'y'), session('d', 'x')])).toEqual([
      { heading: 'x', sessions: [session('a', 'x'), session('d', 'x')] },
      { heading: 'y', sessions: [session('c', 'y')] },
      { heading: 'No lane', sessions: [session('b')] }
    ])
  })
})
```

Run: `pnpm test test/webview` → FAIL.

- [ ] **Step 2: State and grouping**

In `webview/app/state.ts`:
- import `LaneInfo` with the protocol types;
- add to `ChatState`: `/** Lanes for the lane chip; undefined when lanes are unavailable (no folder). */ lanes?: LaneInfo[]`;
- in the `'empty'` case, carry `lanes: state.lanes` into the new state like `sessions`;
- add cases:

```ts
    case 'lanes':
      return { ...state, lanes: message.lanes }
    case 'lane': {
      if (message.sessionId !== state.sessionId || !state.record) return state
      const { laneId: _previous, ...record } = state.record
      return { ...state, record: message.laneId ? { ...record, laneId: message.laneId } : record }
    }
```

  (if the linter rejects the unused `_previous`, build `record` with `structuredClone` and `delete` instead).

`webview/app/lanes.ts`:

```ts
import type { SessionSummary } from '../../src/ui/protocol'

export type RecentGroup = { heading: string; sessions: SessionSummary[] }

/** The switcher's recent chats: one list, or grouped by lane (in order of each lane's most recent chat) with chats on no lane last. */
export function groupRecent(sessions: SessionSummary[]): RecentGroup[] {
  if (!sessions.some((session) => session.laneId)) return [{ heading: 'Recent', sessions }]
  const groups = new Map<string, SessionSummary[]>()
  for (const session of sessions) {
    if (!session.laneId) continue
    groups.set(session.laneId, [...(groups.get(session.laneId) ?? []), session])
  }
  const loose = sessions.filter((session) => !session.laneId)
  return [
    ...[...groups].map(([heading, grouped]) => ({ heading, sessions: grouped })),
    ...(loose.length > 0 ? [{ heading: 'No lane', sessions: loose }] : [])
  ]
}
```

Run: `pnpm test test/webview` → PASS.

- [ ] **Step 3: The chip**

`webview/app/components/lane-picker.tsx`:

```tsx
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import type { LaneInfo } from '../../../src/ui/protocol'
import { send } from '../host'
import { Codicon } from './codicon'

const NONE = ''

/** Which lane the chat is on: the lane decides where it may write and what its brief says. */
export function LanePicker({ lanes, current }: { lanes?: LaneInfo[]; current?: string }) {
  if (!lanes) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="xs" variant="ghost" className="min-w-0 text-muted-foreground" title={current ? `Lane: ${current}` : 'No lane'}>
          <Codicon name="git-branch" size={12} />
          <span className="hidden max-w-32 truncate @[26rem]:inline">{current ?? 'No lane'}</span>
          <Codicon name="chevron-down" size={12} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-w-80">
        <DropdownMenuRadioGroup
          value={current ?? NONE}
          onValueChange={(laneId) => send({ type: 'setLane', ...(laneId === NONE ? {} : { laneId }) })}
        >
          {lanes.map((lane) => (
            <DropdownMenuRadioItem key={lane.name} value={lane.name}>
              <span className="min-w-0 flex-1 truncate">{lane.name}</span>
              <span className="truncate text-xs text-muted-foreground">{lane.where}</span>
            </DropdownMenuRadioItem>
          ))}
          <DropdownMenuRadioItem value={NONE}>No lane</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => send({ type: 'newLane' })}>
          <Codicon name="add" size={12} />
          New lane…
        </DropdownMenuItem>
        {current && (
          <DropdownMenuItem onSelect={() => send({ type: 'reviewLane', laneId: current })}>
            <Codicon name="diff-multiple" size={12} />
            Review lane changes
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
```

(If `DropdownMenuSeparator` or `DropdownMenuItem` is not exported by `webview/components/ui/dropdown-menu.tsx`, check the file: shadcn's dropdown-menu exports both; if they are missing, add them the way shadcn defines them. If the `diff-multiple` codicon does not exist in the codicon CSS, use `diff`.)

In `webview/app/components/composer.tsx`, import `LanePicker` and render it right after `<ModePicker … />`:

```tsx
          <LanePicker lanes={state.lanes} current={state.record?.laneId} />
```

- [ ] **Step 4: The grouped switcher**

In `webview/app/components/session-switcher.tsx`, import `groupRecent` from `../lanes` and replace the `<CommandGroup heading="Recent">…</CommandGroup>` block with:

```tsx
            {groupRecent(state.sessions).map((group) => (
              <CommandGroup key={group.heading} heading={group.heading}>
                {group.sessions.map((session) => (
                  <CommandItem
                    key={session.id}
                    value={`session:${session.id}`}
                    keywords={[session.title, ...(session.laneId ? [session.laneId] : [])]}
                    onSelect={() => choose({ type: 'switchSession', sessionId: session.id })}
                  >
                    <StatusDot status={session.status} />
                    <span className="min-w-0 flex-1 truncate">{session.title}</span>
                    {session.inTab && <span className="rounded border px-1 text-[10px] text-muted-foreground">in tab</span>}
                    <span className="text-xs text-muted-foreground">{relativeTime(session.updatedAt)}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
```

Run: `pnpm typecheck && pnpm test` → clean; PASS.

- [ ] **Step 5: Commit**

```bash
git add webview test/webview
git commit -m "feat(webview): lane chip in the composer and lane groups in the switcher"
```

---

### Task 4: Review lane changes, and wiring

**Files:**
- Create: `src/ui/lane-changes.ts`
- Modify: `src/extension.ts`, `package.json`

- [ ] **Step 1: The multi-diff**

`src/ui/lane-changes.ts`:

```ts
import { relative } from 'node:path'
import * as vscode from 'vscode'
import { checkoutChanges } from '../lanes/changes'
import { git } from '../lanes/git'
import type { Lane } from '../lanes/lanes'
import type { RepoState } from '../lanes/state'

export const GIT_SCHEME = 'agentdeck-git'

type Side = { cwd?: string; ref?: string; path?: string }

/** Opens everything a lane changed, across its repos, in VS Code's multi-diff editor; serves the base side from Git. */
export class LaneChanges implements vscode.TextDocumentContentProvider {
  provideTextDocumentContent(uri: vscode.Uri): Promise<string> {
    const side = JSON.parse(uri.query) as Side
    if (!side.cwd || !side.ref || !side.path) return Promise.resolve('')
    return git(side.cwd, ['show', `${side.ref}:${side.path}`]).catch(() => '')
  }

  async open(lane: Lane, repos: RepoState[]): Promise<void> {
    const resources: [vscode.Uri, vscode.Uri, vscode.Uri][] = []
    for (const laneRepo of lane.repos) {
      const base = repos.find((repo) => repo.name === laneRepo.repo)?.base
      if (!base) continue
      for (const change of await checkoutChanges(laneRepo.path, base)) {
        const path = relative(laneRepo.path, change.path)
        const name = `${laneRepo.repo}/${path}`
        const before = change.status === 'added' ? this.uri(name, {}) : this.uri(name, { cwd: laneRepo.path, ref: change.ref, path })
        const after = change.status === 'deleted' ? this.uri(name, {}) : vscode.Uri.file(change.path)
        resources.push([vscode.Uri.file(change.path), before, after])
      }
    }
    if (resources.length === 0) return void vscode.window.showInformationMessage(`${lane.name} has no changes yet.`)
    await vscode.commands.executeCommand('vscode.changes', `${lane.name}: changes`, resources)
  }

  private uri(name: string, side: Side): vscode.Uri {
    return vscode.Uri.from({ scheme: GIT_SCHEME, path: `/${name}`, query: JSON.stringify(side) })
  }
}
```

- [ ] **Step 2: Wiring**

In `src/extension.ts`:
- import `GIT_SCHEME, LaneChanges` from `./ui/lane-changes`, and `type LaneSource` from `./ui/chat-surfaces`;
- move the `const tree = new SessionsTree(…)` line above `const surfaces = new ChatSurfaces(…)` (it only needs the manager, labels, and tracker);
- before `const surfaces = …`, add:

```ts
  const laneSource: LaneSource | undefined = tracker
    ? { list: () => tree.lanes().map((lane) => ({ name: lane.name, where: laneDescription(lane) })), onDidChange: tracker.onDidChange }
    : undefined
  const laneChanges = new LaneChanges()
```

  and pass `laneSource` as the last argument of `new ChatSurfaces(…)`;
- add to the main `push(…)` list:

```ts
    vscode.workspace.registerTextDocumentContentProvider(GIT_SCHEME, laneChanges),
    vscode.commands.registerCommand('agentdeck.reviewLane', async (target: LaneNode | string) => {
      const name = typeof target === 'string' ? target : target.lane.name
      const lane = tree.lanes().find((candidate) => candidate.name === name)
      if (lane && tracker) await laneChanges.open(lane, tracker.repos)
    }),
```

In `package.json`, following the existing style: command `agentdeck.reviewLane` "Review Lane Changes" (category AgentDeck); `view/item/context` for `viewItem == lane` at `"1_open@2"`; `commandPalette` `"when": "false"`.

- [ ] **Step 3: Verify and commit**

Run: `pnpm typecheck && pnpm test && pnpm build` → clean; PASS; built.

```bash
git add src/ui/lane-changes.ts src/extension.ts package.json
git commit -m "feat(lanes): review a lane's changes across repos in one multi-diff"
```

---

### Task 5: Preview, package, hand-off

**Files:**
- Modify: `webview/preview/scenario.ts`

- [ ] **Step 1: Preview**

In `webview/preview/scenario.ts`:
- in the `sessions` message, add `laneId: 'retry-fix'` to the `s1` entry, and add a third session `{ id: 's3', title: 'Token rotation', providerId: 'codex', status: 'idle', updatedAt: '2026-10-28T08:00:00.000Z', inTab: false, laneId: 'auth-refresh' }`;
- add `laneId: 'retry-fix'` to the `record` constant;
- add to the default `chat` messages (after the `sessions` message): `{ type: 'lanes', lanes: [{ name: 'retry-fix', where: 'api main ●2 · ui worktree' }, { name: 'auth-refresh', where: 'ui worktree' }] }`.

Run: `pnpm build:preview && pnpm screenshot dark 900x1100 panel chat && pnpm screenshot dark 340x1100 view chat`
Open both: the composer shows a git-branch chip (with "retry-fix" at 900 px, icon only at 340 px) after the mode picker, nothing overflows. Open the switcher state is not scripted; skip it. Fix layout only in `lane-picker.tsx`. (If the scenario name for the default is not `chat`, use the name the screenshot script expects for the default scenario; check `scripts/screenshot.*`.)

- [ ] **Step 2: Package, docs, commit**

Run: `pnpm test && pnpm run package` → PASS; packaged.

In `docs/superpowers/plans/2026-10-28-mvp-overview.md`, add after the plan 20 row:

```
| 21 | [Lanes in the chat](2026-10-29-21-lanes-in-the-chat.md) | Lane chip in the composer, switcher grouped by lane, review a lane's changes across repos | Done |
```

In `docs/roadmap.md`, make the line starting `- **21 — Lanes in the chat list:**` end with ` ✓ done.`

```bash
git add webview/preview docs
git commit -m "docs: plan 21 done"
```
