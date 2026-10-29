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
