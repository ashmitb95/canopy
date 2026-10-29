# Plan 19: Lane memory and briefs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first. **Commit at every checkpoint** (each step whose check passes) so a usage limit cannot lose work; end each task with its named commit. Write files with the code itself; never extract code blocks from this plan with `sed` line ranges (fence lines leak in).

**Goal:** Every chat on a lane starts oriented and stays current, without any new UI.
- **What a chat receives:**
  - **Brief:** on its first turn on the lane, a chat receives a short brief. It covers the lane's goal, where its code lives, its plan and notes, and what earlier chats did.
  - **Update:** on later turns, it receives an update listing what changed since its last turn.
- **What AgentDeck keeps** under `.agentdeck/`:
  - a summary of each chat;
  - a history of where the lane's checkouts moved.

**Architecture:** Plan 19 follows the [lanes spec](../specs/2026-10-29-lanes-and-control-center.md): *Stored intent* and *The lane brief and the lane delta*.
- **`LaneMemory`:** reads and writes `.agentdeck/lanes/<lane>/`. That folder holds:
  - `lane.toml`: the goal and when the lane was created;
  - `plan.md` and `notes.md`, which agents keep current;
  - `chats/<id>.md`;
  - `history.jsonl`.
- **TOML:** `lane.toml` uses a small TOML subset, `key = <JSON value>` and `[table]`. AgentDeck reads and writes it itself, so no dependency is needed.
- **Pure builders** produce the text:
  - the brief;
  - the update ("delta");
  - the chat summary;
  - the list of lane moves.
- **Adding the brief or update to a prompt:**
  - The session manager gains an optional `decorate` hook.
  - The hook appends the brief or update to the prompt the provider receives. The user's message is shown unchanged.
  - It records what the chat has now seen on `SessionRecord.laneSeen`.
- **Writing the summary:** after each turn, AgentDeck refreshes the tracker, links the chat to a lane (plan 18), and writes the chat's summary. The summary is built mechanically from the title, the files edited, and the last reply, with no model call.
- **History:** lane moves that the tracker observes are appended to `history.jsonl`.
- **Stamps:** each summary carries a stamp: `<!-- 2026-10-29T15:41:00.000Z · claude:1a2b3c4d · api@3f2c1a0 ui@91be04c -->`.
- **The only new UI:** *Set Lane Goal…* and *Open Lane Plan* on a lane in the Sessions list.

**Tech Stack:** as before.

---

## File structure

| File | Responsibility |
|---|---|
| `src/lanes/state.ts`, `src/lanes/lanes.ts` | Checkouts and lane repos carry their HEAD commit; `laneMoves` |
| `src/lanes/toml.ts` | The TOML subset |
| `src/lanes/memory.ts` | `.agentdeck/` files; stamps |
| `src/lanes/brief.ts` | Brief, delta, what a chat has seen |
| `src/lanes/summary.ts` | A chat's summary text |
| `src/lanes/lane-context.ts` | The `decorate` hook: brief or delta per prompt |
| `src/lanes/auto-link.ts`, `src/lanes/lane-turns.ts` | After each turn: link, then summarize; history of moves |
| `src/sessions/store.ts`, `src/sessions/manager.ts` | `laneSeen`; `decorate`; `lastReply`; `setLane` clears `laneSeen` |
| `src/ui/sessions-tree.ts`, `src/extension.ts`, `package.json` | Wiring; *Set Lane Goal…*, *Open Lane Plan* |
| `scripts/smoke-lanes.ts`, `esbuild.mjs` | Live check: a real agent reads its brief |

---

### Task 1: HEAD commits, TOML, and lane memory

**Files:**
- Modify: `src/lanes/state.ts`, `src/lanes/lanes.ts`, `test/lanes/state.test.ts`
- Create: `src/lanes/toml.ts`, `src/lanes/memory.ts`
- Test: `test/lanes/memory.test.ts`

- [ ] **Step 1: Update the state tests**

In `test/lanes/state.test.ts`:
- in *reads the main checkout first…*, change the expected entries to include each HEAD:

```ts
    expect(parseWorktrees(text)).toEqual([
      { path: '/w/api', main: true, head: 'aaa', branch: 'retry-fix' },
      { path: '/w/api/.worktrees/auth', main: false, head: 'bbb', branch: 'feat/auth' },
      { path: '/w/api/.worktrees/old', main: false, head: 'ccc' }
    ])
```

- in *reads checkouts, the base branch, and uncommitted files*, add `head: expect.stringMatching(/^[0-9a-f]{40}$/),` to both expected checkouts.

Run: `pnpm test test/lanes/state.test.ts` → FAIL (no `head`).

- [ ] **Step 2: HEAD in state and lanes**

In `src/lanes/state.ts`:
- change `Checkout` to `export type Checkout = { path: string; main: boolean; head?: string; branch?: string; dirty: number }`;
- in `parseWorktrees`, after the `branch` line add `const head = lines.find((line) => line.startsWith('HEAD '))?.slice('HEAD '.length)` and return `[{ path, main: index === 0, ...(head ? { head } : {}), ...(branch ? { branch } : {}) }]`.

In `src/lanes/lanes.ts`:
- change `LaneRepo` to `export type LaneRepo = { repo: string; location: 'main' | 'worktree'; path: string; dirty: number; head?: string }`;
- in `deriveLanes`, add `...(checkout.head ? { head: checkout.head } : {})` to the pushed object (after `dirty`).

Run: `pnpm test test/lanes` → PASS (the lanes fixtures carry no `head`, so their expectations are unchanged).

- [ ] **Step 3: Write the failing memory tests**

`test/lanes/memory.test.ts`:

```ts
import { existsSync, readFileSync, utimesSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { LaneMemory, stamp } from '../../src/lanes/memory'
import { parseToml, stringifyToml } from '../../src/lanes/toml'
import { repo, workspace } from './repos'

describe('toml subset', () => {
  it('round-trips keys, strings, numbers, arrays, and tables', () => {
    const data = { name: 'retry-fix', goal: 'Fix "retry"\nfor real', count: 2, files: ['.env', '.env.local'], setup: { command: 'pnpm install' } }
    expect(parseToml(stringifyToml(data))).toEqual(data)
  })

  it('skips comments and lines outside the subset', () => {
    expect(parseToml('# note\nname = "x"\nweird = bare words\n[t]\nk = true\n')).toEqual({ name: 'x', t: { k: true } })
  })
})

describe('LaneMemory', () => {
  it('creates a lane folder with lane.toml, plan.md, notes.md, and chats/', () => {
    const root = workspace()
    const memory = new LaneMemory(root)
    expect(memory.exists('feat/retry')).toBe(false)
    memory.ensure('feat/retry')
    const dir = join(root, '.agentdeck', 'lanes', 'feat--retry')
    expect(memory.laneDir('feat/retry')).toBe(dir)
    expect(parseToml(readFileSync(join(dir, 'lane.toml'), 'utf8'))).toMatchObject({ name: 'feat/retry' })
    expect(existsSync(join(dir, 'plan.md'))).toBe(true)
    expect(existsSync(join(dir, 'notes.md'))).toBe(true)
    expect(existsSync(join(dir, 'chats'))).toBe(true)
  })

  it('stores the goal', () => {
    const memory = new LaneMemory(workspace())
    expect(memory.goal('x')).toBeUndefined()
    memory.setGoal('x', 'Make retry reliable')
    expect(memory.goal('x')).toBe('Make retry reliable')
  })

  it('reports when the plan changed and how many notes there are', () => {
    const memory = new LaneMemory(workspace())
    memory.ensure('x')
    expect(memory.planUpdated('x')).toBeUndefined()
    writeFileSync(memory.planPath('x'), '1. do it\n')
    const when = new Date('2026-10-29T10:00:00Z')
    utimesSync(memory.planPath('x'), when, when)
    expect(memory.planUpdated('x')).toBe('2026-10-29T10:00:00.000Z')
    writeFileSync(memory.notesPath('x'), '# Notes\n- one\n- two\nnot a note\n')
    expect(memory.noteCount('x')).toBe(2)
  })

  it('lists chat summaries newest first with their titles', () => {
    const memory = new LaneMemory(workspace())
    memory.writeSummary('x', 'a', '<!-- s -->\n# Research · grok\nbody\n')
    memory.writeSummary('x', 'b', '<!-- s -->\n# Plan · claude\nbody\n')
    utimesSync(join(memory.laneDir('x'), 'chats', 'a.md'), new Date(1000), new Date(1000))
    expect(memory.summaries('x').map(({ chatId, title }) => ({ chatId, title }))).toEqual([
      { chatId: 'b', title: 'Plan · claude' },
      { chatId: 'a', title: 'Research · grok' }
    ])
  })

  it('appends history only for lanes it already holds', () => {
    const memory = new LaneMemory(workspace())
    memory.appendHistory('x', { event: 'moved' })
    expect(memory.exists('x')).toBe(false)
    memory.ensure('x')
    memory.appendHistory('x', { event: 'moved', repo: 'api' })
    const lines = readFileSync(join(memory.laneDir('x'), 'history.jsonl'), 'utf8').trim().split('\n')
    expect(JSON.parse(lines[0])).toMatchObject({ event: 'moved', repo: 'api', at: expect.any(String) })
  })

  it('keeps .agentdeck out of a single-repo workspace, once', () => {
    const root = repo(workspace())
    const memory = new LaneMemory(root)
    memory.ensure('x')
    memory.ensure('y')
    const exclude = readFileSync(join(root, '.git', 'info', 'exclude'), 'utf8')
    expect(exclude.split('\n').filter((line) => line === '.agentdeck/')).toHaveLength(1)
  })

  it('stamps with time, author, and short commits', () => {
    expect(stamp('claude:1a2b', [{ repo: 'api', head: '3f2c1a0aaaa' }, { repo: 'ui' }], new Date('2026-10-29T15:41:00Z'))).toBe(
      '<!-- 2026-10-29T15:41:00.000Z · claude:1a2b · api@3f2c1a0 -->'
    )
  })
})
```

Run: `pnpm test test/lanes/memory.test.ts` → FAIL.

- [ ] **Step 4: Implement**

`src/lanes/toml.ts`:

```ts
/**
 * The TOML subset AgentDeck writes: `[table]` headers and `key = value` lines whose value is JSON
 * (strings, numbers, booleans, arrays). JSON values are valid TOML; lines outside the subset are skipped.
 */
export function parseToml(text: string): Record<string, unknown> {
  const root: Record<string, unknown> = {}
  let table = root
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const header = /^\[([A-Za-z0-9_.-]+)\]$/.exec(line)
    if (header) {
      table = {}
      root[header[1]] = table
      continue
    }
    const pair = /^([A-Za-z0-9_-]+)\s*=\s*(.+)$/.exec(line)
    if (!pair) continue
    try {
      table[pair[1]] = JSON.parse(pair[2])
    } catch {
      // Not in the subset.
    }
  }
  return root
}

const isTable = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

export function stringifyToml(data: Record<string, unknown>): string {
  const line = ([key, value]: [string, unknown]) => `${key} = ${JSON.stringify(value)}`
  const entries = Object.entries(data)
  const lines = entries.filter(([, value]) => !isTable(value)).map(line)
  for (const [name, table] of entries) {
    if (isTable(table)) lines.push('', `[${name}]`, ...Object.entries(table).map(line))
  }
  return `${lines.join('\n')}\n`
}
```

`src/lanes/memory.ts`:

```ts
import { appendFileSync, existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { parseToml, stringifyToml } from './toml'

export type ChatSummaryRef = { chatId: string; title: string; path: string; updated: string }

/** `.agentdeck/` at the workspace root: what each lane is for and what its chats found. It never describes Git. */
export class LaneMemory {
  readonly dir: string

  constructor(private readonly root: string) {
    this.dir = join(root, '.agentdeck')
  }

  laneDir(lane: string): string {
    return join(this.dir, 'lanes', lane.replaceAll('/', '--'))
  }

  planPath(lane: string): string {
    return join(this.laneDir(lane), 'plan.md')
  }

  notesPath(lane: string): string {
    return join(this.laneDir(lane), 'notes.md')
  }

  exists(lane: string): boolean {
    return existsSync(this.laneDir(lane))
  }

  ensure(lane: string): void {
    const dir = this.laneDir(lane)
    mkdirSync(join(dir, 'chats'), { recursive: true })
    const toml = join(dir, 'lane.toml')
    if (!existsSync(toml)) writeFileSync(toml, stringifyToml({ name: lane, created: new Date().toISOString() }))
    for (const file of [this.planPath(lane), this.notesPath(lane)]) if (!existsSync(file)) writeFileSync(file, '')
    this.exclude()
  }

  goal(lane: string): string | undefined {
    const goal = this.lane(lane).goal
    return typeof goal === 'string' && goal.trim() ? goal.trim() : undefined
  }

  setGoal(lane: string, goal: string): void {
    this.ensure(lane)
    writeFileSync(join(this.laneDir(lane), 'lane.toml'), stringifyToml({ ...this.lane(lane), goal }))
  }

  /** When plan.md last changed, or undefined while it is empty. */
  planUpdated(lane: string): string | undefined {
    const path = this.planPath(lane)
    if (!existsSync(path)) return undefined
    const stats = statSync(path)
    return stats.size > 0 ? stats.mtime.toISOString() : undefined
  }

  noteCount(lane: string): number {
    const path = this.notesPath(lane)
    if (!existsSync(path)) return 0
    return readFileSync(path, 'utf8')
      .split('\n')
      .filter((line) => line.startsWith('- ')).length
  }

  /** Chat summaries, newest first. */
  summaries(lane: string): ChatSummaryRef[] {
    const dir = join(this.laneDir(lane), 'chats')
    if (!existsSync(dir)) return []
    return readdirSync(dir)
      .filter((file) => file.endsWith('.md'))
      .map((file) => {
        const path = join(dir, file)
        const heading = readFileSync(path, 'utf8')
          .split('\n')
          .find((line) => line.startsWith('# '))
        return {
          chatId: file.slice(0, -'.md'.length),
          title: heading?.slice(2).trim() ?? file,
          path,
          updated: statSync(path).mtime.toISOString()
        }
      })
      .sort((a, b) => b.updated.localeCompare(a.updated))
  }

  writeSummary(lane: string, chatId: string, text: string): void {
    this.ensure(lane)
    writeFileSync(join(this.laneDir(lane), 'chats', `${chatId}.md`), text)
  }

  /** Records an observed event; lanes AgentDeck holds no memory for are not given a folder just for this. */
  appendHistory(lane: string, event: Record<string, unknown>): void {
    if (!this.exists(lane)) return
    appendFileSync(join(this.laneDir(lane), 'history.jsonl'), `${JSON.stringify({ at: new Date().toISOString(), ...event })}\n`)
  }

  private lane(lane: string): Record<string, unknown> {
    const path = join(this.laneDir(lane), 'lane.toml')
    return existsSync(path) ? parseToml(readFileSync(path, 'utf8')) : {}
  }

  /** In a single-repo workspace the root is the repo, so `.agentdeck/` is excluded locally (never in a committed .gitignore). */
  private exclude(): void {
    const gitDir = join(this.root, '.git')
    if (!existsSync(gitDir) || !statSync(gitDir).isDirectory()) return
    const file = join(gitDir, 'info', 'exclude')
    const current = existsSync(file) ? readFileSync(file, 'utf8') : ''
    if (current.split('\n').includes('.agentdeck/')) return
    mkdirSync(join(gitDir, 'info'), { recursive: true })
    appendFileSync(file, `${current && !current.endsWith('\n') ? '\n' : ''}.agentdeck/\n`)
  }
}

/** `<!-- when · by · repo@commit … -->`, so a reader can tell how far each repo moved since. */
export function stamp(by: string, heads: { repo: string; head?: string }[], at = new Date()): string {
  const commits = heads.flatMap(({ repo, head }) => (head ? [`${repo}@${head.slice(0, 7)}`] : []))
  return `<!-- ${[at.toISOString(), by, ...(commits.length > 0 ? [commits.join(' ')] : [])].join(' · ')} -->`
}
```

Run: `pnpm test test/lanes` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lanes test/lanes
git commit -m "feat(lanes): lane memory in .agentdeck with stamps and HEAD commits"
```

---

### Task 2: Brief, delta, summary, and moves

**Files:**
- Modify: `src/sessions/store.ts`, `src/lanes/lanes.ts`
- Create: `src/lanes/brief.ts`, `src/lanes/summary.ts`
- Test: `test/lanes/brief.test.ts`

- [ ] **Step 1: The seen-state type**

In `src/sessions/store.ts`, add above `SessionRecord`:

```ts
/** Where a chat's lane was (path and HEAD per repo) when the chat last received its lane brief or update. */
export type LaneSeen = { lane: string; at: string; repos: Record<string, { path: string; head?: string }> }
```

and add to `SessionRecord` after `laneId`:

```ts
  laneSeen?: LaneSeen
```

- [ ] **Step 2: Write the failing tests**

`test/lanes/brief.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { buildBrief, buildDelta, seenOf } from '../../src/lanes/brief'
import { type Lane, laneMoves } from '../../src/lanes/lanes'
import { chatSummary } from '../../src/lanes/summary'

const lane: Lane = {
  name: 'retry-fix',
  repos: [
    { repo: 'api', location: 'main', path: '/w/api', dirty: 2, head: 'aaaaaaa111' },
    { repo: 'ui', location: 'worktree', path: '/w/ui/.worktrees/retry-fix', dirty: 0, head: 'bbbbbbb222' }
  ]
}

describe('buildBrief', () => {
  it('points at the code, plan, notes, and earlier chats', () => {
    expect(
      buildBrief({
        root: '/w',
        lane,
        goal: 'Make retry reliable',
        plan: { path: '/w/.agentdeck/lanes/retry-fix/plan.md', updated: '2026-10-29T10:00:00.000Z' },
        notes: { path: '/w/.agentdeck/lanes/retry-fix/notes.md', entries: 1 },
        earlier: [{ title: 'Research · grok', path: '/w/.agentdeck/lanes/retry-fix/chats/a.md' }]
      })
    ).toBe(
      [
        '<lane name="retry-fix">',
        'Goal: Make retry reliable',
        'Code: api/ (main checkout, 2 uncommitted) · ui/.worktrees/retry-fix (worktree, clean)',
        'Plan: .agentdeck/lanes/retry-fix/plan.md (updated 2026-10-29T10:00:00.000Z)',
        'Notes: .agentdeck/lanes/retry-fix/notes.md (1 entry)',
        'Earlier chats: Research · grok (.agentdeck/lanes/retry-fix/chats/a.md)',
        'Rules: edit only inside the code paths above. Do not switch branches in main checkouts. Keep plan.md current as steps finish; add decisions and findings to notes.md as "- " bullets.',
        '</lane>'
      ].join('\n')
    )
  })

  it('says when there is no goal, plan, or checkout yet', () => {
    const brief = buildBrief({
      root: '/w',
      lane: { name: 'new', repos: [] },
      plan: { path: '/w/.agentdeck/lanes/new/plan.md' },
      notes: { path: '/w/.agentdeck/lanes/new/notes.md', entries: 0 },
      earlier: []
    })
    expect(brief).toContain('Goal: not set')
    expect(brief).toContain('Code: no checkout yet (branch new)')
    expect(brief).toContain('plan.md (empty)')
    expect(brief).toContain('(0 entries)')
    expect(brief).not.toContain('Earlier chats')
  })
})

describe('buildDelta', () => {
  const seen = seenOf(lane, new Date('2026-10-29T12:00:00Z'))

  it('is empty when nothing changed', () => {
    expect(buildDelta('/w', lane, seen)).toBeUndefined()
  })

  it('reports moves, new commits, joins, leaves, and plan edits', () => {
    const now: Lane = {
      name: 'retry-fix',
      repos: [
        { repo: 'api', location: 'worktree', path: '/w/api/.worktrees/retry-fix', dirty: 2, head: 'aaaaaaa111' },
        { repo: 'db', location: 'worktree', path: '/w/db/.worktrees/retry-fix', dirty: 0 }
      ]
    }
    const withUi = { ...seen, repos: { ...seen.repos } }
    expect(buildDelta('/w', now, withUi, '2026-10-29T13:00:00.000Z')).toBe(
      [
        '<lane-update name="retry-fix">',
        'Since your last turn:',
        '- api: moved from api to api/.worktrees/retry-fix; work there now.',
        '- ui: left the lane (no checkout now).',
        '- db: joined the lane at db/.worktrees/retry-fix.',
        '- plan.md changed.',
        '</lane-update>'
      ].join('\n')
    )
    const committed: Lane = { ...lane, repos: [{ ...lane.repos[0], head: 'ccccccc333' }, lane.repos[1]] }
    expect(buildDelta('/w', committed, seen)).toContain('- api: new commits (aaaaaaa → ccccccc).')
  })
})

describe('laneMoves', () => {
  it('lists checkouts that appeared, moved, or went away', () => {
    const after: Lane[] = [
      { name: 'retry-fix', repos: [{ repo: 'api', location: 'worktree', path: '/w/api/.worktrees/retry-fix', dirty: 0 }] },
      { name: 'auth', repos: [{ repo: 'api', location: 'main', path: '/w/api', dirty: 0 }] }
    ]
    expect(laneMoves([lane], after)).toEqual([
      { lane: 'retry-fix', repo: 'api', from: '/w/api', to: '/w/api/.worktrees/retry-fix' },
      { lane: 'retry-fix', repo: 'ui', from: '/w/ui/.worktrees/retry-fix' },
      { lane: 'auth', repo: 'api', to: '/w/api' }
    ])
  })
})

describe('chatSummary', () => {
  it('lists files relative to the root and a trimmed last reply', () => {
    expect(
      chatSummary({
        stamp: '<!-- s -->',
        title: 'Fix the retry backoff',
        provider: 'codex',
        root: '/w',
        files: ['/w/api/retry.ts', '/w/api/retry.ts', '/w/ui/a.ts'],
        reply: `Done.\n\n${'x'.repeat(500)}`
      })
    ).toBe(`<!-- s -->\n# Fix the retry backoff · codex\nFiles: api/retry.ts, ui/a.ts\nLast reply: Done. ${'x'.repeat(394)}…\n`)
  })
})
```

Run: `pnpm test test/lanes/brief.test.ts` → FAIL.

- [ ] **Step 3: Implement**

`src/lanes/brief.ts`:

```ts
import { relative } from 'node:path'
import type { LaneSeen } from '../sessions/store'
import type { Lane, LaneRepo } from './lanes'

const MAX_EARLIER = 5

const RULES =
  'Rules: edit only inside the code paths above. Do not switch branches in main checkouts. Keep plan.md current as steps finish; add decisions and findings to notes.md as "- " bullets.'

export type BriefInput = {
  root: string
  lane: Lane
  goal?: string
  plan: { path: string; updated?: string }
  notes: { path: string; entries: number }
  earlier: { title: string; path: string }[]
}

function where(root: string, repo: LaneRepo): string {
  const path = relative(root, repo.path) || '.'
  const state = repo.dirty > 0 ? `${repo.dirty} uncommitted` : 'clean'
  return repo.location === 'main' ? `${path}/ (main checkout, ${state})` : `${path} (worktree, ${state})`
}

/** The first-turn brief: pointers, not content; the agent reads what it needs. */
export function buildBrief(input: BriefInput): string {
  const rel = (path: string) => relative(input.root, path)
  const code =
    input.lane.repos.length > 0
      ? input.lane.repos.map((repo) => where(input.root, repo)).join(' · ')
      : `no checkout yet (branch ${input.lane.name})`
  const earlier = input.earlier.slice(0, MAX_EARLIER).map((chat) => `${chat.title} (${rel(chat.path)})`)
  return [
    `<lane name="${input.lane.name}">`,
    `Goal: ${input.goal ?? 'not set'}`,
    `Code: ${code}`,
    `Plan: ${rel(input.plan.path)} (${input.plan.updated ? `updated ${input.plan.updated}` : 'empty'})`,
    `Notes: ${rel(input.notes.path)} (${input.notes.entries} ${input.notes.entries === 1 ? 'entry' : 'entries'})`,
    ...(earlier.length > 0 ? [`Earlier chats: ${earlier.join('; ')}`] : []),
    RULES,
    '</lane>'
  ].join('\n')
}

export function seenOf(lane: Lane, at = new Date()): LaneSeen {
  return {
    lane: lane.name,
    at: at.toISOString(),
    repos: Object.fromEntries(lane.repos.map((repo) => [repo.repo, { path: repo.path, ...(repo.head ? { head: repo.head } : {}) }]))
  }
}

/** What changed for this lane since the chat last looked, or undefined when nothing did. */
export function buildDelta(root: string, lane: Lane, seen: LaneSeen, planUpdated?: string): string | undefined {
  const rel = (path: string) => relative(root, path) || '.'
  const now = new Map(lane.repos.map((repo) => [repo.repo, repo]))
  const lines: string[] = []
  for (const [repo, before] of Object.entries(seen.repos)) {
    const after = now.get(repo)
    if (!after) lines.push(`- ${repo}: left the lane (no checkout now).`)
    else if (after.path !== before.path) lines.push(`- ${repo}: moved from ${rel(before.path)} to ${rel(after.path)}; work there now.`)
    else if (before.head && after.head && before.head !== after.head) {
      lines.push(`- ${repo}: new commits (${before.head.slice(0, 7)} → ${after.head.slice(0, 7)}).`)
    }
  }
  for (const repo of lane.repos) if (!(repo.repo in seen.repos)) lines.push(`- ${repo.repo}: joined the lane at ${rel(repo.path)}.`)
  if (planUpdated && planUpdated > seen.at) lines.push('- plan.md changed.')
  if (lines.length === 0) return undefined
  return [`<lane-update name="${lane.name}">`, 'Since your last turn:', ...lines, '</lane-update>'].join('\n')
}
```

`src/lanes/summary.ts`:

```ts
import { relative } from 'node:path'

const MAX_FILES = 10
const MAX_REPLY = 400

export type SummaryInput = { stamp: string; title: string; provider: string; root: string; files: string[]; reply?: string }

/** A chat's summary, built from what AgentDeck already knows: no model call. */
export function chatSummary(input: SummaryInput): string {
  const files = [...new Set(input.files.map((file) => relative(input.root, file)))]
  const lines = [input.stamp, `# ${input.title} · ${input.provider}`]
  if (files.length > 0) {
    const more = files.length > MAX_FILES ? ` (+${files.length - MAX_FILES} more)` : ''
    lines.push(`Files: ${files.slice(0, MAX_FILES).join(', ')}${more}`)
  }
  const reply = input.reply?.replace(/\s+/g, ' ').trim()
  if (reply) lines.push(`Last reply: ${reply.length > MAX_REPLY ? `${reply.slice(0, MAX_REPLY)}…` : reply}`)
  return `${lines.join('\n')}\n`
}
```

In `src/lanes/lanes.ts`, add at the end:

```ts
export type LaneMove = { lane: string; repo: string; from?: string; to?: string }

/** Lane checkouts that appeared, moved, or went away between two readings. */
export function laneMoves(before: Lane[], after: Lane[]): LaneMove[] {
  const paths = (lanes: Lane[]) =>
    new Map(lanes.flatMap((lane) => lane.repos.map((repo) => [`${lane.name}\u0000${repo.repo}`, repo.path] as const)))
  const was = paths(before)
  const is = paths(after)
  const moves: LaneMove[] = []
  for (const key of new Set([...was.keys(), ...is.keys()])) {
    const from = was.get(key)
    const to = is.get(key)
    if (from === to) continue
    const [lane, repo] = key.split('\u0000')
    moves.push({ lane, repo, ...(from ? { from } : {}), ...(to ? { to } : {}) })
  }
  return moves
}
```

Run: `pnpm test test/lanes` → PASS.

- [ ] **Step 4: Commit**

```bash
git add src/sessions/store.ts src/lanes test/lanes/brief.test.ts
git commit -m "feat(lanes): lane brief, lane update, chat summary, and lane moves"
```

---

### Task 3: Briefs reach the agent

**Files:**
- Modify: `src/sessions/manager.ts`, `test/sessions/manager.test.ts`
- Create: `src/lanes/lane-context.ts`
- Test: `test/lanes/lane-context.test.ts`

- [ ] **Step 1: Write the failing tests**

Add inside the `describe` block of `test/sessions/manager.test.ts`:

```ts
  it('lets a decorator add to what the provider receives while the transcript keeps what the user wrote', async () => {
    const { provider, sessions } = fakeProvider()
    const manager = new SessionManager({
      providers: new Map([[provider.id, provider]]),
      store: new SessionStore(new MemoryMemento()),
      journalDir: mkdtempSync(join(tmpdir(), 'agentdeck-manager-')),
      cwd: '/work',
      env: async () => ({ PATH: '/bin' }),
      decorate: async (record, parts) => {
        record.laneSeen = { lane: 'x', at: 'now', repos: {} }
        return [...parts, { type: 'text', text: '<lane name="x" />' }]
      }
    })
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    await manager.prompt(id, text('hello'))
    expect(sessions[0].prompts[0]).toEqual([...text('hello'), { type: 'text', text: '<lane name="x" />' }])
    expect(events.find((event) => event.type === 'item' && event.item.kind === 'message')).toMatchObject({
      item: { role: 'user', parts: text('hello') }
    })
    expect(manager.list()[0].record.laneSeen).toEqual({ lane: 'x', at: 'now', repos: {} })
  })

  it('knows the last reply and forgets what a chat saw when it changes lane', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('hi'))
    sessions[0].emit({ kind: 'message', id: 'm1', role: 'assistant', text: 'first', streaming: false })
    sessions[0].emit({ kind: 'message', id: 'm2', role: 'assistant', text: 'second', streaming: false })
    expect(manager.lastReply(id)).toBe('second')
    await manager.setLane(id, 'a')
    const record = manager.list()[0].record
    record.laneSeen = { lane: 'a', at: 'now', repos: {} }
    await manager.setLane(id, 'b')
    expect(manager.list()[0].record.laneSeen).toBeUndefined()
  })
```

`test/lanes/lane-context.test.ts`:

```ts
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import type { PromptPart } from '../../src/core/types'
import { laneContext } from '../../src/lanes/lane-context'
import { LaneMemory } from '../../src/lanes/memory'
import { LaneTracker } from '../../src/lanes/tracker'
import type { SessionRecord } from '../../src/sessions/store'
import { repo, run, workspace } from './repos'

const parts: PromptPart[] = [{ type: 'text', text: 'go' }]
let tracker: LaneTracker | undefined
afterEach(() => tracker?.dispose())

function record(laneId?: string): SessionRecord {
  return {
    id: 'chat-1',
    providerId: 'fake',
    title: 't',
    createdAt: '',
    updatedAt: '',
    mode: 'ask',
    hasTurns: false,
    facts: {},
    ...(laneId ? { laneId } : {})
  }
}

describe('laneContext', () => {
  it('sends the brief first, nothing when unchanged, then an update after a commit', async () => {
    const root = workspace()
    const api = repo(join(root, 'api'))
    run(api, 'checkout', '-q', '-b', 'retry-fix')
    tracker = new LaneTracker(root)
    const memory = new LaneMemory(tracker.root)
    memory.setGoal('retry-fix', 'Make retry reliable')
    const decorate = laneContext(tracker, memory)
    const chat = record('retry-fix')

    const first = await decorate(chat, parts)
    expect(first).toHaveLength(2)
    expect(first[1]).toMatchObject({ type: 'text', text: expect.stringContaining('Goal: Make retry reliable') })
    expect(chat.laneSeen?.lane).toBe('retry-fix')

    expect(await decorate(chat, parts)).toEqual(parts)

    writeFileSync(join(api, 'b.txt'), 'b')
    run(api, 'add', '.')
    run(api, 'commit', '-q', '-m', 'b')
    const third = await decorate(chat, parts)
    expect(third[1]).toMatchObject({ text: expect.stringContaining('- api: new commits') })
  })

  it('leaves prompts of chats on no lane alone', async () => {
    tracker = new LaneTracker(workspace())
    expect(await laneContext(tracker, new LaneMemory(tracker.root))(record(), parts)).toEqual(parts)
  })
})
```

Run: `pnpm test test/sessions test/lanes/lane-context.test.ts` → FAIL.

- [ ] **Step 2: Manager**

In `src/sessions/manager.ts`:
- add to `SessionManagerDeps`:

```ts
  /** Adds context to what the provider receives (the transcript keeps what the user wrote). May update the record, which is saved after. */
  decorate?: (record: SessionRecord, parts: PromptPart[]) => Promise<PromptPart[]>
```

- in `send`, replace

```ts
      const session = await this.connect(live)
      live.record.hasTurns = true
      await this.save(live)
      await session.prompt(parts)
```

  with

```ts
      const session = await this.connect(live)
      const sent = this.deps.decorate ? await this.deps.decorate(live.record, parts).catch(() => parts) : parts
      live.record.hasTurns = true
      await this.save(live)
      await session.prompt(sent)
```

- in `setLane`, after the `if/else` add `delete live.record.laneSeen`;
- after `diffPaths`, add:

```ts
  lastReply(id: string): string | undefined {
    const replies = [...this.load(id).items.values()].flatMap((item) =>
      item.kind === 'message' && item.role === 'assistant' ? [item.text] : []
    )
    return replies.at(-1)
  }
```

- [ ] **Step 3: The decorator**

`src/lanes/lane-context.ts`:

```ts
import type { PromptPart } from '../core/types'
import type { SessionRecord } from '../sessions/store'
import { buildBrief, buildDelta, seenOf } from './brief'
import { deriveLanes } from './lanes'
import type { LaneMemory } from './memory'
import type { LaneTracker } from './tracker'

/**
 * The session manager's `decorate` hook: a chat's first prompt on its lane carries the lane brief; later prompts carry
 * a lane update when something changed. What the chat has now seen is kept on `record.laneSeen`.
 */
export function laneContext(tracker: LaneTracker, memory: LaneMemory) {
  return async (record: SessionRecord, parts: PromptPart[]): Promise<PromptPart[]> => {
    const name = record.laneId
    if (!name) return parts
    await tracker.refresh()
    const lane = deriveLanes(tracker.repos, [name]).find((candidate) => candidate.name === name)
    if (!lane) return parts
    memory.ensure(name)
    const planUpdated = memory.planUpdated(name)
    const text =
      record.laneSeen?.lane === name
        ? buildDelta(tracker.root, lane, record.laneSeen, planUpdated)
        : buildBrief({
            root: tracker.root,
            lane,
            goal: memory.goal(name),
            plan: { path: memory.planPath(name), ...(planUpdated ? { updated: planUpdated } : {}) },
            notes: { path: memory.notesPath(name), entries: memory.noteCount(name) },
            earlier: memory.summaries(name).filter((summary) => summary.chatId !== record.id)
          })
    record.laneSeen = seenOf(lane)
    return text ? [...parts, { type: 'text', text }] : parts
  }
}
```

Run: `pnpm test` → PASS.

- [ ] **Step 4: Commit**

```bash
git add src/sessions/manager.ts src/lanes/lane-context.ts test/sessions/manager.test.ts test/lanes/lane-context.test.ts
git commit -m "feat(lanes): chats on a lane receive the lane brief and later updates"
```

---

### Task 4: Summaries and history

**Files:**
- Modify: `src/lanes/auto-link.ts` (full replacement)
- Create: `src/lanes/lane-turns.ts`
- Test: `test/lanes/lane-turns.test.ts`

- [ ] **Step 1: Write the failing tests**

`test/lanes/lane-turns.test.ts`:

```ts
import { existsSync, mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import type { PromptPart } from '../../src/core/types'
import { watchHistory, watchTurns } from '../../src/lanes/lane-turns'
import { LaneMemory } from '../../src/lanes/memory'
import { LaneTracker } from '../../src/lanes/tracker'
import { SessionManager } from '../../src/sessions/manager'
import { SessionStore } from '../../src/sessions/store'
import { fakeProvider } from '../fake-provider'
import { MemoryMemento } from '../memory-memento'
import { repo, run, workspace } from './repos'

const text = (value: string): PromptPart[] => [{ type: 'text', text: value }]
let tracker: LaneTracker | undefined
afterEach(() => tracker?.dispose())

function until(check: () => boolean): Promise<void> {
  return new Promise((resolve, reject) => {
    const started = Date.now()
    const tick = () => (check() ? resolve() : Date.now() - started > 5000 ? reject(new Error('timed out')) : setTimeout(tick, 20))
    tick()
  })
}

describe('watchTurns', () => {
  it('links the chat, then writes its summary into the lane', async () => {
    const root = workspace()
    const api = repo(join(root, 'api'))
    run(api, 'worktree', 'add', '-q', '-b', 'retry-fix', join(api, '.worktrees', 'retry-fix'))
    const { provider, sessions } = fakeProvider()
    const manager = new SessionManager({
      providers: new Map([[provider.id, provider]]),
      store: new SessionStore(new MemoryMemento()),
      journalDir: mkdtempSync(join(tmpdir(), 'agentdeck-turns-')),
      cwd: root,
      env: async () => ({ PATH: '/bin' })
    })
    tracker = new LaneTracker(root)
    await tracker.refresh()
    const memory = new LaneMemory(tracker.root)
    watchTurns(manager, tracker, memory)
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('Fix the retry'))
    sessions[0].emit({ kind: 'diff', id: 'd1', path: join(api, '.worktrees', 'retry-fix', 'retry.ts'), oldText: null, newText: 'x' })
    sessions[0].emit({ kind: 'message', id: 'm1', role: 'assistant', text: 'Fixed it.', streaming: false })
    sessions[0].emit({ kind: 'turn', id: 't1', state: 'ended' })
    const summary = join(memory.laneDir('retry-fix'), 'chats', `${id}.md`)
    await until(() => existsSync(summary))
    const body = readFileSync(summary, 'utf8')
    expect(body).toMatch(/^<!-- \d{4}-.* · fake:.* · api@[0-9a-f]{7} -->\n# Fix the retry · fake\n/)
    expect(body).toContain('Files: api/.worktrees/retry-fix/retry.ts')
    expect(body).toContain('Last reply: Fixed it.')
  })
})

describe('watchHistory', () => {
  it('records moves of lanes AgentDeck holds memory for, not the first reading', async () => {
    const root = workspace()
    const api = repo(join(root, 'api'))
    run(api, 'checkout', '-q', '-b', 'retry-fix')
    tracker = new LaneTracker(root)
    const memory = new LaneMemory(tracker.root)
    memory.ensure('retry-fix')
    watchHistory(tracker, memory)
    await tracker.refresh()
    const history = join(memory.laneDir('retry-fix'), 'history.jsonl')
    expect(existsSync(history)).toBe(false)
    run(api, 'checkout', '-q', 'main')
    await tracker.refresh()
    expect(JSON.parse(readFileSync(history, 'utf8').trim())).toMatchObject({ event: 'moved', repo: 'api', from: 'api' })
  })
})
```

Run: `pnpm test test/lanes/lane-turns.test.ts` → FAIL.

- [ ] **Step 2: Implement**

`src/lanes/auto-link.ts` (full replacement):

```ts
import { resolve } from 'node:path'
import type { Disposable } from '../core/emitter'
import type { SessionManager } from '../sessions/manager'
import { laneFromPaths } from './lanes'
import type { LaneTracker } from './tracker'

/** A chat on no lane joins the one lane its edits landed in. Agents may branch on their own; this keeps up. */
export async function linkChat(manager: SessionManager, tracker: LaneTracker, sessionId: string): Promise<void> {
  const record = manager.list().find((entry) => entry.record.id === sessionId)?.record
  if (!record || record.laneId) return
  const files = manager.diffPaths(sessionId).map((path) => resolve(tracker.root, path))
  const lane = laneFromPaths(tracker.repos, files)
  if (lane) await manager.setLane(sessionId, lane)
}

/** After each turn: refresh what Git shows, then link. */
export function autoLink(manager: SessionManager, tracker: LaneTracker): Disposable {
  return manager.onAttention(({ sessionId, reason }) => {
    if (reason !== 'turn-ended') return
    void tracker.refresh().then(() => linkChat(manager, tracker, sessionId))
  })
}
```

`src/lanes/lane-turns.ts`:

```ts
import { relative, resolve } from 'node:path'
import type { Disposable } from '../core/emitter'
import type { SessionManager } from '../sessions/manager'
import { linkChat } from './auto-link'
import { deriveLanes, type Lane, laneMoves } from './lanes'
import { type LaneMemory, stamp } from './memory'
import { chatSummary } from './summary'
import type { LaneTracker } from './tracker'

/** After each turn: refresh, link the chat to a lane if it has none, then write its summary into the lane. */
export function watchTurns(manager: SessionManager, tracker: LaneTracker, memory: LaneMemory): Disposable {
  return manager.onAttention(({ sessionId, reason }) => {
    if (reason !== 'turn-ended') return
    void (async () => {
      await tracker.refresh()
      await linkChat(manager, tracker, sessionId)
      const record = manager.list().find((entry) => entry.record.id === sessionId)?.record
      const laneId = record?.laneId
      if (!record || !laneId) return
      const lane = deriveLanes(tracker.repos, [laneId]).find((candidate) => candidate.name === laneId)
      memory.writeSummary(
        laneId,
        sessionId,
        chatSummary({
          stamp: stamp(`${record.providerId}:${sessionId.slice(0, 8)}`, lane?.repos ?? []),
          title: record.title,
          provider: record.providerId,
          root: tracker.root,
          files: manager.diffPaths(sessionId).map((path) => resolve(tracker.root, path)),
          reply: manager.lastReply(sessionId)
        })
      )
    })().catch(() => {})
  })
}

/** Appends observed lane moves to each lane's history. The first reading is a baseline, not a move. */
export function watchHistory(tracker: LaneTracker, memory: LaneMemory): Disposable {
  let before: Lane[] | undefined = tracker.repos.length > 0 ? deriveLanes(tracker.repos) : undefined
  return tracker.onDidChange(() => {
    const after = deriveLanes(tracker.repos)
    const rel = (path: string) => relative(tracker.root, path) || '.'
    for (const move of before ? laneMoves(before, after) : []) {
      memory.appendHistory(move.lane, {
        event: 'moved',
        repo: move.repo,
        ...(move.from ? { from: rel(move.from) } : {}),
        ...(move.to ? { to: rel(move.to) } : {})
      })
    }
    before = after
  })
}
```

Run: `pnpm test` → PASS.

- [ ] **Step 3: Commit**

```bash
git add src/lanes test/lanes/lane-turns.test.ts
git commit -m "feat(lanes): summarize chats into their lane and record lane moves"
```

---

### Task 5: Wiring

**Files:**
- Modify: `src/ui/sessions-tree.ts`, `src/extension.ts`, `package.json`

- [ ] **Step 1: Export the lane node**

In `src/ui/sessions-tree.ts`, change `type LaneNode = …` to `export type LaneNode = …`.

- [ ] **Step 2: Extension**

In `src/extension.ts`:
- replace `import { autoLink } from './lanes/auto-link'` with:

```ts
import { laneContext } from './lanes/lane-context'
import { watchHistory, watchTurns } from './lanes/lane-turns'
import { LaneMemory } from './lanes/memory'
```

  and import `type LaneNode` from `./ui/sessions-tree` alongside the existing imports;
- after `const tracker = root ? new LaneTracker(root) : undefined`, add `const memory = tracker ? new LaneMemory(tracker.root) : undefined`;
- add to the `SessionManager` deps: `decorate: tracker && memory ? laneContext(tracker, memory) : undefined,`;
- add to the main `push(…)` list:

```ts
    vscode.commands.registerCommand('agentdeck.setLaneGoal', async (node: LaneNode) => {
      if (!memory) return
      const goal = await vscode.window.showInputBox({ prompt: `Goal for ${node.lane.name}`, value: memory.goal(node.lane.name) ?? '' })
      if (goal?.trim()) memory.setGoal(node.lane.name, goal.trim())
    }),
    vscode.commands.registerCommand('agentdeck.openLanePlan', async (node: LaneNode) => {
      if (!memory) return
      memory.ensure(node.lane.name)
      await vscode.window.showTextDocument(vscode.Uri.file(memory.planPath(node.lane.name)))
    }),
```

- in the `if (tracker) { … }` block, replace `autoLink(sessionManager, tracker),` with:

```ts
      ...(memory ? [watchTurns(sessionManager, tracker, memory), watchHistory(tracker, memory)] : []),
```

  (`memory` is always set when `tracker` is; the spread keeps TypeScript satisfied without a non-null assertion).

In `package.json`, following how the existing entries are written:
- `contributes.commands`: `{ "command": "agentdeck.setLaneGoal", "title": "Set Lane Goal…", "category": "AgentDeck" }` and `{ "command": "agentdeck.openLanePlan", "title": "Open Lane Plan", "category": "AgentDeck" }`;
- `menus.view/item/context`: `{ "command": "agentdeck.openLanePlan", "when": "view == agentdeck.sessions && viewItem == lane", "group": "1_open@1" }` and `{ "command": "agentdeck.setLaneGoal", "when": "view == agentdeck.sessions && viewItem == lane", "group": "2_edit@1" }`;
- `menus.commandPalette`: both with `"when": "false"`.

- [ ] **Step 3: Verify and commit**

Run: `pnpm typecheck && pnpm test && pnpm build` → clean; PASS; built.

```bash
git add src/ui/sessions-tree.ts src/extension.ts package.json
git commit -m "feat(lanes): wire lane memory, briefs, summaries, and history into the extension"
```

---

### Task 6: Live check and hand-off

**Files:**
- Create: `scripts/smoke-lanes.ts`
- Modify: `esbuild.mjs`

- [ ] **Step 1: The script**

`scripts/smoke-lanes.ts`:

```ts
// Live check: a real agent on a lane receives its brief and can say the lane's goal; its summary lands in the lane.
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { captureEnv } from '../src/env'
import { laneContext } from '../src/lanes/lane-context'
import { watchTurns } from '../src/lanes/lane-turns'
import { LaneMemory } from '../src/lanes/memory'
import { LaneTracker } from '../src/lanes/tracker'
import { providers } from '../src/providers/registry'
import { SessionManager } from '../src/sessions/manager'
import { SessionStore } from '../src/sessions/store'
import { MemoryMemento } from '../test/memory-memento'

const TIMEOUT_MS = 180_000
const GOAL = 'Teach the parser to accept trailing commas'

const git = (cwd: string, ...args: string[]) => execFileSync('git', args, { cwd, stdio: 'ignore' })

async function main(): Promise<void> {
  const providerId = process.argv[2] ?? 'claude'
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'agentdeck-lanes-smoke-')))
  const api = join(root, 'api')
  mkdirSync(api)
  git(api, 'init', '-q', '-b', 'main')
  git(api, 'config', 'user.email', 'smoke@example.com')
  git(api, 'config', 'user.name', 'Smoke')
  writeFileSync(join(api, 'parser.ts'), 'export const parse = (s: string) => JSON.parse(s)\n')
  git(api, 'add', '.')
  git(api, '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'init')
  git(api, 'checkout', '-q', '-b', 'trailing-commas')

  const tracker = new LaneTracker(root)
  const memory = new LaneMemory(tracker.root)
  memory.setGoal('trailing-commas', GOAL)
  const env = await captureEnv()
  const manager = new SessionManager({
    providers,
    store: new SessionStore(new MemoryMemento()),
    journalDir: join(root, '.journal'),
    cwd: root,
    env: async () => env,
    decorate: laneContext(tracker, memory)
  })
  watchTurns(manager, tracker, memory)
  const { id } = await manager.create(providerId)
  await manager.setLane(id, 'trailing-commas')

  const reply = await new Promise<string>((resolve, reject) => {
    const replies = new Map<string, string>()
    const timer = setTimeout(() => reject(new Error('turn timed out')), TIMEOUT_MS)
    const subscription = manager.subscribe(id, (event) => {
      if (event.type !== 'item') return
      const item = event.item
      if (item.kind === 'message' && item.role === 'assistant') replies.set(item.id, item.text)
      if (item.kind === 'approval' && item.resolved === undefined) manager.answer(id, item.id, { kind: 'option', optionId: 'deny' })
      if (item.kind === 'turn' && item.state === 'ended') {
        clearTimeout(timer)
        subscription.dispose()
        resolve([...replies.values()].join('\n'))
      }
    })
    void manager.prompt(id, [{ type: 'text', text: 'Without using any tools: what is the goal of the lane you are on, and which folder holds its code? One line.' }])
  })
  console.log('reply:', reply.replaceAll('\n', ' ').slice(0, 200))
  if (!/trailing comma/i.test(reply)) throw new Error('the agent did not see the lane goal')
  const summary = join(memory.laneDir('trailing-commas'), 'chats', `${id}.md`)
  const started = Date.now()
  while (!existsSync(summary) && Date.now() - started < 5000) await new Promise((resolve) => setTimeout(resolve, 100))
  if (!existsSync(summary)) throw new Error('no chat summary written')
  console.log('summary:', readFileSync(summary, 'utf8').split('\n').slice(0, 2).join(' | '))
  await manager.dispose()
  tracker.dispose()
  console.log('LANES SMOKE OK')
}

main().catch((error) => {
  console.error('LANES SMOKE FAILED:', error)
  process.exit(1)
})
```

In `esbuild.mjs`, add `'smoke-lanes': 'scripts/smoke-lanes.ts'` to the extension build's `entryPoints`.

- [ ] **Step 2: Run it**

Run: `pnpm typecheck && pnpm build && node dist/smoke-lanes.js claude && node dist/smoke-lanes.js codex && node dist/smoke-lanes.js grok`
Expected for each: a `reply:` line naming trailing commas, a `summary:` line starting `<!-- … --> | # Without using any tools… · <provider>`, then `LANES SMOKE OK`. If one provider fails, report its full output; a model that ignores the brief is a finding to report, not something to patch around.

- [ ] **Step 3: Package, docs, commit**

Run: `pnpm test && pnpm run package` → PASS; packaged.

In `docs/superpowers/plans/2026-10-28-mvp-overview.md`, add after the plan 18 row:

```
| 19 | [Lane memory and briefs](2026-10-29-19-lane-memory-and-briefs.md) | `.agentdeck/` lane memory, stamped chat summaries, lane brief and update in prompts, history of moves | Done |
```

In `docs/roadmap.md`, make the line starting `- **19 — Lane memory and briefs:**` end with ` ✓ done.`

```bash
git add scripts/smoke-lanes.ts esbuild.mjs docs
git commit -m "test: live lane brief check; plan 19 done"
```
