import type { SessionItem } from '../../src/core/types'
import type { SessionRecord } from '../../src/sessions/store'
import type { HostMessage, ProviderInfo } from '../../src/ui/protocol'

const record: SessionRecord = {
  id: 's1',
  providerId: 'claude',
  title: 'Fix flaky retry test',
  createdAt: '2026-10-28T10:00:00.000Z',
  updatedAt: '2026-10-28T10:04:00.000Z',
  mode: 'ask',
  hasTurns: true,
  facts: {
    model: { kind: 'model', current: 'opus', available: [{ id: 'opus', label: 'Opus 5.5' }, { id: 'sonnet', label: 'Sonnet 5.5' }] },
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
  { kind: 'message', id: 'u0', role: 'user', parts: [{ type: 'text', text: 'Add a retry helper with exponential backoff.' }] },
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
  capabilities: [],
  modes: ['ask', 'accept-edits', 'plan', 'full-access'],
  state: { status: 'signed-in', account: 'me@example.com', version: '2.1.311' }
}
const codex: ProviderInfo = { ...claude, id: 'codex', label: 'Codex', state: { status: 'signed-out', version: '0.164.0' } }
const grokInfo: ProviderInfo = { ...claude, id: 'grok', label: 'Grok', state: { status: 'not-installed' } }
const providers: HostMessage = { type: 'providers', providers: [claude, codex, grokInfo] }

const chat: HostMessage[] = [
  providers,
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
      { id: 's1', title: 'Fix flaky retry test', providerId: 'claude', status: 'needs-input', updatedAt: '2026-10-28T10:04:00.000Z', inTab: false },
      { id: 's2', title: 'Refactor auth middleware', providerId: 'claude', status: 'idle', updatedAt: '2026-10-28T09:00:00.000Z', inTab: true }
    ]
  },
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

// `?scenario=new` shows the provider chooser instead of a chat.
const messages: HostMessage[] = new URLSearchParams(location.search).get('scenario') === 'new'
    ? [
        providers,
        { type: 'signInProgress', providerId: 'codex', progress: { step: 'link', url: 'https://auth.openai.com/oauth/authorize?x=1' } },
        { type: 'empty' }
      ]
    : chat

// Posted after the app has mounted and subscribed.
setTimeout(() => {
  for (const message of messages) window.postMessage(message, '*')
}, 100)
