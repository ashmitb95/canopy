import { describe, expect, it } from 'vitest'
import { groupByProvider, groupSessions } from '../../src/lanes/group'
import { deriveLanes, laneDescription, laneForPath, laneFromPaths } from '../../src/lanes/lanes'
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

describe('groupByProvider', () => {
  it('groups by provider in the given order, then by the lanes each provider has chats on', () => {
    const sessions = [
      { id: 's1', provider: 'Codex', laneId: 'retry-fix' },
      { id: 's2', provider: 'Claude' },
      { id: 's3', provider: 'Codex' },
      { id: 's4', provider: 'Muse' }
    ]
    const lanes = deriveLanes(repos, ['retry-fix'])
    expect(groupByProvider(lanes, sessions, ['Claude', 'Codex'])).toEqual([
      { provider: 'Claude', lanes: [], loose: [sessions[1]] },
      { provider: 'Codex', lanes: [{ lane: lanes[1], sessions: [sessions[0]] }], loose: [sessions[2]] },
      { provider: 'Muse', lanes: [], loose: [sessions[3]] }
    ])
  })
})

describe('laneDescription', () => {
  it('says where the lane lives in each repo, with uncommitted files', () => {
    expect(laneDescription(deriveLanes(repos).find((lane) => lane.name === 'retry-fix') ?? { name: '', repos: [] })).toBe(
      'api main ●2 · ui worktree ●1'
    )
    expect(laneDescription({ name: 'p', repos: [] })).toBe('no checkout')
  })
})
