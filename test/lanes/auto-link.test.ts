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
    journalDir: mkdtempSync(join(tmpdir(), 'canopy-link-')),
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
