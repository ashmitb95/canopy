// The scripted chat for the project page: Claude researches and plans, Codex builds it in two phases, Grok reviews.
import type { SessionItem } from '../../src/core/types'
import type { Delegation, GroupState } from '../../src/group/chat'
import type { HostMessage } from '../../src/ui/protocol'

type Step = [number, HostMessage]

const ask = 'Search buries documents edited this week (ENG-482). Rank recent edits higher, without breaking the existing filters.'
const plan = 'Rank recent edits higher: a recency boost in ranker.ts, then a test and the docs.'
const context =
  'Findings: ranker.ts scores by text match only; updatedAt is indexed but never read. Filters run before scoring, so a boost cannot change which documents match. Plan: phase 1 adds a recency boost that decays over 7 days, capped at 1.5x. Phase 2 adds a test that a 2-day-old document outranks an older equal match, and documents the boost.'

export function showcaseSteps(): Step[] {
  const started = () => new Date(Date.now() - 2000).toISOString()
  const base: GroupState = {
    id: 'showcase',
    title: 'Rank recent edits higher',
    lead: 'claude',
    target: 'claude',
    active: [],
    queue: [],
    members: [
      { agent: 'claude', status: 'idle', activity: '' },
      { agent: 'codex', status: 'idle', activity: '', mode: 'accept-edits', modes: ['ask', 'accept-edits', 'full-access'] },
      { agent: 'grok', status: 'idle', activity: '' }
    ],
    roster: { plan: 'claude', research: 'claude', implement: 'codex', review: 'grok' },
    delegating: true,
    delegations: [],
    violations: [],
    userQuestions: [],
    quotas: {},
    laneId: 'search-recency'
  }
  const phase = (n: 1 | 2): Delegation => ({
    id: `p${n}`,
    lead: 'claude',
    agent: 'codex',
    role: 'implement',
    series: 'plan',
    phase: n,
    phases: 2,
    task: n === 1 ? 'Add a recency boost to the ranker' : 'Test the boost and document it',
    doneWhen: n === 1 ? 'Recent documents score higher and the search tests pass.' : 'A test covers the boost and the docs describe it.',
    context,
    status: 'planned',
    added: ['1 message from the chat, word for word', 'The search-recency lane: goal, plan, and notes', ...(n === 2 ? ["Phase 1's report and changed files"] : [])]
  })
  const review: Delegation = {
    id: 'rv',
    lead: 'claude',
    agent: 'grok',
    role: 'review',
    task: 'Review the recency boost against the plan',
    doneWhen: '',
    context: 'What changed: ranker.ts gains a recency boost, with a test and docs. Check it against the plan, and that filters still run before scoring.',
    status: 'planned',
    added: ['The plan and both phase reports']
  }
  const facts1 = { files: ['M\tsearch/ranker.ts', 'M\tsearch/score.ts'], commands: [{ command: 'pnpm test search', failed: false }], verify: { command: 'pnpm test', ok: true, output: '214 passed' }, violations: [] }
  const facts2 = { files: ['A\tsearch/ranker.test.ts', 'M\tdocs/search.md'], commands: [{ command: 'pnpm test search', failed: false }], verify: { command: 'pnpm test', ok: true, output: '216 passed' }, violations: [] }
  const report1 = 'Done. ranker.ts multiplies the match score by a recency boost: 1.5x today, falling to 1x after 7 days. Filters are untouched.\nSTATUS: done'
  const report2 = 'Done. A 2-day-old document now outranks an older equal match, and docs/search.md explains the boost.\nSTATUS: done'
  const report3 = 'Matches the plan. Filters still run before scoring, and the boost is capped. One note: the 7 days could be a setting later.\nSTATUS: done'

  const steps: Step[] = []
  const at = (t: number, message: HostMessage) => steps.push([t, message])
  const item = (t: number, agent: string, value: SessionItem, delegation?: string) => {
    at(t, { type: 'groupItem', agent, item: value, ...(delegation ? { delegation } : {}) })
  }
  const said = (t: number, agent: string, id: string, text: string, delegation?: string, streaming = false) => item(t, agent, { kind: 'message', id, role: 'assistant', text, streaming }, delegation)
  const tool = (t: number, agent: string, id: string, title: string, toolKind: string, status: 'running' | 'done', delegation?: string, output?: string) =>
    item(t, agent, { kind: 'tool', id, title, toolKind, status, ...(output ? { output } : {}) } as SessionItem, delegation)
  const handoff = (t: number, agent: string, id: string, delegation: string) => item(t, agent, { kind: 'message', id, role: 'user', parts: [{ type: 'text', text: `You are ${agent}, delegated this by claude in a group chat run by Canopy.` }] }, delegation)
  const members = (working: string, activity: string) => base.members.map((member) => (member.agent === working ? { ...member, status: 'running' as const, activity } : member))
  const state = (t: number, working: string | undefined, activity: string, delegations: Delegation[]) =>
    at(t, { type: 'groupState', state: { ...base, delegations, ...(working ? { running: working, active: [working], members: members(working, activity) } : {}) } })

  at(0, { type: 'groupSnapshot', state: base, items: [] })
  item(300, 'claude', { kind: 'message', id: 'u1', role: 'user', parts: [{ type: 'text', text: ask }] })

  // Claude researches, then plans.
  state(700, 'claude', 'read ranker.ts', [])
  tool(800, 'claude', 'l-t1', 'Read search/ranker.ts', 'read', 'done')
  tool(1200, 'claude', 'l-t2', 'Grep updatedAt', 'search', 'done')
  tool(1500, 'claude', 'l-t3', 'Read search/ranker.test.ts', 'read', 'done')
  said(1900, 'claude', 'l-m1', 'ranker.ts scores by text match only.', undefined, true)
  said(2500, 'claude', 'l-m1', `ranker.ts scores by text match only. \`updatedAt\` is indexed but never read, and filters run before scoring, so a boost can't change what matches.\n\n${plan} Implement belongs to Codex, so I'm handing it over in two phases with the plan.`)

  // Phase 1.
  const p1 = phase(1)
  const p2 = phase(2)
  const s1 = started()
  state(3300, 'codex', 'read ranker.ts', [{ ...p1, status: 'running', startedAt: s1 }, p2])
  handoff(3300, 'codex', 'c-h1', 'p1')
  said(3700, 'codex', 'c-m1', 'Starting from the plan: the boost goes in ranker.ts, scoring only.', 'p1')
  tool(4100, 'codex', 'c-t1', 'Read search/ranker.ts', 'read', 'done', 'p1')
  tool(4400, 'codex', 'c-t2', 'Read search/score.ts', 'read', 'done', 'p1')
  state(4800, 'codex', 'edit ranker.ts', [{ ...p1, status: 'running', startedAt: s1 }, p2])
  tool(4800, 'codex', 'c-t3', 'Edit search/ranker.ts', 'edit', 'done', 'p1')
  tool(5200, 'codex', 'c-t4', 'Edit search/score.ts', 'edit', 'done', 'p1')
  state(5600, 'codex', '$ pnpm test search', [{ ...p1, status: 'running', startedAt: s1 }, p2])
  tool(5600, 'codex', 'c-t5', 'Run pnpm test search', 'execute', 'running', 'p1')
  tool(6500, 'codex', 'c-t5', 'Run pnpm test search', 'execute', 'done', 'p1', 'Test Files  12 passed (12)\n     Tests  214 passed (214)')
  said(6800, 'codex', 'c-m2', report1, 'p1')
  const done1: Delegation = { ...p1, status: 'done', startedAt: s1, report: report1, facts: facts1, handoff: '/handoff-1.md', snapshots: [] }

  // Phase 2 starts from phase 1's report, and asks once before running a command.
  const s2 = started()
  state(7400, 'codex', 'read ranker.test.ts', [done1, { ...p2, status: 'running', startedAt: s2 }])
  handoff(7400, 'codex', 'c-h2', 'p2')
  said(7800, 'codex', 'c-m3', "Phase 1's boost is in. Adding the test next.", 'p2')
  tool(8200, 'codex', 'c-t6', 'Read search/ranker.test.ts', 'read', 'done', 'p2')
  tool(8600, 'codex', 'c-t7', 'Edit search/ranker.test.ts', 'edit', 'done', 'p2')
  const approval = (resolved?: string): SessionItem => ({
    kind: 'approval',
    id: 'c-a1',
    title: 'Allow Codex to run this command?',
    detail: 'pnpm test search --update-snapshots',
    options: [
      { id: 'allow', label: 'Allow once' },
      { id: 'allowForSession', label: 'Allow for this session' },
      { id: 'deny', label: 'Deny' }
    ],
    ...(resolved ? { resolved } : {})
  })
  item(9100, 'codex', approval(), 'p2')
  item(11000, 'codex', approval('allowForSession'), 'p2')
  state(11000, 'codex', '$ pnpm test search', [done1, { ...p2, status: 'running', startedAt: s2 }])
  tool(11100, 'codex', 'c-t8', 'Run pnpm test search --update-snapshots', 'execute', 'running', 'p2')
  tool(12000, 'codex', 'c-t8', 'Run pnpm test search --update-snapshots', 'execute', 'done', 'p2', 'Test Files  13 passed (13)\n     Tests  216 passed (216)')
  tool(12300, 'codex', 'c-t9', 'Edit docs/search.md', 'edit', 'done', 'p2')
  said(12700, 'codex', 'c-m4', report2, 'p2')
  const done2: Delegation = { ...p2, status: 'done', startedAt: s2, report: report2, facts: facts2, handoff: '/handoff-2.md', snapshots: [] }

  // Grok reviews, read-only.
  const s3 = started()
  state(13300, 'grok', 'read the diff', [done1, done2, { ...review, status: 'running', startedAt: s3 }])
  handoff(13300, 'grok', 'g-h1', 'rv')
  said(13700, 'grok', 'g-m1', 'Checking the change against the plan.', 'rv')
  tool(14100, 'grok', 'g-t1', 'Run git diff main -- search/ docs/', 'execute', 'done', 'rv', '4 files changed, 61 insertions(+), 6 deletions(-)')
  tool(14600, 'grok', 'g-t2', 'Read search/ranker.ts', 'read', 'done', 'rv')
  said(15200, 'grok', 'g-m2', report3, 'rv')
  const done3: Delegation = { ...review, status: 'done', startedAt: s3, report: report3, facts: { files: [], commands: [{ command: 'git diff main -- search/ docs/', failed: false }], violations: [] }, handoff: '/handoff-3.md', snapshots: [] }

  // Claude reports what really happened.
  state(15800, 'claude', 'Writing', [done1, done2, done3])
  said(16000, 'claude', 'l-m2', 'Both phases are in and checked.', undefined, true)
  said(16600, 'claude', 'l-m2', 'Both phases are in and checked: 4 files changed, and Canopy\'s own test run passed with 216 tests. Grok found no problems; it suggests making the 7-day window a setting later. Filters behave as before.')
  state(17000, undefined, '', [done1, done2, done3])
  return steps
}
