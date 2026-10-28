import type { SessionItem } from '../../src/core/types'
import type { QueuedPrompt, SessionEvent } from '../../src/sessions/manager'
import type { SessionRecord, SessionStatus } from '../../src/sessions/store'
import type { EditorContext, HostMessage, ProviderInfo, SessionSummary } from '../../src/ui/protocol'

export type ChatState = {
  sessionId?: string
  record?: SessionRecord
  status: SessionStatus
  items: SessionItem[]
  queue: QueuedPrompt[]
  facts: SessionRecord['facts']
  provider?: ProviderInfo
  editorContext: EditorContext | null
  sessions: SessionSummary[]
  /** The sidebar has no session to show. */
  empty: boolean
}

export const initialState: ChatState = {
  status: 'idle',
  items: [],
  queue: [],
  facts: {},
  editorContext: null,
  sessions: [],
  empty: false
}

export function reduce(state: ChatState, message: HostMessage): ChatState {
  switch (message.type) {
    case 'provider':
      return { ...state, provider: message.provider }
    case 'editorContext':
      return { ...state, editorContext: message.context }
    case 'empty':
      return { ...initialState, provider: state.provider, editorContext: state.editorContext, sessions: state.sessions, empty: true }
    case 'title':
      if (message.sessionId !== state.sessionId || !state.record) return state
      return { ...state, record: { ...state.record, title: message.title } }
    case 'sessions':
      return { ...state, sessions: message.sessions }
    case 'session':
      return sessionEvent(state, message.sessionId, message.event)
  }
}

function sessionEvent(state: ChatState, sessionId: string, event: SessionEvent): ChatState {
  if (event.type === 'snapshot') {
    return {
      ...state,
      empty: false,
      sessionId,
      record: event.record,
      status: event.status,
      items: event.items,
      queue: event.queue,
      facts: event.record.facts
    }
  }
  if (sessionId !== state.sessionId) return state
  switch (event.type) {
    case 'item':
      return { ...state, items: upsert(state.items, event.item) }
    case 'fact':
      return { ...state, facts: { ...state.facts, [event.fact.kind]: event.fact } }
    case 'status':
      return { ...state, status: event.status }
    case 'queue':
      return { ...state, queue: event.queue }
  }
}

function upsert(items: SessionItem[], item: SessionItem): SessionItem[] {
  const index = items.findIndex((existing) => existing.id === item.id)
  if (index === -1) return [...items, item]
  const next = items.slice()
  next[index] = item
  return next
}
