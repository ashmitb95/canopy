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
