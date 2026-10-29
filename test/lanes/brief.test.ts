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
