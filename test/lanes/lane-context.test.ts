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
