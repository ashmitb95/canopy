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

  it('notices a branch switch made outside Canopy', async () => {
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
