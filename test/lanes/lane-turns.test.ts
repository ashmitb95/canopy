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
