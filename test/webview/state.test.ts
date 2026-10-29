import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import type { SessionEvent } from '../../src/sessions/manager'
import type { SessionRecord } from '../../src/sessions/store'
import type { HostMessage } from '../../src/ui/protocol'
import { type ChatState, initialState, reduce } from '../../webview/app/state'

const record: SessionRecord = {
  id: 's1',
  providerId: 'claude',
  title: 'Chat',
  createdAt: 't',
  updatedAt: 't',
  mode: 'ask',
  hasTurns: false,
  facts: {}
}
const reply = (id: string, text: string): SessionItem => ({ kind: 'message', id, role: 'assistant', text, streaming: false })
const session = (event: SessionEvent, sessionId = 's1'): HostMessage => ({ type: 'session', sessionId, event })
const snapshot = (items: SessionItem[] = [], sessionId = 's1'): HostMessage =>
  session({ type: 'snapshot', record: { ...record, id: sessionId }, status: 'idle', items, queue: [] }, sessionId)
const run = (...messages: HostMessage[]): ChatState => messages.reduce(reduce, initialState)

describe('chat state', () => {
  it('loads a snapshot', () => {
    const state = run(snapshot([reply('a', 'hi')]))
    expect(state).toMatchObject({ sessionId: 's1', record, status: 'idle', items: [reply('a', 'hi')], empty: false })
  })

  it('upserts items in place and appends new ones', () => {
    const state = run(
      snapshot([reply('a', 'h')]),
      session({ type: 'item', item: reply('b', 'x') }),
      session({ type: 'item', item: reply('a', 'hello') })
    )
    expect(state.items).toEqual([reply('a', 'hello'), reply('b', 'x')])
  })

  it('ignores events for a session it is not showing', () => {
    const state = run(snapshot(), session({ type: 'item', item: reply('a', 'x') }, 'other'))
    expect(state.items).toEqual([])
  })

  it('switches sessions on a new snapshot', () => {
    const state = run(snapshot([reply('a', 'x')]), snapshot([], 's2'))
    expect(state).toMatchObject({ sessionId: 's2', items: [] })
  })

  it('tracks status, queue, and facts', () => {
    const state = run(
      snapshot(),
      session({ type: 'status', status: 'running' }),
      session({ type: 'queue', queue: [{ id: 'q', parts: [{ type: 'text', text: 'next' }] }] }),
      session({ type: 'fact', fact: { kind: 'context', usedTokens: 10, maxTokens: 100 } })
    )
    expect(state.status).toBe('running')
    expect(state.queue).toHaveLength(1)
    expect(state.facts.context).toEqual({ kind: 'context', usedTokens: 10, maxTokens: 100 })
  })

  it('renames the session it is showing', () => {
    const state = run(
      snapshot(),
      { type: 'title', sessionId: 's1', title: 'Fix login' },
      { type: 'title', sessionId: 'other', title: 'Nope' }
    )
    expect(state.record?.title).toBe('Fix login')
  })

  it('keeps provider and editor context across an empty sidebar', () => {
    const provider = {
      id: 'claude',
      label: 'Claude',
      installUrl: 'u',
      capabilities: [],
      modes: ['ask' as const],
      state: { status: 'signed-in' as const }
    }
    const state = run(
      { type: 'provider', provider },
      { type: 'editorContext', context: { path: '/w/a.ts', label: 'a.ts' } },
      snapshot([reply('a', 'x')]),
      { type: 'empty' }
    )
    expect(state).toMatchObject({ empty: true, items: [], provider, editorContext: { path: '/w/a.ts' } })
    expect(state.sessionId).toBeUndefined()
  })

  it('keeps the provider list for the chooser, also across an empty surface', () => {
    const providers = [
      {
        id: 'codex',
        label: 'Codex',
        installUrl: 'u',
        capabilities: [],
        modes: ['ask' as const],
        state: { status: 'signed-out' as const }
      }
    ]
    const state = run({ type: 'providers', providers }, { type: 'empty' })
    expect(state.providers).toEqual(providers)
  })

  it('keeps the session list for the switcher', () => {
    const sessions = [{ id: 's1', title: 'Chat', providerId: 'claude', status: 'idle' as const, updatedAt: 't', inTab: false }]
    expect(run({ type: 'sessions', sessions }).sessions).toEqual(sessions)
  })

  it('keeps the latest quota per provider, also across an empty surface', () => {
    const quota = { observedAt: 't', windows: [{ label: '5-hour', usedPercent: 40, status: 'ok' as const }] }
    const state = run({ type: 'quota', providerId: 'claude', quota }, { type: 'empty' })
    expect(state.quotas).toEqual({ claude: quota })
  })

  it('tracks sign-in progress per provider and clears it when done', () => {
    const started = run({ type: 'signInProgress', providerId: 'claude', progress: { step: 'link', url: 'https://claude.ai/x' } })
    expect(started.signIns.claude).toEqual({ step: 'link', url: 'https://claude.ai/x' })
    expect(reduce(started, { type: 'signInProgress', providerId: 'claude', progress: null }).signIns).toEqual({})
  })

  it('keeps the lane list and the lane of the chat it shows', () => {
    let state = reduce(initialState, { type: 'session', sessionId: 's1', event: { type: 'snapshot', record, status: 'idle', items: [], queue: [] } })
    state = reduce(state, { type: 'lanes', lanes: [{ name: 'x', where: 'api main' }] })
    state = reduce(state, { type: 'lane', sessionId: 's1', laneId: 'x' })
    expect(state.lanes).toEqual([{ name: 'x', where: 'api main' }])
    expect(state.record?.laneId).toBe('x')
    state = reduce(state, { type: 'lane', sessionId: 'other', laneId: 'y' })
    expect(state.record?.laneId).toBe('x')
    state = reduce(state, { type: 'lane', sessionId: 's1' })
    expect(state.record?.laneId).toBeUndefined()
  })
})
