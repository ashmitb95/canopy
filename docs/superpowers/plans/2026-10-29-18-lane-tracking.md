# Plan 18: Workspace and lane tracking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first. **Commit at every checkpoint** (each step whose check passes) so a usage limit cannot lose work; end each task with its named commit.

**Goal:** AgentDeck knows, live from Git, which repos the workspace holds, which branch each checkout is on, and which lane each chat belongs to. The Sessions list groups chats by lane and shows where each lane's code lives.

**Architecture:** A pure-Node `src/lanes/` module, which never imports `vscode`.
- **Discovery** finds the repos under the workspace root.
- **`readRepo`** reads each repo's checkouts with `git worktree list --porcelain`, plus its base branch and how many files each checkout has uncommitted.
- **`deriveLanes`** turns those checkouts into lanes. A lane is a branch checked out anywhere other than its repo's base, or a branch a chat is linked to. Nothing about Git is stored (decision 32).
- **`LaneTracker`** re-reads all of this when the Git refs change (`fs.watch` on each repo's common git dir), when a file is saved, when the window regains focus, and when a turn ends.
- **Linking chats to lanes.** A chat's lane is stored on its record (`SessionRecord.laneId`). After a turn, a chat not yet on a lane joins the lane its edits landed in. *Move to lane…* changes the lane by hand.
- **The Sessions tree** groups chats by lane, with each lane's per-repo location. When the workspace has no lanes, it shows today's flat list.

**Out of scope** (later plans):
- ahead/behind, merged and missing state;
- `.agentdeck/` memory and briefs (19);
- switching, warm-up and path enforcement (20);
- grouping in the webview switcher, the composer lane chip, and group actions (21).

**Tech Stack:** as before; `git` from PATH (2.20+ for `--path-format`). The tests create real temporary repos.

---

## File structure

| File | Responsibility |
|---|---|
| `src/lanes/git.ts` | Run git, read-only, without optional locks |
| `src/lanes/discover.ts` | Repos at or under the workspace root |
| `src/lanes/state.ts` | `RepoState` for one repo: checkouts, base branch, dirty counts |
| `src/lanes/lanes.ts` | Pure: lanes from repo states; the lane a file belongs to |
| `src/lanes/group.ts` | Pure: sessions grouped by lane for the tree |
| `src/lanes/tracker.ts` | Live repo states with Git watchers and debounced refresh |
| `src/lanes/auto-link.ts` | After a turn, link an unlinked chat to the lane its edits landed in |
| `src/sessions/store.ts`, `src/sessions/manager.ts` | `laneId` on the record; `setLane`, `diffPaths` |
| `src/ui/sessions-tree.ts` | Lane groups, the *No branch* group, flat when there are no lanes |
| `src/extension.ts`, `package.json` | Wiring; *Move to lane…* |
| `test/lanes/*.test.ts`, `test/lanes/repos.ts` | Tests with real temporary repos |

---

### Task 1: Reading repos

**Files:**
- Create: `src/lanes/git.ts`, `src/lanes/discover.ts`, `src/lanes/state.ts`, `test/lanes/repos.ts`
- Test: `test/lanes/state.test.ts`

- [ ] **Step 1: Test helper for real repos**

`test/lanes/repos.ts`:

```ts
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, realpathSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export function run(cwd: string, ...args: string[]): string {
  return execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
}

/** A temporary workspace root (real path: macOS tmpdir is behind a symlink, and git prints real paths). */
export function workspace(): string {
  return realpathSync(mkdtempSync(join(tmpdir(), 'agentdeck-lanes-')))
}

/** A repo with one commit on `main`. */
export function repo(path: string): string {
  mkdirSync(path, { recursive: true })
  run(path, 'init', '-q', '-b', 'main')
  run(path, 'config', 'user.email', 'test@example.com')
  run(path, 'config', 'user.name', 'Test')
  run(path, 'config', 'commit.gpgsign', 'false')
  writeFileSync(join(path, 'README.md'), '# repo\n')
  run(path, 'add', '.')
  run(path, 'commit', '-q', '-m', 'init')
  return path
}
```

- [ ] **Step 2: Write the failing tests**

`test/lanes/state.test.ts`:

```ts
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { discoverRepos } from '../../src/lanes/discover'
import { parseWorktrees, readRepo } from '../../src/lanes/state'
import { repo, run, workspace } from './repos'

describe('parseWorktrees', () => {
  it('reads the main checkout first, branches, detached heads, and skips bare entries', () => {
    const text = [
      'worktree /w/api\nHEAD aaa\nbranch refs/heads/retry-fix\n',
      'worktree /w/api/.worktrees/auth\nHEAD bbb\nbranch refs/heads/feat/auth\n',
      'worktree /w/api/.worktrees/old\nHEAD ccc\ndetached\n',
      'worktree /w/bare\nbare\n'
    ].join('\n')
    expect(parseWorktrees(text)).toEqual([
      { path: '/w/api', main: true, branch: 'retry-fix' },
      { path: '/w/api/.worktrees/auth', main: false, branch: 'feat/auth' },
      { path: '/w/api/.worktrees/old', main: false }
    ])
  })
})

describe('discoverRepos', () => {
  it('finds repos under the root, skipping their insides and dependency folders', async () => {
    const root = workspace()
    repo(join(root, 'ui'))
    repo(join(root, 'services', 'api'))
    repo(join(root, 'ui', 'packages', 'nested'))
    mkdirSync(join(root, 'node_modules', 'dep'), { recursive: true })
    repo(join(root, 'node_modules', 'dep'))
    expect(await discoverRepos(root)).toEqual([join(root, 'services', 'api'), join(root, 'ui')])
  })

  it('is just the root when the root is a repo', async () => {
    const root = repo(workspace())
    repo(join(root, 'vendor-copy'))
    expect(await discoverRepos(root)).toEqual([root])
  })
})

describe('readRepo', () => {
  it('reads checkouts, the base branch, and uncommitted files', async () => {
    const root = workspace()
    const api = repo(join(root, 'api'))
    run(api, 'checkout', '-q', '-b', 'retry-fix')
    run(api, 'worktree', 'add', '-q', '-b', 'auth', join(api, '.worktrees', 'auth'))
    writeFileSync(join(api, 'a.ts'), 'a')
    writeFileSync(join(api, 'README.md'), 'changed')
    expect(await readRepo(root, api)).toEqual({
      path: api,
      name: 'api',
      base: 'main',
      checkouts: [
        { path: api, main: true, branch: 'retry-fix', dirty: 2 },
        { path: join(api, '.worktrees', 'auth'), main: false, branch: 'auth', dirty: 0 }
      ]
    })
  })

  it('takes the base branch from origin when there is one', async () => {
    const root = workspace()
    const origin = repo(join(root, 'origin'))
    run(origin, 'branch', '-q', '-m', 'trunk-line')
    run(root, 'clone', '-q', origin, join(root, 'clone'))
    expect((await readRepo(root, join(root, 'clone'))).base).toBe('trunk-line')
  })
})
```

Run: `pnpm test test/lanes/state.test.ts` → FAIL (modules missing).

- [ ] **Step 3: Implement**

`src/lanes/git.ts`:

```ts
import { execFile } from 'node:child_process'

/** Runs git and returns stdout. Optional locks are off so reading status never rewrites the index, which the watcher would see. */
export function git(cwd: string, args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(
      'git',
      args,
      { cwd, env: { ...process.env, GIT_OPTIONAL_LOCKS: '0' }, maxBuffer: 16 * 1024 * 1024 },
      (error, stdout, stderr) => (error ? reject(new Error(stderr.trim() || error.message)) : resolve(stdout))
    )
  })
}
```

`src/lanes/discover.ts`:

```ts
import { type Dirent, existsSync } from 'node:fs'
import { readdir } from 'node:fs/promises'
import { join } from 'node:path'

const SKIP = new Set(['node_modules', 'dist', 'build', 'out', 'target', 'vendor'])

/** Git repositories at or under the root. A repo's own folders, hidden folders, and dependency folders are not searched. */
export async function discoverRepos(root: string, depth = 3): Promise<string[]> {
  if (existsSync(join(root, '.git'))) return [root]
  const found: string[] = []
  const walk = async (dir: string, left: number): Promise<void> => {
    if (left === 0) return
    let entries: Dirent[]
    try {
      entries = await readdir(dir, { withFileTypes: true })
    } catch {
      return
    }
    for (const entry of entries) {
      if (!entry.isDirectory() || entry.name.startsWith('.') || SKIP.has(entry.name)) continue
      const path = join(dir, entry.name)
      if (existsSync(join(path, '.git'))) found.push(path)
      else await walk(path, left - 1)
    }
  }
  await walk(root, depth)
  return found.sort()
}
```

`src/lanes/state.ts`:

```ts
import { existsSync } from 'node:fs'
import { basename, relative } from 'node:path'
import { git } from './git'

/** One checkout of a repo: the main checkout or a linked worktree. `branch` is absent on a detached HEAD. */
export type Checkout = { path: string; main: boolean; branch?: string; dirty: number }

export type RepoState = {
  path: string
  /** Path relative to the workspace root, or the folder name when the root is the repo. */
  name: string
  /** The branch nobody "works on": origin's default, else main, master, develop, or trunk. */
  base?: string
  checkouts: Checkout[]
}

/** Parses `git worktree list --porcelain`; the first entry is the main checkout. */
export function parseWorktrees(text: string): Omit<Checkout, 'dirty'>[] {
  return text
    .split('\n\n')
    .map((block) => block.trim())
    .filter(Boolean)
    .flatMap((block, index) => {
      const lines = block.split('\n')
      const path = lines.find((line) => line.startsWith('worktree '))?.slice('worktree '.length)
      if (!path || lines.includes('bare')) return []
      const branch = lines.find((line) => line.startsWith('branch refs/heads/'))?.slice('branch refs/heads/'.length)
      return [{ path, main: index === 0, ...(branch ? { branch } : {}) }]
    })
}

async function baseBranch(path: string): Promise<string | undefined> {
  const remote = (await git(path, ['symbolic-ref', '--quiet', '--short', 'refs/remotes/origin/HEAD']).catch(() => '')).trim()
  if (remote) return remote.replace(/^origin\//, '')
  for (const name of ['main', 'master', 'develop', 'trunk']) {
    const exists = await git(path, ['rev-parse', '--verify', '--quiet', `refs/heads/${name}`]).then(
      () => true,
      () => false
    )
    if (exists) return name
  }
  return undefined
}

async function dirtyFiles(path: string): Promise<number> {
  const status = await git(path, ['status', '--porcelain']).catch(() => '')
  // The worktrees folder sits inside the main checkout; it is not uncommitted work.
  return status.split('\n').filter((line) => line && line !== '?? .worktrees/').length
}

export async function readRepo(root: string, path: string): Promise<RepoState> {
  const [list, base] = await Promise.all([git(path, ['worktree', 'list', '--porcelain']), baseBranch(path)])
  const checkouts = await Promise.all(
    parseWorktrees(list)
      // A worktree whose folder was deleted by hand is listed until pruned; it has nothing to show.
      .filter((checkout) => existsSync(checkout.path))
      .map(async (checkout) => ({ ...checkout, dirty: await dirtyFiles(checkout.path) }))
  )
  return { path, name: relative(root, path) || basename(path), ...(base ? { base } : {}), checkouts }
}
```

Run: `pnpm test test/lanes/state.test.ts` → PASS.

- [ ] **Step 4: Commit**

```bash
git add src/lanes test/lanes
git commit -m "feat(lanes): discover repos and read their checkouts from git"
```

---

### Task 2: Lanes from repo state

**Files:**
- Create: `src/lanes/lanes.ts`, `src/lanes/group.ts`
- Test: `test/lanes/lanes.test.ts`

- [ ] **Step 1: Write the failing tests**

`test/lanes/lanes.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { groupSessions } from '../../src/lanes/group'
import { deriveLanes, laneForPath, laneFromPaths } from '../../src/lanes/lanes'
import type { RepoState } from '../../src/lanes/state'

const repos: RepoState[] = [
  {
    path: '/w/api',
    name: 'api',
    base: 'main',
    checkouts: [
      { path: '/w/api', main: true, branch: 'retry-fix', dirty: 2 },
      { path: '/w/api/.worktrees/auth', main: false, branch: 'auth', dirty: 0 }
    ]
  },
  {
    path: '/w/ui',
    name: 'ui',
    base: 'main',
    checkouts: [
      { path: '/w/ui', main: true, branch: 'main', dirty: 0 },
      { path: '/w/ui/.worktrees/retry-fix', main: false, branch: 'retry-fix', dirty: 1 },
      { path: '/w/ui/.worktrees/old', main: false, dirty: 0 }
    ]
  }
]

describe('deriveLanes', () => {
  it('makes a lane of every branch checked out off base, with its location per repo, plus linked lanes', () => {
    expect(deriveLanes(repos, ['parked'])).toEqual([
      { name: 'auth', repos: [{ repo: 'api', location: 'worktree', path: '/w/api/.worktrees/auth', dirty: 0 }] },
      { name: 'parked', repos: [] },
      {
        name: 'retry-fix',
        repos: [
          { repo: 'api', location: 'main', path: '/w/api', dirty: 2 },
          { repo: 'ui', location: 'worktree', path: '/w/ui/.worktrees/retry-fix', dirty: 1 }
        ]
      }
    ])
  })
})

describe('laneForPath', () => {
  it('uses the innermost checkout, and no lane on base or a detached head', () => {
    expect(laneForPath(repos, '/w/api/src/retry.ts')).toBe('retry-fix')
    expect(laneForPath(repos, '/w/api/.worktrees/auth/src/token.ts')).toBe('auth')
    expect(laneForPath(repos, '/w/ui/src/app.tsx')).toBeUndefined()
    expect(laneForPath(repos, '/w/ui/.worktrees/old/x.ts')).toBeUndefined()
    expect(laneForPath(repos, '/w/api-other/x.ts')).toBeUndefined()
  })

  it('picks the one lane a set of edits landed in, ignoring edits outside lanes', () => {
    expect(laneFromPaths(repos, ['/w/api/a.ts', '/w/ui/.worktrees/retry-fix/b.ts', '/w/ui/c.ts'])).toBe('retry-fix')
    expect(laneFromPaths(repos, ['/w/api/a.ts', '/w/api/.worktrees/auth/b.ts'])).toBeUndefined()
    expect(laneFromPaths(repos, [])).toBeUndefined()
  })
})

describe('groupSessions', () => {
  it('puts sessions under their lane and the rest in loose, keeping lanes without sessions', () => {
    const sessions = [
      { id: 's1', laneId: 'retry-fix' },
      { id: 's2' },
      { id: 's3', laneId: 'retry-fix' }
    ]
    const lanes = deriveLanes(repos, ['retry-fix'])
    expect(groupSessions(lanes, sessions)).toEqual({
      lanes: [
        { lane: lanes[0], sessions: [] },
        { lane: lanes[1], sessions: [sessions[0], sessions[2]] }
      ],
      loose: [sessions[1]]
    })
  })
})
```

Run: `pnpm test test/lanes/lanes.test.ts` → FAIL.

- [ ] **Step 2: Implement**

`src/lanes/lanes.ts`:

```ts
import { sep } from 'node:path'
import type { RepoState } from './state'

export type LaneRepo = { repo: string; location: 'main' | 'worktree'; path: string; dirty: number }

/** A lane is a branch: where it is checked out in each repo is read from Git, never stored. */
export type Lane = { name: string; repos: LaneRepo[] }

function onLane(repo: RepoState, branch: string | undefined): branch is string {
  return branch !== undefined && branch !== repo.base
}

/** Lanes are branches checked out anywhere other than their repo's base, plus lanes chats are linked to. */
export function deriveLanes(repos: RepoState[], linked: Iterable<string> = []): Lane[] {
  const lanes = new Map<string, Lane>()
  const lane = (name: string): Lane => {
    const existing = lanes.get(name)
    if (existing) return existing
    const created: Lane = { name, repos: [] }
    lanes.set(name, created)
    return created
  }
  for (const repo of repos) {
    for (const checkout of repo.checkouts) {
      if (!onLane(repo, checkout.branch)) continue
      lane(checkout.branch).repos.push({
        repo: repo.name,
        location: checkout.main ? 'main' : 'worktree',
        path: checkout.path,
        dirty: checkout.dirty
      })
    }
  }
  for (const name of linked) lane(name)
  return [...lanes.values()].sort((a, b) => a.name.localeCompare(b.name))
}

/** The lane a file belongs to: the branch of the innermost checkout holding it, unless that is the base or a detached head. */
export function laneForPath(repos: RepoState[], file: string): string | undefined {
  let best: { repo: RepoState; branch?: string; length: number } | undefined
  for (const repo of repos) {
    for (const checkout of repo.checkouts) {
      const inside = file === checkout.path || file.startsWith(checkout.path + sep)
      if (inside && (!best || checkout.path.length > best.length)) {
        best = { repo, branch: checkout.branch, length: checkout.path.length }
      }
    }
  }
  return best && onLane(best.repo, best.branch) ? best.branch : undefined
}

/** The one lane a set of edits landed in, or undefined when they landed in none or in several. */
export function laneFromPaths(repos: RepoState[], files: string[]): string | undefined {
  const lanes = new Set(files.flatMap((file) => laneForPath(repos, file) ?? []))
  return lanes.size === 1 ? [...lanes][0] : undefined
}
```

`src/lanes/group.ts`:

```ts
import type { Lane } from './lanes'

export type Grouped<T> = { lanes: { lane: Lane; sessions: T[] }[]; loose: T[] }

/** Sessions under their lane, in the given order; sessions on no known lane are loose. */
export function groupSessions<T extends { laneId?: string }>(lanes: Lane[], sessions: T[]): Grouped<T> {
  const names = new Set(lanes.map((lane) => lane.name))
  return {
    lanes: lanes.map((lane) => ({ lane, sessions: sessions.filter((session) => session.laneId === lane.name) })),
    loose: sessions.filter((session) => session.laneId === undefined || !names.has(session.laneId))
  }
}
```

Run: `pnpm test test/lanes` → PASS.

- [ ] **Step 3: Commit**

```bash
git add src/lanes test/lanes
git commit -m "feat(lanes): derive lanes from checkouts and find the lane a file belongs to"
```

---

### Task 3: The tracker

**Files:**
- Create: `src/lanes/tracker.ts`
- Test: `test/lanes/tracker.test.ts`

- [ ] **Step 1: Write the failing tests**

`test/lanes/tracker.test.ts`:

```ts
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { LaneTracker } from '../../src/lanes/tracker'
import { repo, run, workspace } from './repos'

let tracker: LaneTracker | undefined
afterEach(() => tracker?.dispose())

function changed(subject: LaneTracker): Promise<void> {
  return new Promise((resolve) => {
    const subscription = subject.onDidChange(() => {
      subscription.dispose()
      resolve()
    })
  })
}

describe('LaneTracker', () => {
  it('reads every repo under the root', async () => {
    const root = workspace()
    repo(join(root, 'api'))
    repo(join(root, 'ui'))
    tracker = new LaneTracker(root)
    await tracker.refresh()
    expect(tracker.repos.map((state) => state.name)).toEqual(['api', 'ui'])
  })

  it('notices a branch switch made outside AgentDeck', async () => {
    const root = workspace()
    const api = repo(join(root, 'api'))
    tracker = new LaneTracker(root)
    await tracker.refresh()
    const next = changed(tracker)
    run(api, 'checkout', '-q', '-b', 'retry-fix')
    await next
    expect(tracker.repos[0].checkouts[0].branch).toBe('retry-fix')
  }, 10_000)

  it('does not report a change when nothing changed', async () => {
    const root = workspace()
    repo(join(root, 'api'))
    tracker = new LaneTracker(root)
    await tracker.refresh()
    let fired = 0
    tracker.onDidChange(() => fired++)
    await tracker.refresh()
    expect(fired).toBe(0)
  })
})
```

Run: `pnpm test test/lanes/tracker.test.ts` → FAIL.

- [ ] **Step 2: Implement**

`src/lanes/tracker.ts`:

```ts
import { type FSWatcher, realpathSync, watch } from 'node:fs'
import { Emitter } from '../core/emitter'
import { discoverRepos } from './discover'
import { git } from './git'
import { type RepoState, readRepo } from './state'

const DEBOUNCE_MS = 300

/** Files in a git dir whose change can move a branch or a checkout (paths relative to the common git dir). */
const WATCHED = /^(HEAD|packed-refs|refs[\\/]heads([\\/].*)?|worktrees([\\/][^\\/]+([\\/]HEAD)?)?)$/

/** The workspace's repos as Git sees them right now. Re-read when refs move, and when asked. */
export class LaneTracker {
  readonly root: string
  repos: RepoState[] = []
  private readonly changed = new Emitter<void>()
  readonly onDidChange = this.changed.event
  private readonly watchers = new Map<string, FSWatcher>()
  private timer: ReturnType<typeof setTimeout> | undefined
  private chain: Promise<void> = Promise.resolve()
  private last = ''
  private disposed = false

  constructor(root: string) {
    // Git prints real paths; agents' file paths are compared against them.
    this.root = realpathSync(root)
  }

  /** Re-reads every repo; calls run one after another, so awaiting one sees state at least as new as the call. */
  refresh(): Promise<void> {
    this.chain = this.chain.then(
      () => this.read(),
      () => this.read()
    )
    return this.chain
  }

  /** Refreshes once things settle, for bursts of events. */
  schedule(): void {
    clearTimeout(this.timer)
    this.timer = setTimeout(() => void this.refresh().catch(() => {}), DEBOUNCE_MS)
  }

  dispose(): void {
    this.disposed = true
    clearTimeout(this.timer)
    for (const watcher of this.watchers.values()) watcher.close()
    this.watchers.clear()
  }

  private async read(): Promise<void> {
    if (this.disposed) return
    const paths = await discoverRepos(this.root)
    const states = await Promise.all(paths.map((path) => readRepo(this.root, path).catch(() => undefined)))
    if (this.disposed) return
    this.repos = states.filter((state): state is RepoState => state !== undefined)
    await this.watch(this.repos.map((state) => state.path))
    const snapshot = JSON.stringify(this.repos)
    if (snapshot === this.last) return
    this.last = snapshot
    this.changed.fire()
  }

  private async watch(paths: string[]): Promise<void> {
    for (const [path, watcher] of this.watchers) {
      if (paths.includes(path)) continue
      watcher.close()
      this.watchers.delete(path)
    }
    for (const path of paths) {
      if (this.watchers.has(path) || this.disposed) continue
      const dir = (await git(path, ['rev-parse', '--path-format=absolute', '--git-common-dir']).catch(() => '')).trim()
      if (!dir) continue
      const watcher = watch(dir, { recursive: true }, (_event, file) => {
        if (file && WATCHED.test(file.toString())) this.schedule()
      })
      watcher.on('error', () => {
        watcher.close()
        this.watchers.delete(path)
      })
      this.watchers.set(path, watcher)
    }
  }
}
```

Run: `pnpm test test/lanes` → PASS. If the watcher test flakes on your machine, run it 5 times (`for i in 1 2 3 4 5; do pnpm test test/lanes/tracker.test.ts || break; done`); it must pass every time. Report any flake instead of raising the timeout.

- [ ] **Step 3: Commit**

```bash
git add src/lanes/tracker.ts test/lanes/tracker.test.ts
git commit -m "feat(lanes): live repo state with git watchers"
```

---

### Task 4: Chats on lanes

**Files:**
- Modify: `src/sessions/store.ts`, `src/sessions/manager.ts`, `test/sessions/manager.test.ts`
- Create: `src/lanes/auto-link.ts`
- Test: `test/lanes/auto-link.test.ts`

- [ ] **Step 1: Write the failing tests**

Add inside the `describe` block of `test/sessions/manager.test.ts`:

```ts
  it('puts a chat on a lane and takes it off again', async () => {
    const { manager } = setup()
    const { id } = await manager.create('fake')
    let changes = 0
    manager.onDidChange(() => changes++)
    await manager.setLane(id, 'retry-fix')
    expect(manager.list()[0].record.laneId).toBe('retry-fix')
    await manager.setLane(id, undefined)
    expect(manager.list()[0].record.laneId).toBeUndefined()
    expect(changes).toBe(2)
  })

  it('lists the files a chat edited', async () => {
    const { manager, sessions } = setup()
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('edit'))
    sessions[0].emit({ kind: 'diff', id: 'd1', path: '/w/a.ts', oldText: 'a', newText: 'b' })
    sessions[0].emit({ kind: 'diff', id: 'd2', path: '/w/b.ts', oldText: null, newText: 'c' })
    expect(manager.diffPaths(id)).toEqual(['/w/a.ts', '/w/b.ts'])
  })
```

`test/lanes/auto-link.test.ts`:

```ts
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import type { PromptPart } from '../../src/core/types'
import { autoLink } from '../../src/lanes/auto-link'
import { LaneTracker } from '../../src/lanes/tracker'
import { SessionManager } from '../../src/sessions/manager'
import { SessionStore } from '../../src/sessions/store'
import { fakeProvider } from '../fake-provider'
import { MemoryMemento } from '../memory-memento'
import { repo, run, workspace } from './repos'

const text = (value: string): PromptPart[] => [{ type: 'text', text: value }]
let tracker: LaneTracker | undefined
afterEach(() => tracker?.dispose())

async function setup() {
  const root = workspace()
  const api = repo(join(root, 'api'))
  run(api, 'worktree', 'add', '-q', '-b', 'retry-fix', join(api, '.worktrees', 'retry-fix'))
  const { provider, sessions } = fakeProvider()
  const manager = new SessionManager({
    providers: new Map([[provider.id, provider]]),
    store: new SessionStore(new MemoryMemento()),
    journalDir: mkdtempSync(join(tmpdir(), 'agentdeck-link-')),
    cwd: root,
    env: async () => ({ PATH: '/bin' })
  })
  tracker = new LaneTracker(root)
  await tracker.refresh()
  autoLink(manager, tracker)
  return { manager, sessions, api }
}

function linked(manager: SessionManager, id: string): Promise<string | undefined> {
  return new Promise((resolve) => {
    const check = () => {
      const laneId = manager.list().find(({ record }) => record.id === id)?.record.laneId
      if (laneId) {
        subscription.dispose()
        resolve(laneId)
      }
    }
    const subscription = manager.onDidChange(check)
  })
}

describe('autoLink', () => {
  it('links a chat to the lane its edits landed in when the turn ends', async () => {
    const { manager, sessions, api } = await setup()
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('edit'))
    sessions[0].emit({ kind: 'diff', id: 'd1', path: join(api, '.worktrees', 'retry-fix', 'a.ts'), oldText: null, newText: 'a' })
    const lane = linked(manager, id)
    sessions[0].emit({ kind: 'turn', id: 't1', state: 'ended' })
    expect(await lane).toBe('retry-fix')
  })

  it('leaves a chat that edited only the base checkout unlinked', async () => {
    const { manager, sessions } = await setup()
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('edit'))
    sessions[0].emit({ kind: 'diff', id: 'd1', path: 'api/README.md', oldText: 'a', newText: 'b' })
    sessions[0].emit({ kind: 'turn', id: 't1', state: 'ended' })
    await tracker?.refresh()
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(manager.list()[0].record.laneId).toBeUndefined()
  })
})
```

Run: `pnpm test test/sessions test/lanes/auto-link.test.ts` → FAIL.

- [ ] **Step 2: Implement**

In `src/sessions/store.ts`, add to `SessionRecord` after `hasTurns`:

```ts
  /** The lane (branch) this chat works on; absent for chats on no lane. */
  laneId?: string
```

In `src/sessions/manager.ts`, add after `rename`:

```ts
  async setLane(id: string, laneId: string | undefined): Promise<void> {
    const live = this.load(id)
    if (laneId === undefined) delete live.record.laneId
    else live.record.laneId = laneId
    await this.save(live)
    this.changed.fire()
  }

  /** Files the chat's diffs touched, as the provider reported them (absolute, or relative to the workspace root). */
  diffPaths(id: string): string[] {
    return [...this.load(id).items.values()].flatMap((item) => (item.kind === 'diff' ? [item.path] : []))
  }
```

`src/lanes/auto-link.ts`:

```ts
import { resolve } from 'node:path'
import type { Disposable } from '../core/emitter'
import type { SessionManager } from '../sessions/manager'
import { laneFromPaths } from './lanes'
import type { LaneTracker } from './tracker'

/** After a turn, a chat on no lane joins the one lane its edits landed in. Agents may branch on their own; this keeps up. */
export function autoLink(manager: SessionManager, tracker: LaneTracker): Disposable {
  return manager.onAttention(({ sessionId, reason }) => {
    if (reason !== 'turn-ended') return
    void tracker.refresh().then(async () => {
      const record = manager.list().find((entry) => entry.record.id === sessionId)?.record
      if (!record || record.laneId) return
      const files = manager.diffPaths(sessionId).map((path) => resolve(tracker.root, path))
      const lane = laneFromPaths(tracker.repos, files)
      if (lane) await manager.setLane(sessionId, lane)
    })
  })
}
```

Run: `pnpm test` → PASS.

- [ ] **Step 3: Commit**

```bash
git add src/sessions src/lanes/auto-link.ts test/sessions/manager.test.ts test/lanes/auto-link.test.ts
git commit -m "feat(lanes): chats carry a lane and join the lane their edits landed in"
```

---

### Task 5: Sessions grouped by lane

**Files:**
- Modify: `src/ui/sessions-tree.ts` (full replacement), `src/extension.ts`, `package.json`

- [ ] **Step 1: The tree**

`src/ui/sessions-tree.ts` (full replacement):

```ts
import * as vscode from 'vscode'
import { groupSessions } from '../lanes/group'
import { deriveLanes, type Lane } from '../lanes/lanes'
import type { LaneTracker } from '../lanes/tracker'
import type { SessionManager } from '../sessions/manager'
import type { SessionStatus } from '../sessions/store'
import { relativeTime } from './time'

export type SessionNode = {
  kind: 'session'
  id: string
  title: string
  status: SessionStatus
  updatedAt: string
  provider: string
  laneId?: string
}
type LaneNode = { kind: 'lane'; lane: Lane; sessions: SessionNode[] }
type LooseNode = { kind: 'loose'; sessions: SessionNode[] }
type Node = SessionNode | LaneNode | LooseNode

const ICONS: Record<SessionStatus, vscode.ThemeIcon> = {
  idle: new vscode.ThemeIcon('comment'),
  running: new vscode.ThemeIcon('loading~spin'),
  'needs-input': new vscode.ThemeIcon('bell-dot', new vscode.ThemeColor('editorWarning.foreground')),
  error: new vscode.ThemeIcon('error', new vscode.ThemeColor('errorForeground')),
  stopped: new vscode.ThemeIcon('debug-stop')
}

/** "api main ●2 · ui worktree": where the lane's code lives in each repo, with uncommitted files. */
export function laneDescription(lane: Lane): string {
  if (lane.repos.length === 0) return 'no checkout'
  return lane.repos.map((repo) => `${repo.repo} ${repo.location}${repo.dirty > 0 ? ` ●${repo.dirty}` : ''}`).join(' · ')
}

export class SessionsTree implements vscode.TreeDataProvider<Node>, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<void>()
  readonly onDidChangeTreeData = this.changed.event
  private readonly view: vscode.TreeView<Node>
  private readonly subscriptions: { dispose(): void }[]

  constructor(
    private readonly manager: SessionManager,
    private readonly labels: ReadonlyMap<string, string>,
    private readonly tracker: LaneTracker | undefined
  ) {
    this.view = vscode.window.createTreeView('agentdeck.sessions', { treeDataProvider: this })
    this.subscriptions = [manager.onDidChange(() => this.refresh()), ...(tracker ? [tracker.onDidChange(() => this.refresh())] : [])]
    this.refresh()
  }

  /** Lanes, for *Move to lane…*: every lane Git shows plus every lane a chat is on. */
  lanes(): Lane[] {
    return deriveLanes(this.tracker?.repos ?? [], this.sessions().flatMap((session) => session.laneId ?? []))
  }

  getChildren(element?: Node): Node[] {
    if (element) return element.kind === 'session' ? [] : element.sessions
    const sessions = this.sessions()
    const grouped = groupSessions(this.lanes(), sessions)
    // No lanes in this workspace: the plain list, as before.
    if (grouped.lanes.length === 0) return sessions
    const lanes: Node[] = grouped.lanes.map(({ lane, sessions }) => ({ kind: 'lane', lane, sessions }))
    return grouped.loose.length > 0 ? [...lanes, { kind: 'loose', sessions: grouped.loose }] : lanes
  }

  getTreeItem(node: Node): vscode.TreeItem {
    if (node.kind === 'lane') {
      const item = new vscode.TreeItem(node.lane.name, vscode.TreeItemCollapsibleState.Expanded)
      item.id = `lane:${node.lane.name}`
      item.description = laneDescription(node.lane)
      item.tooltip = node.lane.repos.map((repo) => `${repo.repo}: ${repo.path}`).join('\n') || 'No checkout'
      item.iconPath = new vscode.ThemeIcon('git-branch')
      item.contextValue = 'lane'
      return item
    }
    if (node.kind === 'loose') {
      const item = new vscode.TreeItem('No branch', vscode.TreeItemCollapsibleState.Expanded)
      item.id = 'lane:none'
      item.iconPath = new vscode.ThemeIcon('circle-slash')
      return item
    }
    const item = new vscode.TreeItem(node.title)
    item.id = node.id
    item.description = relativeTime(node.updatedAt)
    item.tooltip = `${node.provider} · ${node.status}`
    item.iconPath = ICONS[node.status]
    item.contextValue = 'session'
    item.command = { command: 'agentdeck.openSession', title: 'Open', arguments: [node] }
    return item
  }

  dispose(): void {
    for (const subscription of this.subscriptions) subscription.dispose()
    this.view.dispose()
    this.changed.dispose()
  }

  private sessions(): SessionNode[] {
    return this.manager.list().map(({ record, status }) => ({
      kind: 'session',
      id: record.id,
      title: record.title,
      status,
      updatedAt: record.updatedAt,
      provider: this.labels.get(record.providerId) ?? record.providerId,
      ...(record.laneId ? { laneId: record.laneId } : {})
    }))
  }

  private refresh(): void {
    this.changed.fire()
    const waiting = this.manager.list().filter(({ status }) => status === 'needs-input').length
    this.view.badge = waiting > 0 ? { value: waiting, tooltip: `${waiting} waiting for input` } : undefined
  }
}
```

- [ ] **Step 2: Wiring**

In `src/extension.ts`:
- add imports: `import { autoLink } from './lanes/auto-link'` and `import { LaneTracker } from './lanes/tracker'`;
- before `manager = new SessionManager(…)`, add:

```ts
  const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
  // Without a folder there is nothing to track (and the home folder is not scanned).
  const tracker = root ? new LaneTracker(root) : undefined
```

  and change `cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? homedir(),` to `cwd: root ?? homedir(),`;
- replace `new SessionsTree(sessionManager, new Map([...providers].map(([id, provider]) => [id, provider.label]))),` in the `push(…)` with `tree,` and declare before `context.subscriptions.push(`:

```ts
  const tree = new SessionsTree(sessionManager, new Map([...providers].map(([id, provider]) => [id, provider.label])), tracker)
```

- add to the `push(…)` list:

```ts
    vscode.commands.registerCommand('agentdeck.moveSessionToLane', async (node: SessionNode) => {
      const none = { label: '$(circle-slash) No branch', lane: undefined }
      const choices = [
        ...tree.lanes().map((lane) => ({ label: `$(git-branch) ${lane.name}`, description: laneDescription(lane), lane: lane.name })),
        none
      ]
      const choice = await vscode.window.showQuickPick(choices, { placeHolder: `Move “${node.title}” to…` })
      if (choice) await sessionManager.setLane(node.id, choice.lane)
    }),
```

  (import `laneDescription` with `SessionsTree` from `./ui/sessions-tree`);
- after the `push(…)` call, add:

```ts
  if (tracker) {
    void tracker.refresh().catch(() => {})
    context.subscriptions.push(
      tracker,
      autoLink(sessionManager, tracker),
      // Saves change dirty counts; refocusing catches work done in a terminal or another app.
      vscode.workspace.onDidSaveTextDocument(() => tracker.schedule()),
      vscode.window.onDidChangeWindowState((state) => state.focused && tracker.schedule())
    )
  }
```

In `package.json`:
- add to `contributes.commands`: `{ "command": "agentdeck.moveSessionToLane", "title": "Move to Lane…", "category": "AgentDeck" }` (match how the other entries are written, e.g. whether they carry `category` or `icon`);
- add to `menus.view/item/context`, after `agentdeck.renameSession`: `{ "command": "agentdeck.moveSessionToLane", "when": "view == agentdeck.sessions && viewItem == session", "group": "2_edit@2" }`, and change `agentdeck.stopSession`'s group to `"2_edit@3"`;
- add to `menus.commandPalette`: `{ "command": "agentdeck.moveSessionToLane", "when": "false" }`.

- [ ] **Step 3: Verify**

Run: `pnpm typecheck && pnpm test && pnpm build` → clean; PASS; built.

- [ ] **Step 4: Commit**

```bash
git add src/ui/sessions-tree.ts src/extension.ts package.json
git commit -m "feat(lanes): group sessions by lane with where each lane's code lives"
```

---

### Task 6: Check and hand off

- [ ] **Step 1: Package**

Run: `pnpm test && pnpm run package` → PASS; packaged.

- [ ] **Step 2: Mark the plan done**

In `docs/superpowers/plans/2026-10-28-mvp-overview.md`, add after the plan 11 row:

```
| 18 | [Workspace and lane tracking](2026-10-29-18-lane-tracking.md) | Repos and checkouts read live from Git, lanes derived from branches, chats linked to lanes, Sessions grouped by lane | Done |
```

In `docs/roadmap.md`, change the line starting `- **18 — Workspace and lane tracking:**` to end with ` ✓ done.`

```bash
git add docs
git commit -m "docs: plan 18 done"
```

- [ ] **Step 3: Hand off**

Ask the user to reinstall, open a workspace with several repos (such as `docsum/`), and check:
- **Sessions list:** shows a lane group for each branch checked out off base, with "api main · ui worktree", and a ● count of uncommitted files that updates on save.
- **Terminal switch:** `git checkout -b x` in one repo makes an `x` group appear within a second.
- **Auto-link:** a chat that edits files in a worktree moves under that lane when its turn ends.
- **Manual move:** *Move to Lane…* on a chat moves it, and choosing *No branch* takes it off.
- **No lanes:** a workspace without lanes shows the plain list, as before.
