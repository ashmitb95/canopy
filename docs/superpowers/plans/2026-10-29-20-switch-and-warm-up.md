# Plan 20: Switch, warm-up, and lane boundaries — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the [MVP overview](2026-10-28-mvp-overview.md) conventions first. **Commit at every checkpoint** (each step whose check passes) so a usage limit cannot lose work; end each task with its named commit. Write files with the code itself; never extract code blocks from this plan with `sed` line ranges (fence lines leak in).

**Goal:** Lanes move into and out of the main checkouts on request, and uncommitted work travels with each lane.
- **Warm-up:** a lane moved out of main is warmed up in its worktree: env files are copied in and a setup command runs.
- **Joining a repo:** a lane joins a new repo when its chat first edits there.
- **One writer:** only one chat per lane runs a turn at a time.
- **Boundaries:** each chat on a lane can write only inside its lane's paths. Claude, Codex and Grok each enforce this.

**Architecture:** This plan follows the [lanes spec](../specs/2026-10-29-lanes-and-control-center.md) sections *Switching and warming*, *Enforcement*, and *Settled*.

The pieces:
- **Git operations** (`switch.ts`), tested against real repos:
  - moving a lane into main;
  - moving a lane to a worktree;
  - joining a repo.

  Each operation stashes uncommitted work under a unique message and re-applies it where the lane lands. It never runs `reset --hard` and never deletes a branch.
- **Workspace config:** `.agentdeck/config.toml` holds the env-file patterns, a setup command per repo, and the default worktree toggle. Each lane can override the toggle in its own `lane.toml`.
- **The coordinator** (`coordinator.ts`) runs a switch end to end:
  1. It refuses while any affected chat is mid-turn.
  2. It moves the lanes.
  3. It warms up whatever moved out.
  4. It records the move in history.
  5. It posts a one-line notice in every affected chat.

  It also builds each chat's write boundary.
- **The session manager:**
  - queues a prompt while another chat on the same lane is running, and sends it when that turn ends;
  - passes the boundary to the provider before every prompt.
- **How each provider enforces the boundary:**
  - **Claude:** a `PreToolUse` hook denies `Edit`, `Write`, `MultiEdit` and `NotebookEdit` calls outside the boundary, and branch switches in Bash. It runs in every mode, including full access.
  - **Codex:** the turn's `writableRoots` are set to the boundary.
  - **ACP:** an edit permission request whose paths fall outside the boundary is rejected, and a notice is shown.
- **Redirecting a write that misses the lane:**
  - An edit aimed at the same repo but outside the lane's checkout is redirected to the matching file in the lane's own checkout.
  - An edit in a repo the lane hasn't joined makes the lane join that repo, following its worktree toggle, and redirects there.
- **UI:**
  - *New Lane…* is a Sessions view title action;
  - *Move into Main* and *Move to Worktrees* are on a lane;
  - switch notices appear in chats.

**Tech Stack:** as before.

---

## File structure

| File | Responsibility |
|---|---|
| `src/core/types.ts` | `WriteBoundary`; `ProviderSession.setBoundary` |
| `src/providers/boundary.ts` | Pure: is a path writable; which paths a Claude tool writes; branch-switch commands |
| `src/providers/{claude,codex,acp}/provider.ts` | Enforcement |
| `src/sessions/manager.ts` | One writer per lane; `notify`; `busyOn`; `boundary` dep |
| `src/lanes/switch.ts` | Git: move into main, move to worktree, join a repo |
| `src/lanes/config.ts`, `src/lanes/warmup.ts`, `src/lanes/memory.ts` | Config, warm-up, per-lane worktree toggle |
| `src/lanes/coordinator.ts` | Switches end to end; boundaries; new lanes |
| `src/extension.ts`, `package.json` | Commands |
| `scripts/smoke-boundary.ts`, `esbuild.mjs` | Live check of enforcement |

---

### Task 1: Git operations

**Files:**
- Create: `src/lanes/switch.ts`
- Test: `test/lanes/switch.test.ts`

- [ ] **Step 1: Write the failing tests**

`test/lanes/switch.test.ts`:

```ts
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { readRepo } from '../../src/lanes/state'
import { joinRepo, moveIntoMain, moveToWorktree, SwitchError, worktreePath } from '../../src/lanes/switch'
import { repo, run, workspace } from './repos'

async function setup() {
  const root = workspace()
  const api = repo(join(root, 'api'))
  return { root, api, state: () => readRepo(root, api) }
}

const branchIn = (path: string) => run(path, 'branch', '--show-current').trim()

describe('moveIntoMain', () => {
  it('swaps lanes, carrying each lane’s uncommitted work', async () => {
    const { api, state } = await setup()
    run(api, 'branch', 'a')
    run(api, 'worktree', 'add', '-q', join(api, '.worktrees', 'a'), 'a')
    run(api, 'checkout', '-q', '-b', 'b')
    writeFileSync(join(api, 'b-work.txt'), 'b')
    writeFileSync(join(api, '.worktrees', 'a', 'a-work.txt'), 'a')

    expect(await moveIntoMain(await state(), 'a')).toEqual({ movedOut: 'b', worktree: worktreePath(api, 'b') })
    expect(branchIn(api)).toBe('a')
    expect(readFileSync(join(api, 'a-work.txt'), 'utf8')).toBe('a')
    expect(existsSync(join(api, 'b-work.txt'))).toBe(false)
    expect(branchIn(worktreePath(api, 'b'))).toBe('b')
    expect(readFileSync(join(worktreePath(api, 'b'), 'b-work.txt'), 'utf8')).toBe('b')
    expect(existsSync(join(api, '.worktrees', 'a'))).toBe(false)
    expect(run(api, 'stash', 'list').trim()).toBe('')
  })

  it('checks out a parked lane, or creates it from base', async () => {
    const { api, state } = await setup()
    run(api, 'branch', 'parked')
    expect(await moveIntoMain(await state(), 'parked')).toEqual({})
    expect(branchIn(api)).toBe('parked')
    run(api, 'checkout', '-q', 'main')
    expect(await moveIntoMain(await state(), 'fresh')).toEqual({})
    expect(branchIn(api)).toBe('fresh')
  })

  it('refuses when main holds uncommitted work on the base branch', async () => {
    const { api, state } = await setup()
    writeFileSync(join(api, 'README.md'), 'changed')
    await expect(moveIntoMain(await state(), 'x')).rejects.toBeInstanceOf(SwitchError)
    expect(branchIn(api)).toBe('main')
  })
})

describe('moveToWorktree', () => {
  it('moves the lane out of main with its work and puts base back', async () => {
    const { api, state } = await setup()
    run(api, 'checkout', '-q', '-b', 'x')
    writeFileSync(join(api, 'x-work.txt'), 'x')
    expect(await moveToWorktree(await state(), 'x')).toBe(worktreePath(api, 'x'))
    expect(branchIn(api)).toBe('main')
    expect(existsSync(join(api, 'x-work.txt'))).toBe(false)
    expect(readFileSync(join(worktreePath(api, 'x'), 'x-work.txt'), 'utf8')).toBe('x')
  })

  it('makes a worktree for a parked lane and returns an existing one as is', async () => {
    const { api, state } = await setup()
    run(api, 'branch', 'p')
    const path = await moveToWorktree(await state(), 'p')
    expect(branchIn(path)).toBe('p')
    expect(await moveToWorktree(await state(), 'p')).toBe(path)
  })

  it('keeps .worktrees out of the repo’s status', async () => {
    const { api, state } = await setup()
    run(api, 'branch', 'p')
    await moveToWorktree(await state(), 'p')
    expect(run(api, 'status', '--porcelain').trim()).toBe('')
  })
})

describe('joinRepo', () => {
  it('starts the lane in a worktree from base', async () => {
    const { api, state } = await setup()
    const path = await joinRepo(await state(), 'feat/x', true)
    expect(path).toBe(join(api, '.worktrees', 'feat--x'))
    expect(branchIn(path)).toBe('feat/x')
  })

  it('starts the lane in main when worktrees are off and main is free', async () => {
    const { api, state } = await setup()
    expect(await joinRepo(await state(), 'y', false)).toBe(api)
    expect(branchIn(api)).toBe('y')
  })

  it('refuses main when another lane holds it', async () => {
    const { api, state } = await setup()
    run(api, 'checkout', '-q', '-b', 'other')
    await expect(joinRepo(await state(), 'y', false)).rejects.toThrow(/main checkout is busy/)
  })
})
```

Run: `pnpm test test/lanes/switch.test.ts` → FAIL.

- [ ] **Step 2: Implement**

`src/lanes/switch.ts`:

```ts
import { appendFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { git } from './git'
import type { RepoState } from './state'

/** A switch step that cannot complete cleanly; the message says what was left where. */
export class SwitchError extends Error {}

export function worktreePath(repo: string, lane: string): string {
  return join(repo, '.worktrees', lane.replaceAll('/', '--'))
}

/** `.worktrees/` stays out of the repo's status and stashes, without touching a committed .gitignore. */
export async function excludeWorktrees(repo: string): Promise<void> {
  const common = (await git(repo, ['rev-parse', '--path-format=absolute', '--git-common-dir'])).trim()
  const file = join(common, 'info', 'exclude')
  const current = existsSync(file) ? readFileSync(file, 'utf8') : ''
  if (current.split('\n').includes('.worktrees/')) return
  mkdirSync(dirname(file), { recursive: true })
  appendFileSync(file, `${current && !current.endsWith('\n') ? '\n' : ''}.worktrees/\n`)
}

async function branchExists(repo: string, branch: string): Promise<boolean> {
  return git(repo, ['rev-parse', '--verify', '--quiet', `refs/heads/${branch}`]).then(
    () => true,
    () => false
  )
}

async function isDirty(path: string): Promise<boolean> {
  return (await git(path, ['status', '--porcelain'])).trim() !== ''
}

/** Stashes uncommitted work, untracked files included, under a unique message; undefined when clean. */
async function stash(path: string, lane: string): Promise<string | undefined> {
  if (!(await isDirty(path))) return undefined
  const message = `agentdeck:${lane}:${Date.now()}`
  await git(path, ['stash', 'push', '--include-untracked', '-m', message])
  return message
}

/** Re-applies a stash made by `stash`. On conflict the stash is kept and the switch stops. */
async function unstash(path: string, message: string | undefined): Promise<void> {
  if (!message) return
  const list = await git(path, ['stash', 'list', '--format=%gd %gs'])
  const ref = list
    .split('\n')
    .find((line) => line.endsWith(message))
    ?.split(' ')[0]
  if (!ref) throw new SwitchError(`The stash “${message}” is missing.`)
  try {
    await git(path, ['stash', 'pop', ref])
  } catch {
    throw new SwitchError(
      `Uncommitted changes did not re-apply cleanly in ${path}. They are kept in ${ref} (“${message}”): resolve the conflict, then drop that stash.`
    )
  }
}

export type MoveResult = { movedOut?: string; worktree?: string }

/** Brings `lane` into the repo's main checkout. The lane holding main moves to a worktree; uncommitted work travels with each lane. */
export async function moveIntoMain(repo: RepoState, lane: string): Promise<MoveResult> {
  const main = repo.checkouts.find((checkout) => checkout.main)
  if (!main) throw new SwitchError(`${repo.name} has no main checkout.`)
  if (main.branch === lane) return {}
  await excludeWorktrees(repo.path)
  const holder = main.branch && main.branch !== repo.base ? main.branch : undefined
  if (!holder && (await isDirty(main.path))) {
    throw new SwitchError(
      `${repo.name} has uncommitted changes on ${main.branch ?? 'a detached HEAD'}. Commit or stash them, then move ${lane} in.`
    )
  }
  const heldWork = holder ? await stash(main.path, holder) : undefined
  const own = repo.checkouts.find((checkout) => !checkout.main && checkout.branch === lane)
  let laneWork: string | undefined
  if (own) {
    laneWork = await stash(own.path, lane)
    // A branch cannot be checked out twice; its worktree goes, its work came along in the stash.
    await git(repo.path, ['worktree', 'remove', own.path])
  }
  if (await branchExists(repo.path, lane)) await git(main.path, ['checkout', lane])
  else await git(main.path, ['checkout', '-b', lane, repo.base ?? 'HEAD'])
  await unstash(main.path, laneWork)
  if (!holder) return {}
  const worktree = worktreePath(repo.path, holder)
  await git(repo.path, ['worktree', 'add', worktree, holder])
  await unstash(worktree, heldWork)
  return { movedOut: holder, worktree }
}

/** Moves `lane` out of the main checkout into its worktree (main goes back to base); for a parked lane, makes the worktree. */
export async function moveToWorktree(repo: RepoState, lane: string): Promise<string> {
  const main = repo.checkouts.find((checkout) => checkout.main)
  if (main?.branch !== lane) {
    const existing = repo.checkouts.find((checkout) => checkout.branch === lane)
    if (existing) return existing.path
    if (!(await branchExists(repo.path, lane))) throw new SwitchError(`${repo.name} has no branch ${lane}.`)
    await excludeWorktrees(repo.path)
    const worktree = worktreePath(repo.path, lane)
    await git(repo.path, ['worktree', 'add', worktree, lane])
    return worktree
  }
  if (!repo.base) throw new SwitchError(`${repo.name} has no base branch to put back in main.`)
  await excludeWorktrees(repo.path)
  const work = await stash(main.path, lane)
  await git(main.path, ['checkout', repo.base])
  const worktree = worktreePath(repo.path, lane)
  await git(repo.path, ['worktree', 'add', worktree, lane])
  await unstash(worktree, work)
  return worktree
}

/** Starts `lane` in a repo: in a worktree, or (worktrees off) in the main checkout when that is clean and on base. */
export async function joinRepo(repo: RepoState, lane: string, worktrees: boolean): Promise<string> {
  const existing = repo.checkouts.find((checkout) => checkout.branch === lane)
  if (existing) return existing.path
  const exists = await branchExists(repo.path, lane)
  if (worktrees) {
    await excludeWorktrees(repo.path)
    const worktree = worktreePath(repo.path, lane)
    await git(repo.path, exists ? ['worktree', 'add', worktree, lane] : ['worktree', 'add', '-b', lane, worktree, repo.base ?? 'HEAD'])
    return worktree
  }
  const main = repo.checkouts.find((checkout) => checkout.main)
  if (!main) throw new SwitchError(`${repo.name} has no main checkout.`)
  if (main.branch !== repo.base || (await isDirty(main.path))) {
    throw new SwitchError(
      `${repo.name}'s main checkout is busy (${main.branch ?? 'detached HEAD'}). Move ${lane} into main from AgentDeck, or turn worktrees on for this lane.`
    )
  }
  await git(main.path, exists ? ['checkout', lane] : ['checkout', '-b', lane])
  return main.path
}
```

Run: `pnpm test test/lanes/switch.test.ts` → PASS.

- [ ] **Step 3: Commit**

```bash
git add src/lanes/switch.ts test/lanes/switch.test.ts
git commit -m "feat(lanes): move lanes into and out of main, and join repos, carrying uncommitted work"
```

---

### Task 2: Config, worktree toggle, and warm-up

**Files:**
- Create: `src/lanes/config.ts`, `src/lanes/warmup.ts`
- Modify: `src/lanes/memory.ts`
- Test: `test/lanes/warmup.test.ts`

- [ ] **Step 1: Write the failing tests**

`test/lanes/warmup.test.ts`:

```ts
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { readConfig } from '../../src/lanes/config'
import { LaneMemory } from '../../src/lanes/memory'
import { matchEnvFiles, warmUp } from '../../src/lanes/warmup'
import { workspace } from './repos'

describe('readConfig', () => {
  it('defaults: .env* files, no setup, worktrees on', () => {
    expect(readConfig(workspace())).toEqual({ envFiles: ['.env*'], setup: {}, worktrees: true })
  })

  it('reads env files, setup per repo, and the worktree default', () => {
    const root = workspace()
    mkdirSync(join(root, '.agentdeck'))
    writeFileSync(
      join(root, '.agentdeck', 'config.toml'),
      'env_files = [".env", "config/local.json"]\nworktrees = false\n\n[setup]\napi = "pnpm install"\n'
    )
    expect(readConfig(root)).toEqual({ envFiles: ['.env', 'config/local.json'], setup: { api: 'pnpm install' }, worktrees: false })
  })
})

describe('lane worktree toggle', () => {
  it('is unset until chosen', () => {
    const memory = new LaneMemory(workspace())
    expect(memory.worktrees('x')).toBeUndefined()
    memory.setWorktrees('x', false)
    expect(memory.worktrees('x')).toBe(false)
  })
})

describe('warmUp', () => {
  it('copies matching env files without overwriting, then runs setup', async () => {
    const main = workspace()
    const target = workspace()
    writeFileSync(join(main, '.env'), 'A=1')
    writeFileSync(join(main, '.env.local'), 'B=2')
    writeFileSync(join(main, 'README.md'), 'x')
    mkdirSync(join(main, 'config'))
    writeFileSync(join(main, 'config', 'local.json'), '{}')
    writeFileSync(join(target, '.env.local'), 'B=mine')
    expect(matchEnvFiles(main, ['.env*', 'config/local.json']).sort()).toEqual(['.env', '.env.local', 'config/local.json'])
    const result = await warmUp(main, target, ['.env*', 'config/local.json'], 'echo ready > setup-ran.txt')
    expect(result.copied.sort()).toEqual(['.env', 'config/local.json'])
    expect(readFileSync(join(target, '.env.local'), 'utf8')).toBe('B=mine')
    expect(readFileSync(join(target, 'config', 'local.json'), 'utf8')).toBe('{}')
    expect(result.setup).toMatchObject({ command: 'echo ready > setup-ran.txt', ok: true })
    expect(readFileSync(join(target, 'setup-ran.txt'), 'utf8').trim()).toBe('ready')
  })

  it('reports a failing setup with the end of its output', async () => {
    const result = await warmUp(workspace(), workspace(), [], 'echo broken >&2; exit 3')
    expect(result.setup).toMatchObject({ ok: false, output: 'broken' })
  })
})
```

Run: `pnpm test test/lanes/warmup.test.ts` → FAIL.

- [ ] **Step 2: Implement**

`src/lanes/config.ts`:

```ts
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { parseToml } from './toml'

export type WorkspaceConfig = {
  /** Files copied from a main checkout into a new worktree: names or paths relative to the repo; a trailing `*` matches the rest of a name. */
  envFiles: string[]
  /** Setup command per repo name, run in a new worktree (e.g. `pnpm install`). */
  setup: Record<string, string>
  /** Whether new lanes start in worktrees; each lane can override it. */
  worktrees: boolean
}

/** `.agentdeck/config.toml`, with defaults for anything missing. */
export function readConfig(root: string): WorkspaceConfig {
  const path = join(root, '.agentdeck', 'config.toml')
  const data = existsSync(path) ? parseToml(readFileSync(path, 'utf8')) : {}
  const strings = (value: unknown) => (Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : undefined)
  const setup = typeof data.setup === 'object' && data.setup !== null && !Array.isArray(data.setup) ? data.setup : {}
  return {
    envFiles: strings(data.env_files) ?? ['.env*'],
    setup: Object.fromEntries(Object.entries(setup).filter((entry): entry is [string, string] => typeof entry[1] === 'string')),
    worktrees: data.worktrees !== false
  }
}
```

`src/lanes/warmup.ts`:

```ts
import { exec } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync, readdirSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'

const SETUP_TIMEOUT_MS = 10 * 60_000
const OUTPUT_LINES = 20

/** Files in `from` matching the patterns: a trailing `*` matches the rest of a top-level name; other patterns are exact paths. */
export function matchEnvFiles(from: string, patterns: string[]): string[] {
  const top = existsSync(from) ? readdirSync(from) : []
  return [
    ...new Set(
      patterns.flatMap((pattern) =>
        pattern.endsWith('*')
          ? top.filter((name) => name.startsWith(pattern.slice(0, -1)))
          : existsSync(join(from, pattern))
            ? [pattern]
            : []
      )
    )
  ].filter((name) => statSync(join(from, name)).isFile())
}

export type WarmResult = { copied: string[]; setup?: { command: string; ok: boolean; output: string } }

/** Readies a checkout outside main: copies env files from the main checkout (never overwriting), then runs the setup command. */
export async function warmUp(
  main: string,
  target: string,
  envFiles: string[],
  setup: string | undefined,
  env: NodeJS.ProcessEnv = process.env
): Promise<WarmResult> {
  const copied = matchEnvFiles(main, envFiles).filter((name) => !existsSync(join(target, name)))
  for (const name of copied) {
    mkdirSync(dirname(join(target, name)), { recursive: true })
    copyFileSync(join(main, name), join(target, name))
  }
  if (!setup) return { copied }
  const outcome = await new Promise<{ ok: boolean; output: string }>((resolve) =>
    exec(setup, { cwd: target, env, timeout: SETUP_TIMEOUT_MS, maxBuffer: 32 * 1024 * 1024 }, (error, stdout, stderr) =>
      resolve({ ok: !error, output: `${stdout}${stderr}`.trim().split('\n').slice(-OUTPUT_LINES).join('\n') })
    )
  )
  return { copied, setup: { command: setup, ...outcome } }
}
```

In `src/lanes/memory.ts`, add after `setGoal`:

```ts
  /** The lane's own worktree toggle; undefined means the workspace default. */
  worktrees(lane: string): boolean | undefined {
    const value = this.lane(lane).worktrees
    return typeof value === 'boolean' ? value : undefined
  }

  setWorktrees(lane: string, on: boolean): void {
    this.ensure(lane)
    writeFileSync(join(this.laneDir(lane), 'lane.toml'), stringifyToml({ ...this.lane(lane), worktrees: on }))
  }
```

Run: `pnpm test test/lanes` → PASS.

- [ ] **Step 3: Commit**

```bash
git add src/lanes test/lanes/warmup.test.ts
git commit -m "feat(lanes): workspace config, per-lane worktree toggle, and warm-up"
```

---

### Task 3: One writer per lane, notices, boundaries in the manager

**Files:**
- Modify: `src/core/types.ts`, `src/sessions/manager.ts`, `test/fake-provider.ts`, `test/sessions/manager.test.ts`

- [ ] **Step 1: Types**

In `src/core/types.ts`, add after `PromptResponse`:

```ts
/**
 * Where a chat may write for its coming turns: under `roots` but not under `except` (other lanes' checkouts nested
 * inside a root). `outside` explains a refused path, and may act first (e.g. join the lane to a new repo).
 */
export type WriteBoundary = { roots: string[]; except: string[]; outside(path: string): Promise<string> }
```

and add to `ProviderSession` after `answer`:

```ts
  /** Limits writes from the next turn on; undefined lifts the limit. Reads stay open. */
  setBoundary?(boundary: WriteBoundary | undefined): void
```

- [ ] **Step 2: Write the failing tests**

In `test/fake-provider.ts`:
- import `WriteBoundary` with the core types;
- add a field `boundaries: (WriteBoundary | undefined)[] = []` to `FakeSession`;
- add a method:

```ts
  setBoundary(boundary: WriteBoundary | undefined): void {
    this.boundaries.push(boundary)
  }
```

Add inside the `describe` block of `test/sessions/manager.test.ts`:

```ts
  it('lets one chat per lane run; the other waits and goes when the first ends', async () => {
    const { manager, sessions } = setup()
    const first = await manager.create('fake')
    const second = await manager.create('fake')
    await manager.setLane(first.id, 'x')
    await manager.setLane(second.id, 'x')
    await manager.prompt(first.id, text('one'))
    const events = watch(manager, second.id)
    await manager.prompt(second.id, text('two'))
    expect(manager.busyOn(['x']).map((record) => record.id)).toEqual([first.id])
    expect(events.some((event) => event.type === 'item' && event.item.kind === 'notice' && /x is busy/.test(event.item.text))).toBe(true)
    expect(sessions.length).toBe(1)
    sessions[0].emit({ kind: 'turn', id: 't1', state: 'ended' })
    await settle()
    await settle()
    expect(sessions[1].prompts).toEqual([text('two')])
  })

  it('passes the boundary to the provider before each prompt', async () => {
    const { provider, sessions } = fakeProvider()
    const boundary = { roots: ['/w/api'], except: [], outside: async () => 'no' }
    const manager = new SessionManager({
      providers: new Map([[provider.id, provider]]),
      store: new SessionStore(new MemoryMemento()),
      journalDir: mkdtempSync(join(tmpdir(), 'agentdeck-manager-')),
      cwd: '/work',
      env: async () => ({ PATH: '/bin' }),
      boundary: async (record) => (record.laneId ? boundary : undefined)
    })
    const { id } = await manager.create('fake')
    await manager.prompt(id, text('a'))
    sessions[0].emit({ kind: 'turn', id: 't1', state: 'ended' })
    await manager.setLane(id, 'x')
    await manager.prompt(id, text('b'))
    expect(sessions[0].boundaries).toEqual([undefined, boundary])
  })

  it('posts notices into a chat', async () => {
    const { manager } = setup()
    const { id } = await manager.create('fake')
    const events = watch(manager, id)
    manager.notify(id, 'moved')
    expect(events).toContainEqual({ type: 'item', item: { kind: 'notice', id: expect.any(String), level: 'info', text: 'moved' } })
  })
```

Run: `pnpm test test/sessions` → FAIL.

- [ ] **Step 3: Implement**

In `src/sessions/manager.ts`:
- import `WriteBoundary` with the core types;
- add to `SessionManagerDeps`:

```ts
  /** Where the chat may write for its next turn; asked before every prompt. */
  boundary?: (record: SessionRecord) => Promise<WriteBoundary | undefined>
```

- replace `prompt` with:

```ts
  async prompt(id: string, parts: PromptPart[]): Promise<void> {
    const live = this.load(id)
    const writer = this.laneWriter(live)
    if (live.status === 'running' || live.status === 'needs-input' || writer) {
      live.queue.push({ id: randomUUID(), parts })
      this.broadcast(live, { type: 'queue', queue: [...live.queue] })
      if (writer) this.notify(id, `Waiting: ${live.record.laneId} is busy in “${writer.record.title}”.`)
      return
    }
    await this.send(live, parts)
  }
```

- add after `lastReply`:

```ts
  /** Chats on these lanes in the middle of a turn. */
  busyOn(lanes: string[]): SessionRecord[] {
    return [...this.live.values()]
      .filter((live) => live.record.laneId !== undefined && lanes.includes(live.record.laneId) && isBusy(live.status))
      .map((live) => live.record)
  }

  notify(id: string, text: string, level: 'info' | 'warning' | 'error' = 'info'): void {
    this.upsert(this.load(id), { kind: 'notice', id: `notice:${randomUUID()}`, level, text })
  }
```

- add the private helpers after `turnEnded`:

```ts
  /** Another chat on the same lane that is mid-turn: one writer per lane. */
  private laneWriter(live: Live): Live | undefined {
    const lane = live.record.laneId
    if (!lane) return undefined
    return [...this.live.values()].find((other) => other !== live && other.record.laneId === lane && isBusy(other.status))
  }

  /** When a lane frees up, the next chat waiting on it goes. */
  private wakeLane(live: Live): void {
    const lane = live.record.laneId
    if (!lane) return
    const waiting = [...this.live.values()].find(
      (other) => other !== live && other.record.laneId === lane && !isBusy(other.status) && other.queue.length > 0
    )
    const next = waiting?.queue.shift()
    if (!waiting || !next) return
    this.broadcast(waiting, { type: 'queue', queue: [...waiting.queue] })
    void this.send(waiting, next.parts)
  }
```

- in `turnEnded`, change `if (!next) return` to:

```ts
    if (!next) {
      this.wakeLane(live)
      return
    }
```

- in `send`, after `const session = await this.connect(live)` add:

```ts
      if (this.deps.boundary) session.setBoundary?.(await this.deps.boundary(live.record).catch(() => undefined))
```

- add at module level, near the other helpers at the bottom of the file:

```ts
function isBusy(status: SessionStatus): boolean {
  return status === 'running' || status === 'needs-input'
}
```

Run: `pnpm test` → PASS.

- [ ] **Step 4: Commit**

```bash
git add src/core/types.ts src/sessions/manager.ts test/fake-provider.ts test/sessions/manager.test.ts
git commit -m "feat(sessions): one writer per lane, chat notices, and write boundaries"
```

---

### Task 4: Enforcement in the providers

**Files:**
- Create: `src/providers/boundary.ts`
- Modify: `src/providers/claude/provider.ts`, `src/providers/codex/provider.ts`, `src/providers/acp/provider.ts`
- Test: `test/providers/boundary.test.ts`

- [ ] **Step 1: Write the failing tests**

`test/providers/boundary.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { claudeWritePaths, switchesBranch, writable } from '../../src/providers/boundary'

const boundary = { roots: ['/w/api', '/w/.agentdeck/lanes/x'], except: ['/w/api/.worktrees/other'], outside: async () => '' }

describe('boundary', () => {
  it('allows writes under roots but not into other lanes nested inside them', () => {
    expect(writable(boundary, '/w/api/src/a.ts')).toBe(true)
    expect(writable(boundary, '/w/api')).toBe(true)
    expect(writable(boundary, '/w/.agentdeck/lanes/x/plan.md')).toBe(true)
    expect(writable(boundary, '/w/api/.worktrees/other/a.ts')).toBe(false)
    expect(writable(boundary, '/w/api-old/a.ts')).toBe(false)
    expect(writable(boundary, '/w/ui/a.ts')).toBe(false)
  })

  it('finds the paths Claude tools write, relative to the cwd', () => {
    expect(claudeWritePaths('Edit', { file_path: 'api/a.ts' }, '/w')).toEqual(['/w/api/a.ts'])
    expect(claudeWritePaths('Write', { file_path: '/w/b.ts' }, '/w')).toEqual(['/w/b.ts'])
    expect(claudeWritePaths('NotebookEdit', { notebook_path: '/w/n.ipynb' }, '/w')).toEqual(['/w/n.ipynb'])
    expect(claudeWritePaths('Read', { file_path: '/w/c.ts' }, '/w')).toEqual([])
  })

  it('spots branch switches but not file restores', () => {
    expect(switchesBranch('git checkout main')).toBe(true)
    expect(switchesBranch('cd api && git switch -c x')).toBe(true)
    expect(switchesBranch('git -C api checkout feat')).toBe(true)
    expect(switchesBranch('git checkout -- src/a.ts')).toBe(false)
    expect(switchesBranch('git status')).toBe(false)
  })
})
```

Run: `pnpm test test/providers/boundary.test.ts` → FAIL.

- [ ] **Step 2: The helpers**

`src/providers/boundary.ts`:

```ts
import { resolve, sep } from 'node:path'
import type { WriteBoundary } from '../core/types'

export const BRANCH_SWITCH =
  "Branch switches are AgentDeck's job (Move into Main, Move to Worktrees in the Sessions list). Keep working in this lane's paths."

const within = (paths: string[], path: string) => paths.some((root) => path === root || path.startsWith(root + sep))

export function writable(boundary: Pick<WriteBoundary, 'roots' | 'except'>, path: string): boolean {
  return within(boundary.roots, path) && !within(boundary.except, path)
}

const PATH_KEYS: Record<string, string> = { Edit: 'file_path', Write: 'file_path', MultiEdit: 'file_path', NotebookEdit: 'notebook_path' }

/** The files a Claude tool call writes, absolute. */
export function claudeWritePaths(toolName: string, input: Record<string, unknown>, cwd: string): string[] {
  const key = PATH_KEYS[toolName]
  const value = key ? input[key] : undefined
  return typeof value === 'string' ? [resolve(cwd, value)] : []
}

/** A shell command that switches branches; `git checkout -- <file>` (restoring files) is not one. */
export function switchesBranch(command: string): boolean {
  return /\bgit\s+(?:-C\s+\S+\s+)?(?:checkout|switch)\b(?!.*\s--\s)/.test(command)
}
```

Run: `pnpm test test/providers/boundary.test.ts` → PASS.

- [ ] **Step 3: Claude**

In `src/providers/claude/provider.ts`:
- add `HookInput, HookJSONOutput,` to the SDK type import; add `WriteBoundary` to the core type import; add `import { BRANCH_SWITCH, claudeWritePaths, switchesBranch, writable } from '../boundary'`;
- add a field after `holder`: `private boundary: WriteBoundary | undefined`;
- add to the `query({ options: { … } })` object, after `canUseTool`:

```ts
        // Hooks run in every permission mode, so lane boundaries hold in full access too.
        hooks: { PreToolUse: [{ hooks: [(input) => this.guard(input)] }] },
```

- add methods after `answer`:

```ts
  setBoundary(boundary: WriteBoundary | undefined): void {
    this.boundary = boundary
  }

  private async guard(input: HookInput): Promise<HookJSONOutput> {
    const boundary = this.boundary
    if (!boundary || input.hook_event_name !== 'PreToolUse') return {}
    const toolInput = (input.tool_input ?? {}) as Record<string, unknown>
    let reason: string | undefined
    if (input.tool_name === 'Bash' && typeof toolInput.command === 'string' && switchesBranch(toolInput.command)) reason = BRANCH_SWITCH
    for (const path of claudeWritePaths(input.tool_name, toolInput, this.options.cwd)) {
      if (!reason && !writable(boundary, path)) reason = await boundary.outside(path)
    }
    return reason ? { hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'deny', permissionDecisionReason: reason } } : {}
  }
```

- [ ] **Step 4: Codex**

In `src/providers/codex/provider.ts`:
- add `WriteBoundary` to the core type import;
- replace `sandboxPolicy` with:

```ts
function sandboxPolicy(mode: PermissionMode, cwd: string, boundary?: WriteBoundary): SandboxPolicy {
  // On a lane, writes stay inside the lane in every mode; full access keeps its network.
  if (boundary) {
    return { type: 'workspaceWrite', writableRoots: boundary.roots, networkAccess: mode === 'full-access', excludeTmpdirEnvVar: false, excludeSlashTmp: false }
  }
  return mode === 'full-access'
    ? { type: 'dangerFullAccess' }
    : { type: 'workspaceWrite', writableRoots: [cwd], networkAccess: false, excludeTmpdirEnvVar: false, excludeSlashTmp: false }
}
```

- add a field after `mode`: `private boundary: WriteBoundary | undefined`;
- in the `turn/start` request, change `sandboxPolicy: sandboxPolicy(this.mode, this.options.cwd),` to `sandboxPolicy: sandboxPolicy(this.mode, this.options.cwd, this.boundary),`;
- add a method after `answer`:

```ts
  setBoundary(boundary: WriteBoundary | undefined): void {
    this.boundary = boundary
  }
```

(Codex's sandbox cannot express `except`; a write into another lane's worktree nested in a root is not blocked for Codex. The brief's rules still tell it not to.)

- [ ] **Step 5: ACP**

In `src/providers/acp/provider.ts`:
- add `WriteBoundary` to the core type import; add `import { writable } from '../boundary'`;
- change `PermissionRequest` to:

```ts
type PermissionRequest = {
  toolCall: {
    toolCallId: string
    title?: string | null
    kind?: string | null
    locations?: { path: string }[] | null
    content?: { type: string; path?: string }[] | null
  }
  options: PermissionOption[]
}
```

- add a field after `mode`: `private boundary: WriteBoundary | undefined`, and a method after `answer`:

```ts
  setBoundary(boundary: WriteBoundary | undefined): void {
    this.boundary = boundary
  }
```

- add a constant near `selected`: `const WRITES = new Set(['edit', 'delete', 'move'])`;
- at the start of `permission`, before `const allow = …`, add:

```ts
    const outside = this.outsideBoundary(toolCall)
    if (outside) return outside
```

- add the method after `permission`:

```ts
  /** An edit outside the lane is refused without asking; the reason shows in the transcript. */
  private outsideBoundary(toolCall: PermissionRequest['toolCall']): Promise<unknown> | undefined {
    const boundary = this.boundary
    if (!boundary || !WRITES.has(toolCall.kind ?? '')) return undefined
    const paths = [
      ...(toolCall.locations ?? []).map((location) => location.path),
      ...(toolCall.content ?? []).flatMap((block) => (block.type === 'diff' && block.path ? [block.path] : []))
    ]
    const refused = paths.find((path) => !writable(boundary, path))
    if (!refused) return undefined
    return boundary.outside(refused).then((reason) => {
      this.items.fire({ kind: 'notice', id: `notice:${toolCall.toolCallId}`, level: 'warning', text: reason })
      return CANCELLED
    })
  }
```

- [ ] **Step 6: Verify and commit**

Run: `pnpm typecheck && pnpm test` → clean; PASS.

```bash
git add src/providers test/providers/boundary.test.ts
git commit -m "feat(providers): enforce lane write boundaries in Claude, Codex, and ACP agents"
```

---

### Task 5: The coordinator

**Files:**
- Create: `src/lanes/coordinator.ts`
- Test: `test/lanes/coordinator.test.ts`

- [ ] **Step 1: Write the failing tests**

`test/lanes/coordinator.test.ts`:

```ts
import { existsSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import type { PromptPart, SessionItem } from '../../src/core/types'
import { LaneCoordinator } from '../../src/lanes/coordinator'
import { LaneMemory } from '../../src/lanes/memory'
import { LaneTracker } from '../../src/lanes/tracker'
import { SessionManager } from '../../src/sessions/manager'
import { SessionStore } from '../../src/sessions/store'
import { fakeProvider } from '../fake-provider'
import { MemoryMemento } from '../memory-memento'
import { repo, run, workspace } from './repos'

let tracker: LaneTracker | undefined
afterEach(() => tracker?.dispose())
const text = (value: string): PromptPart[] => [{ type: 'text', text: value }]

async function setup() {
  const root = workspace()
  const api = repo(join(root, 'api'))
  const ui = repo(join(root, 'ui'))
  // Env files are ignored in real repos, so stashes leave them where they are.
  writeFileSync(join(api, '.gitignore'), '.env\n')
  run(api, 'add', '.gitignore')
  run(api, 'commit', '-q', '-m', 'ignore env')
  writeFileSync(join(api, '.env'), 'SECRET=1')
  const { provider, sessions } = fakeProvider()
  const manager = new SessionManager({
    providers: new Map([[provider.id, provider]]),
    store: new SessionStore(new MemoryMemento()),
    journalDir: mkdtempSync(join(tmpdir(), 'agentdeck-coord-')),
    cwd: root,
    env: async () => ({ PATH: process.env.PATH ?? '/bin' })
  })
  tracker = new LaneTracker(root)
  await tracker.refresh()
  const memory = new LaneMemory(tracker.root)
  const coordinator = new LaneCoordinator({ tracker, memory, manager, env: async () => process.env })
  return { root: tracker.root, api, ui, manager, sessions, memory, coordinator }
}

function notices(manager: SessionManager, id: string): string[] {
  const seen: string[] = []
  manager.subscribe(id, (event) => {
    const item = (event as { item?: SessionItem }).item
    if (item?.kind === 'notice') seen.push(item.text)
  })
  return seen
}

describe('LaneCoordinator', () => {
  it('creates a lane in worktrees, warmed up, with its goal', async () => {
    const { api, memory, coordinator } = await setup()
    await coordinator.newLane('x', ['api'], { worktrees: true, goal: 'Do x' })
    expect(run(join(api, '.worktrees', 'x'), 'branch', '--show-current').trim()).toBe('x')
    expect(existsSync(join(api, '.worktrees', 'x', '.env'))).toBe(true)
    expect(memory.goal('x')).toBe('Do x')
    expect(memory.worktrees('x')).toBe(true)
  })

  it('swaps a lane into main, tells its chats, and refuses while a chat on it runs', async () => {
    const { api, manager, sessions, coordinator } = await setup()
    await coordinator.newLane('a', ['api'], { worktrees: false })
    await coordinator.newLane('b', ['api'], { worktrees: true })
    const chat = await manager.create('fake')
    await manager.setLane(chat.id, 'a')
    const seen = notices(manager, chat.id)

    await manager.prompt(chat.id, text('work'))
    await expect(coordinator.moveIntoMain('b')).rejects.toThrow(/to finish its turn/)
    sessions[0].emit({ kind: 'turn', id: 't1', state: 'ended' })

    const lines = await coordinator.moveIntoMain('b')
    expect(lines).toEqual(['b took api/ main', 'a moved to api/.worktrees/a'])
    expect(run(api, 'branch', '--show-current').trim()).toBe('b')
    expect(seen).toContain('↪ b took api/ main · a moved to api/.worktrees/a')

    expect(await coordinator.moveToWorktree('b')).toEqual(['b moved to api/.worktrees/b'])
    expect(run(api, 'branch', '--show-current').trim()).toBe('main')
  })

  it('builds a boundary that redirects edits to the lane’s own checkout and joins new repos', async () => {
    const { root, api, ui, manager, coordinator } = await setup()
    await coordinator.newLane('x', ['api'], { worktrees: true })
    const chat = await manager.create('fake')
    await manager.setLane(chat.id, 'x')
    const record = manager.list()[0].record
    const boundary = await coordinator.boundary(record)
    expect(boundary?.roots).toEqual([join(api, '.worktrees', 'x'), join(root, '.agentdeck', 'lanes', 'x')])

    expect(await boundary?.outside(join(api, 'src', 'a.ts'))).toBe(
      `api/src/a.ts is outside lane x. Make this edit at api/.worktrees/x/src/a.ts instead.`
    )
    expect(await boundary?.outside(join(ui, 'b.ts'))).toBe('ui joined lane x at ui/.worktrees/x. Make this edit at ui/.worktrees/x/b.ts instead.')
    expect(run(join(ui, '.worktrees', 'x'), 'branch', '--show-current').trim()).toBe('x')
    expect(await coordinator.boundary({ ...record, laneId: undefined })).toBeUndefined()
  })
})
```

Run: `pnpm test test/lanes/coordinator.test.ts` → FAIL.

- [ ] **Step 2: Implement**

`src/lanes/coordinator.ts`:

```ts
import { join, relative, sep } from 'node:path'
import type { WriteBoundary } from '../core/types'
import type { SessionManager } from '../sessions/manager'
import type { SessionRecord } from '../sessions/store'
import { readConfig } from './config'
import { deriveLanes } from './lanes'
import type { LaneMemory } from './memory'
import type { RepoState } from './state'
import { joinRepo, moveIntoMain, moveToWorktree, SwitchError } from './switch'
import type { LaneTracker } from './tracker'
import { warmUp } from './warmup'

export type CoordinatorDeps = {
  tracker: LaneTracker
  memory: LaneMemory
  manager: SessionManager
  /** The environment setup commands run in (the user's login shell environment). */
  env: () => Promise<NodeJS.ProcessEnv>
}

const inside = (root: string, path: string) => path === root || path.startsWith(root + sep)

/** Moves lanes on request and draws each chat's write boundary. Agents never call it; the app does. */
export class LaneCoordinator {
  constructor(private readonly deps: CoordinatorDeps) {}

  /** Creates a lane in the given repos, in worktrees (warmed up) or in the main checkouts. */
  async newLane(name: string, repoNames: string[], options: { worktrees: boolean; goal?: string }): Promise<void> {
    const { tracker, memory } = this.deps
    memory.ensure(name)
    memory.setWorktrees(name, options.worktrees)
    if (options.goal) memory.setGoal(name, options.goal)
    await tracker.refresh()
    for (const repo of tracker.repos.filter((candidate) => repoNames.includes(candidate.name))) {
      const path = await joinRepo(repo, name, options.worktrees)
      if (path !== repo.path) await this.warm(repo, name, path)
    }
    await tracker.refresh()
  }

  /** Brings the lane into the main checkout of every repo it is in; lanes there move to worktrees and are warmed up. */
  async moveIntoMain(lane: string): Promise<string[]> {
    const { tracker } = this.deps
    await tracker.refresh()
    const repos = this.reposOf(lane)
    if (repos.length === 0) throw new SwitchError(`${lane} has no checkout to move.`)
    const holders = repos.flatMap((repo) => {
      const branch = repo.checkouts.find((checkout) => checkout.main)?.branch
      return branch && branch !== repo.base && branch !== lane ? [branch] : []
    })
    this.assertIdle([lane, ...holders])
    const lines: string[] = []
    for (const repo of repos) {
      const result = await moveIntoMain(repo, lane)
      lines.push(`${lane} took ${repo.name}/ main`)
      if (result.movedOut && result.worktree) {
        lines.push(`${result.movedOut} moved to ${this.rel(result.worktree)}`)
        void this.warm(repo, result.movedOut, result.worktree)
      }
    }
    await this.settle([lane, ...holders], lines)
    return lines
  }

  /** Moves the lane out of every main checkout it holds; main goes back to base. */
  async moveToWorktree(lane: string): Promise<string[]> {
    const { tracker } = this.deps
    await tracker.refresh()
    const repos = tracker.repos.filter((repo) => repo.checkouts.some((checkout) => checkout.main && checkout.branch === lane))
    if (repos.length === 0) throw new SwitchError(`${lane} holds no main checkout.`)
    this.assertIdle([lane])
    const lines: string[] = []
    for (const repo of repos) {
      const path = await moveToWorktree(repo, lane)
      lines.push(`${lane} moved to ${this.rel(path)}`)
      void this.warm(repo, lane, path)
    }
    await this.settle([lane], lines)
    return lines
  }

  /** Where a chat on a lane may write: the lane's checkouts and its memory folder. */
  async boundary(record: SessionRecord): Promise<WriteBoundary | undefined> {
    const name = record.laneId
    if (!name) return undefined
    const { tracker, memory } = this.deps
    const lane = deriveLanes(tracker.repos, [name]).find((candidate) => candidate.name === name)
    if (!lane) return undefined
    const roots = [...lane.repos.map((repo) => repo.path), memory.laneDir(name)]
    const except = tracker.repos
      .flatMap((repo) => repo.checkouts.map((checkout) => checkout.path))
      .filter((path) => !roots.includes(path) && roots.some((root) => inside(root, path)))
    return { roots, except, outside: (path) => this.redirect(name, path) }
  }

  /** Explains a refused write: same file in the lane's own checkout, or join the repo first. */
  private async redirect(lane: string, path: string): Promise<string> {
    const { tracker, memory } = this.deps
    const repo = [...tracker.repos].sort((a, b) => b.path.length - a.path.length).find((candidate) => inside(candidate.path, path))
    const checkout = repo?.checkouts
      .filter((candidate) => inside(candidate.path, path))
      .sort((a, b) => b.path.length - a.path.length)[0]
    if (!repo || !checkout) return `${this.rel(path)} is outside lane ${lane} and every repo AgentDeck tracks. Edit only inside the lane's paths.`
    const within = relative(checkout.path, path)
    const own = repo.checkouts.find((candidate) => candidate.branch === lane)
    if (own) return `${this.rel(path)} is outside lane ${lane}. Make this edit at ${this.rel(join(own.path, within))} instead.`
    const worktrees = memory.worktrees(lane) ?? readConfig(tracker.root).worktrees
    try {
      const joined = await joinRepo(repo, lane, worktrees)
      if (joined !== repo.path) void this.warm(repo, lane, joined)
      await this.settle([lane], [`${lane} joined ${repo.name}`])
      return `${repo.name} joined lane ${lane} at ${this.rel(joined)}. Make this edit at ${this.rel(join(joined, within))} instead.`
    } catch (error) {
      return `${this.rel(path)} is outside lane ${lane}, and ${repo.name} could not join it: ${(error as Error).message}`
    }
  }

  private async warm(repo: RepoState, lane: string, path: string): Promise<void> {
    const { tracker, memory, manager } = this.deps
    const config = readConfig(tracker.root)
    const main = repo.checkouts.find((checkout) => checkout.main)?.path ?? repo.path
    const result = await warmUp(main, path, config.envFiles, config.setup[repo.name], await this.deps.env())
    memory.appendHistory(lane, { event: 'warmed', repo: repo.name, copied: result.copied, ok: result.setup?.ok ?? true })
    if (result.setup && !result.setup.ok) {
      for (const record of this.chatsOn([lane])) {
        manager.notify(record.id, `Warm-up of ${lane} in ${repo.name} failed: ${result.setup.command}\n${result.setup.output}`, 'warning')
      }
    }
  }

  private reposOf(lane: string): RepoState[] {
    return this.deps.tracker.repos.filter((repo) => repo.checkouts.some((checkout) => checkout.branch === lane))
  }

  private assertIdle(lanes: string[]): void {
    const busy = this.deps.manager.busyOn(lanes)
    if (busy.length > 0) {
      throw new SwitchError(`Waiting for ${busy.map((record) => `“${record.title}”`).join(', ')} to finish its turn. Try again then, or stop it.`)
    }
  }

  private chatsOn(lanes: string[]): SessionRecord[] {
    return this.deps.manager
      .list()
      .map(({ record }) => record)
      .filter((record) => record.laneId !== undefined && lanes.includes(record.laneId))
  }

  /** After a move: re-read Git, record history, and tell every affected chat in one line. */
  private async settle(lanes: string[], lines: string[]): Promise<void> {
    await this.deps.tracker.refresh()
    for (const lane of lanes) this.deps.memory.appendHistory(lane, { event: 'switched', lines })
    for (const record of this.chatsOn(lanes)) this.deps.manager.notify(record.id, `↪ ${lines.join(' · ')}`)
  }

  private rel(path: string): string {
    return relative(this.deps.tracker.root, path) || '.'
  }
}
```

Run: `pnpm test test/lanes` → PASS.

- [ ] **Step 3: Commit**

```bash
git add src/lanes/coordinator.ts test/lanes/coordinator.test.ts
git commit -m "feat(lanes): coordinator for switches, warm-up, new lanes, and write boundaries"
```

---

### Task 6: Commands

**Files:**
- Modify: `src/extension.ts`, `package.json`

- [ ] **Step 1: Wiring**

In `src/extension.ts`:
- import `LaneCoordinator` from `./lanes/coordinator`;
- declare `let coordinator: LaneCoordinator | undefined` right before `manager = new SessionManager(…)`, and add to its deps: `boundary: async (record) => coordinator?.boundary(record),`;
- after `const sessionManager = manager`, add:

```ts
  coordinator =
    tracker && memory
      ? new LaneCoordinator({ tracker, memory, manager: sessionManager, env: async () => (await getEnv()) as NodeJS.ProcessEnv })
      : undefined
  const lanes = coordinator
```

  (if `Env`'s type is not assignable to `NodeJS.ProcessEnv`, map it with `Object.fromEntries(Object.entries(await getEnv()))`; report which you used);
- add to the main `push(…)` list:

```ts
    vscode.commands.registerCommand('agentdeck.newLane', async () => {
      if (!lanes || !tracker) return void vscode.window.showInformationMessage('Open a folder to use lanes.')
      const name = await vscode.window.showInputBox({
        prompt: 'Lane name (the branch name)',
        validateInput: (value) => (/^[\w][\w./-]*$/.test(value.trim()) ? undefined : 'Letters, digits, and . _ / - only')
      })
      if (!name?.trim()) return
      const goal = await vscode.window.showInputBox({ prompt: `Goal for ${name.trim()} (optional)` })
      const repos = await vscode.window.showQuickPick(
        tracker.repos.map((repo) => ({ label: repo.name })),
        { canPickMany: true, placeHolder: 'Repos the lane starts in' }
      )
      if (!repos || repos.length === 0) return
      const where = await vscode.window.showQuickPick(
        [
          { label: 'Worktrees', description: 'Separate checkouts, warmed up; main stays as it is', worktrees: true },
          { label: 'Main checkout', description: 'Work where the code runs (main must be free)', worktrees: false }
        ],
        { placeHolder: 'Where does the lane start?' }
      )
      if (!where) return
      await runLane(`Creating ${name.trim()}…`, () =>
        lanes.newLane(name.trim(), repos.map((repo) => repo.label), { worktrees: where.worktrees, goal: goal?.trim() || undefined })
      )
    }),
    vscode.commands.registerCommand('agentdeck.laneIntoMain', (node: LaneNode) =>
      lanes ? runLane(`Moving ${node.lane.name} into main…`, () => lanes.moveIntoMain(node.lane.name)) : undefined
    ),
    vscode.commands.registerCommand('agentdeck.laneToWorktree', (node: LaneNode) =>
      lanes ? runLane(`Moving ${node.lane.name} to worktrees…`, () => lanes.moveToWorktree(node.lane.name)) : undefined
    ),
```

- add at the bottom of the file:

```ts
/** Runs a lane operation with progress; failures (busy chats, stash conflicts) show their message. */
async function runLane(title: string, operation: () => Promise<unknown>): Promise<void> {
  try {
    await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title }, operation)
  } catch (error) {
    void vscode.window.showErrorMessage((error as Error).message)
  }
}
```

In `package.json`, following the existing entries' style:
- `contributes.commands`: `agentdeck.newLane` "New Lane…" (icon `$(git-branch)`), `agentdeck.laneIntoMain` "Move into Main", `agentdeck.laneToWorktree` "Move to Worktrees", each with `"category": "AgentDeck"`;
- `menus.view/title`: `{ "command": "agentdeck.newLane", "when": "view == agentdeck.sessions", "group": "navigation@1" }`;
- `menus.view/item/context`, for `viewItem == lane` in `view == agentdeck.sessions`: `agentdeck.laneIntoMain` at `"3_move@1"`, `agentdeck.laneToWorktree` at `"3_move@2"`;
- `menus.commandPalette`: `laneIntoMain` and `laneToWorktree` with `"when": "false"` (`newLane` stays in the palette).

- [ ] **Step 2: Verify and commit**

Run: `pnpm typecheck && pnpm test && pnpm build` → clean; PASS; built.

```bash
git add src/extension.ts package.json
git commit -m "feat(lanes): New Lane, Move into Main, and Move to Worktrees"
```

---

### Task 7: Live check and hand-off

**Files:**
- Create: `scripts/smoke-boundary.ts`
- Modify: `esbuild.mjs`

- [ ] **Step 1: The script**

`scripts/smoke-boundary.ts`:

```ts
// Live check: an agent on a lane in a worktree is asked to write into the main checkout; the write must not land there.
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, realpathSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { captureEnv } from '../src/env'
import { LaneCoordinator } from '../src/lanes/coordinator'
import { laneContext } from '../src/lanes/lane-context'
import { LaneMemory } from '../src/lanes/memory'
import { LaneTracker } from '../src/lanes/tracker'
import { providers } from '../src/providers/registry'
import { SessionManager } from '../src/sessions/manager'
import { SessionStore } from '../src/sessions/store'
import { MemoryMemento } from '../test/memory-memento'

const TIMEOUT_MS = 240_000
const git = (cwd: string, ...args: string[]) => execFileSync('git', args, { cwd, stdio: 'ignore' })

async function main(): Promise<void> {
  const providerId = process.argv[2] ?? 'claude'
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'agentdeck-boundary-')))
  const api = join(root, 'api')
  mkdirSync(api)
  git(api, 'init', '-q', '-b', 'main')
  git(api, 'config', 'user.email', 'smoke@example.com')
  git(api, 'config', 'user.name', 'Smoke')
  writeFileSync(join(api, 'README.md'), '# api\n')
  git(api, 'add', '.')
  git(api, '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'init')

  const tracker = new LaneTracker(root)
  const memory = new LaneMemory(tracker.root)
  const env = await captureEnv()
  let coordinator: LaneCoordinator | undefined
  const manager = new SessionManager({
    providers,
    store: new SessionStore(new MemoryMemento()),
    journalDir: join(root, '.journal'),
    cwd: root,
    env: async () => env,
    decorate: laneContext(tracker, memory),
    boundary: async (record) => coordinator?.boundary(record)
  })
  coordinator = new LaneCoordinator({ tracker, memory, manager, env: async () => process.env })
  await coordinator.newLane('hello', ['api'], { worktrees: true, goal: 'Add hello.txt' })
  const { id } = await manager.create(providerId, 'full-access')
  await manager.setLane(id, 'hello')

  const target = join(api, 'hello.txt')
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('turn timed out')), TIMEOUT_MS)
    const subscription = manager.subscribe(id, (event) => {
      if (event.type !== 'item') return
      const item = event.item
      if (item.kind === 'notice') console.log(`notice (${item.level}):`, item.text.split('\n')[0])
      if (item.kind === 'approval' && item.resolved === undefined) manager.answer(id, item.id, { kind: 'option', optionId: 'allow' })
      if (item.kind === 'turn' && item.state === 'ended') {
        clearTimeout(timer)
        subscription.dispose()
        resolve()
      }
    })
    void manager.prompt(id, [{ type: 'text', text: `Create the file ${target} containing the word hi. Use your file editing tool.` }])
  })
  const inMain = existsSync(target)
  const inLane = existsSync(join(api, '.worktrees', 'hello', 'hello.txt'))
  console.log(`main checkout has hello.txt: ${inMain} · lane worktree has hello.txt: ${inLane}`)
  await manager.dispose()
  tracker.dispose()
  if (inMain) throw new Error('the write landed in the main checkout')
  console.log('BOUNDARY SMOKE OK')
}

main().catch((error) => {
  console.error('BOUNDARY SMOKE FAILED:', error)
  process.exit(1)
})
```

In `esbuild.mjs`, add `'smoke-boundary': 'scripts/smoke-boundary.ts'` to the extension build's `entryPoints`.

- [ ] **Step 2: Run it**

Run: `pnpm typecheck && pnpm build && node dist/smoke-boundary.js claude && node dist/smoke-boundary.js codex && node dist/smoke-boundary.js grok`
Expected for each: `main checkout has hello.txt: false`, then `BOUNDARY SMOKE OK`. Whether the lane worktree got the file depends on the agent following the redirect; report it (`true` is expected for Claude). A `true` for the main checkout is a failure: report the full output.

- [ ] **Step 3: Package, docs, commit**

Run: `pnpm test && pnpm run package` → PASS; packaged.

In `docs/superpowers/plans/2026-10-28-mvp-overview.md`, add after the plan 19 row:

```
| 20 | [Switch, warm-up, and lane boundaries](2026-10-29-20-switch-and-warm-up.md) | Move lanes into and out of main with their work, warm-up, joining repos, one writer per lane, write boundaries in every provider | Done |
```

In `docs/roadmap.md`, make the line starting `- **20 — Switch and warm-up:**` end with ` ✓ done.`

```bash
git add scripts/smoke-boundary.ts esbuild.mjs docs
git commit -m "test: live lane boundary check; plan 20 done"
```
