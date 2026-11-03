import type { SessionItem } from '../../src/core/types'
import type { SessionRecord } from '../../src/sessions/store'
import type { GroupState, TimelineItem } from '../../src/group/chat'
import type { HostMessage, ProviderInfo } from '../../src/ui/protocol'

const record: SessionRecord = {
  id: 's1',
  providerId: 'claude',
  title: 'Fix flaky retry test',
  createdAt: '2026-10-28T10:00:00.000Z',
  updatedAt: '2026-10-28T10:04:00.000Z',
  mode: 'ask',
  hasTurns: true,
  laneId: 'retry-fix',
  facts: {
    model: { kind: 'model', current: 'opus', available: [{ id: 'opus', label: 'Opus 5.5' }, { id: 'sonnet', label: 'Sonnet 5.5' }] },
    effort: { kind: 'effort', current: 'high', available: ['low', 'medium', 'high', 'xhigh'] },
    mode: { kind: 'mode', current: 'ask', available: ['ask', 'accept-edits', 'plan', 'full-access'] },
    context: { kind: 'context', usedTokens: 76_000, maxTokens: 200_000 },
    mcp: {
      kind: 'mcp',
      servers: [
        { name: 'screenscribe', status: 'connected', scope: 'user', tools: ['analyze_video', 'extract_frames'] },
        { name: 'claude.ai Notion', status: 'needs-auth', scope: 'claudeai', tools: [] },
        { name: 'linear', status: 'failed', scope: 'project', tools: [], error: 'Connection refused' }
      ]
    }
  }
}

const items: SessionItem[] = [
  {
    kind: 'message',
    id: 'u1',
    role: 'user',
    parts: [
      { type: 'text', text: 'The retry test in api.test.ts fails about one run in five. Find out why and fix it.' },
      { type: 'file', path: '/work/src/api.test.ts', range: [40, 72] }
    ]
  },
  { kind: 'turn', id: 't1', state: 'started' },
  {
    kind: 'thought',
    id: 'th1',
    text: 'The failure rate suggests a timing race rather than a logic bug. The test uses fake timers, so the order of advanceTimersByTime against the retry scheduling matters.',
    streaming: false
  },
  { kind: 'tool', id: 'tool1', title: 'Read /work/src/retry.ts', toolKind: 'read', status: 'done', paths: ['/work/src/retry.ts'] },
  { kind: 'tool', id: 'tool2', title: 'Grep advanceTimersByTime', toolKind: 'search', status: 'done' },
  {
    kind: 'tool',
    id: 'tool3',
    title: 'Bash pnpm vitest run api.test.ts',
    toolKind: 'execute',
    status: 'failed',
    output: '✓ api.test.ts > parses response (3ms)\n× api.test.ts > retries with backoff'
  },
  {
    kind: 'plan',
    id: 'plan',
    entries: [
      { text: 'Find why the retry test is flaky', status: 'done' },
      { text: 'Schedule the backoff synchronously', status: 'in_progress' },
      { text: 'Run the test 20 times', status: 'pending' }
    ]
  },
  {
    kind: 'message',
    id: 'a1',
    role: 'assistant',
    streaming: false,
    text: "Found it. The test advances the clock before `retry()` has scheduled its backoff, so the timer sometimes fires after the assertion.\n\nI'll schedule the delay synchronously:\n\n```ts\nawait sleep(delay)\nreturn attempt(n + 1)\n```"
  },
  {
    kind: 'diff',
    id: 'tool4:diff',
    path: '/work/src/retry.ts',
    oldText: 'setTimeout(() => attempt(n + 1), delay)',
    newText: 'await sleep(delay)\nreturn attempt(n + 1)'
  },
  { kind: 'tool', id: 'tool5', title: 'Read /work/src/sleep.ts', toolKind: 'read', status: 'done', paths: ['/work/src/sleep.ts'] },
  { kind: 'tool', id: 'tool6', title: 'Read /work/src/api.ts', toolKind: 'read', status: 'done', paths: ['/work/src/api.ts'] },
  {
    kind: 'message',
    id: 'm-math',
    role: 'assistant',
    streaming: false,
    text: 'The backoff grows as $$d_n = d_0 \\cdot 2^n$$ and the flow is:\n\n```mermaid\ngraph LR\n  A[request] --> B{ok?}\n  B -- no --> C[wait d_n]\n  C --> A\n```'
  },
  {
    kind: 'approval',
    id: 'approval:1',
    title: 'Allow Claude to run this command?',
    detail: 'pnpm vitest run api.test.ts --repeat 20',
    options: [
      { id: 'allow', label: 'Allow once' },
      { id: 'always', label: 'Always allow' },
      { id: 'deny', label: 'Deny' }
    ]
  }
]

const earlier: SessionItem[] = [
  { kind: 'message', id: 'u0', role: 'user', parts: [
      { type: 'command', name: 'review' },
      { type: 'text', text: 'Add a retry helper with exponential backoff.' },
      { type: 'pasted', text: Array.from({ length: 48 }, (_, line) => `log line ${line + 1}`).join('\n') }
    ]
  },
  { kind: 'turn', id: 't0', state: 'ended', stopReason: 'success', at: '2026-10-28T09:58:00.000Z' },
  {
    kind: 'message',
    id: 'a0',
    role: 'assistant',
    streaming: false,
    text: 'Added `retry()` in `src/retry.ts` with exponential backoff, capped at 3 attempts.'
  },
  { kind: 'diff', id: 'd0', path: '/work/src/retry.ts', oldText: null, newText: 'export async function retry() {\n  // …\n}' }
]

const claude: ProviderInfo = {
  id: 'claude',
  label: 'Claude',
  installUrl: 'https://example.invalid',
  capabilities: ['steer', 'effort'],
  modes: ['ask', 'accept-edits', 'plan', 'full-access'],
  state: { status: 'signed-in', account: 'me@example.com', version: '2.1.311' }
}
const codex: ProviderInfo = { ...claude, id: 'codex', label: 'Codex', state: { status: 'signed-out', version: '0.164.0' } }
const grokInfo: ProviderInfo = { ...claude, id: 'grok', label: 'Grok', state: { status: 'not-installed' } }
const providers: HostMessage = { type: 'providers', providers: [claude, codex, grokInfo] }

const chat: HostMessage[] = [
  providers,
  { type: 'assets', attachments: 'about:blank' },
  {
    type: 'quota',
    providerId: 'claude',
    quota: {
      observedAt: new Date(Date.now() - 3 * 60_000).toISOString(),
      windows: [
        { label: '5-hour', usedPercent: 42, resetsAt: new Date(Date.now() + 2 * 3_600_000).toISOString(), status: 'ok' },
        { label: 'Weekly', usedPercent: 18, status: 'ok' }
      ]
    }
  },
  {
    type: 'sessions',
    sessions: [
      { id: 's1', title: 'Fix flaky retry test', providerId: 'claude', status: 'needs-input', updatedAt: '2026-10-28T10:04:00.000Z', inTab: false, laneId: 'retry-fix' },
      { id: 's2', title: 'Refactor auth middleware', providerId: 'claude', status: 'idle', updatedAt: '2026-10-28T09:00:00.000Z', inTab: true },
      { id: 's3', title: 'Token rotation', providerId: 'codex', status: 'idle', updatedAt: '2026-10-28T08:00:00.000Z', inTab: false, laneId: 'auth-refresh' }
    ]
  },
  { type: 'lanes', lanes: [{ name: 'retry-fix', where: 'api main ●2 · ui worktree' }, { name: 'auth-refresh', where: 'ui worktree' }] },
  { type: 'provider', provider: claude },
  { type: 'editorContext', context: { path: '/work/src/api.test.ts', label: 'src/api.test.ts', range: [40, 72] } },
  {
    type: 'session',
    sessionId: 's1',
    event: {
      type: 'snapshot',
      record,
      status: 'needs-input',
      items: [...earlier, ...items],
      queue: [{ id: 'q1', parts: [{ type: 'text', text: 'Also add a regression test that runs the retry with real timers.' }] }]
    }
  }
]

const prompts: SessionItem[] = [
  { kind: 'message', id: 'pu1', role: 'user', parts: [{ type: 'text', text: 'Plan the retry fix.' }] },
  {
    kind: 'approval',
    id: 'approval:plan',
    title: 'Ready to code?',
    subject: {
      kind: 'plan',
      text: '1. Schedule the backoff with `await sleep(delay)`.\n2. Add a regression test with real timers.\n3. Run the suite 20 times.',
      filePath: '/work/.claude/plans/retry.md'
    },
    options: [
      { id: 'approve:ask', label: 'Approve · Ask before edits' },
      { id: 'approve:accept-edits', label: 'Approve · Accept edits' },
      { id: 'approve:auto', label: 'Approve · Auto' },
      { id: 'keep-planning', label: 'Keep planning' }
    ]
  },
  {
    kind: 'question',
    id: 'question:1',
    questions: [
      {
        id: 'q1',
        header: 'Backoff',
        question: 'Which backoff should the retry use?',
        multiSelect: false,
        allowOther: true,
        options: [
          { id: 'o1', label: 'Exponential', description: '100ms, 200ms, 400ms…' },
          { id: 'o2', label: 'Fixed', description: '250ms every time' }
        ]
      },
      { id: 'q2', question: 'Which suites should run?', multiSelect: true, allowOther: true, options: [{ id: 'o1', label: 'api' }, { id: 'o2', label: 'ui' }] }
    ]
  }
]

const groupState: GroupState = {
  id: 'g1',
  title: 'Export timeouts',
  lead: 'claude',
  target: 'claude',
  running: 'codex',
  queue: [{ id: 'q1', target: 'grok', text: 'review it' }],
  members: [
    { agent: 'claude', status: 'idle', activity: '' },
    { agent: 'codex', status: 'running', activity: '$ node --test' },
    { agent: 'grok', status: 'idle', activity: '' }
  ],
  roster: { plan: 'claude', implement: 'codex', review: 'grok' },
  delegations: [
    {
      id: 'd1',
      lead: 'claude',
      agent: 'codex',
      role: 'implement',
      task: 'Stream invoice rows and fix retries',
      doneWhen: 'the 50,000-row test passes',
      status: 'running'
    }
  ],
  violations: [{ id: 'v1', agent: 'grok', files: ['A\tnotes.txt'], before: [] }],
  userQuestions: [{ id: 'uq1', from: 'codex', question: 'Exports over 1 million rows could take minutes. Block them, or warn and continue?' }],
  quotas: {}
}
const groupItems: TimelineItem[] = [
  { agent: 'claude', item: { kind: 'message', id: 'gu1', role: 'user', parts: [{ type: 'text', text: 'Exports time out on large invoices. Keep the CSV format.' }] } },
  { agent: 'claude', item: { kind: 'message', id: 'ga1', role: 'assistant', text: 'export.ts loads every row into memory. I will stream rows instead, and hand the build to Codex.', streaming: false } },
  { agent: 'codex', item: { kind: 'message', id: 'gc0', role: 'user', parts: [{ type: 'text', text: 'You are codex, delegated this by claude in a group chat run by AgentDeck, in the implement role.\nTask: Stream invoice rows and fix retries' }] } },
  { agent: 'codex', item: { kind: 'message', id: 'gc1', role: 'assistant', text: 'Reading export.ts first.', streaming: false } },
  { agent: 'codex', item: { kind: 'tool', id: 'gt1', title: 'Run cat export.ts queue.ts', toolKind: 'execute', status: 'done', output: 'export const limit = 10' } },
  { agent: 'codex', item: { kind: 'message', id: 'gc2', role: 'assistant', text: 'Found that retries append to the partial file; fixing that too.', streaming: false } },
  { agent: 'codex', item: { kind: 'tool', id: 'gt2', title: 'Run node --test', toolKind: 'execute', status: 'running' } }
]

// `?scenario=new` shows the provider chooser instead of a chat.
const scenario = new URLSearchParams(location.search).get('scenario')
const messages: HostMessage[] =
  scenario === 'new'
    ? [
        providers,
        { type: 'signInProgress', providerId: 'codex', progress: { step: 'link', url: 'https://auth.openai.com/oauth/authorize?x=1' } },
        { type: 'empty' }
      ]
    : scenario === 'lanes'
      ? [
          {
            type: 'laneCards',
            lanes: [
              { name: 'export-timeouts', repos: [{ repo: 'api', location: 'worktree', dirty: 1, slot: 'wt-1' }, { repo: 'ui', location: 'worktree', dirty: 0, slot: 'wt-1' }], chats: [{ kind: 'group', id: 'g1', title: 'Export timeouts', agents: ['claude', 'codex', 'grok'], state: 'codex: $ node --test', needsYou: false }] },
              { name: 'auth-flow', repos: [{ repo: 'api', location: 'primary', dirty: 2 }], chats: [{ kind: 'session', id: 's9', title: 'Sign-in screens', agents: ['claude'], state: 'Idle', needsYou: false }] },
              { name: 'billing-export', repos: [{ repo: 'api', location: 'worktree', dirty: 0, slot: 'wt-2' }], chats: [{ kind: 'group', id: 'g2', title: 'Billing CSV', agents: ['grok', 'claude'], state: 'Needs you', needsYou: true }] },
              { name: 'retry-fix', repos: [], chats: [{ kind: 'session', id: 's3', title: 'Retry backoff', agents: ['codex'], state: 'Idle', needsYou: false }] }
            ]
          }
        ]
    : scenario === 'side'
      ? [
          {
            type: 'side',
            side: {
              lanes: [
                { name: 'auth-flow', where: 'api primary ●2', primary: true, warm: false, dirty: 2 },
                { name: 'export-timeouts', where: 'api worktree ●1', primary: false, warm: true, dirty: 1 },
                { name: 'billing-export', where: 'api worktree', primary: false, warm: true, dirty: 0 }
              ],
              groups: [
                { id: 'g1', title: 'Export timeouts', lead: 'claude', running: 'codex', activity: '$ node --test', needsYou: false, agents: ['claude', 'codex', 'grok'], laneId: 'export-timeouts' },
                { id: 'g2', title: 'Billing CSV', lead: 'grok', needsYou: true, agents: ['grok', 'claude'], laneId: 'billing-export' }
              ],
              sessions: [{ id: 's9', title: 'Sign-in screens', providerId: 'claude', status: 'idle', updatedAt: '2026-10-28T08:00:00.000Z', inTab: false, unread: true, laneId: 'auth-flow' }]
            }
          }
        ]
    : scenario === 'group'
      ? [providers, { type: 'groupSnapshot', state: groupState, items: groupItems }]
    : scenario === 'prompts'
      ? [
          providers,
          { type: 'provider', provider: claude },
          { type: 'session', sessionId: 's1', event: { type: 'snapshot', record, status: 'needs-input', items: prompts, queue: [] } }
        ]
      : chat

// Posted after the app has mounted and subscribed.
setTimeout(() => {
  for (const message of messages) window.postMessage(message, '*')
}, 100)
