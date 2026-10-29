import type { Quota, SessionItem } from '../../src/core/types'
import type { QueuedPrompt, SessionEvent } from '../../src/sessions/manager'
import type { SessionRecord, SessionStatus } from '../../src/sessions/store'
import type { EditorContext, HostMessage, LaneInfo, ProviderInfo, SessionSummary, SignInProgress } from '../../src/ui/protocol'

export type ChatState = {
  sessionId?: string
  record?: SessionRecord
  status: SessionStatus
  items: SessionItem[]
  queue: QueuedPrompt[]
  facts: SessionRecord['facts']
  provider?: ProviderInfo
  providers: ProviderInfo[]
  editorContext: EditorContext | null
  sessions: SessionSummary[]
  /** Lanes for the lane chip; undefined when lanes are unavailable (no folder). */
  lanes?: LaneInfo[]
  quotas: Record<string, Quota>
  signIns: Record<string, SignInProgress>
  attachmentsUri?: string
  /** The sidebar has no session to show. */
  empty: boolean
}

export const initialState: ChatState = {
  status: 'idle',
  items: [],
  queue: [],
  facts: {},
  providers: [],
  editorContext: null,
  sessions: [],
  quotas: {},
  signIns: {},
  empty: false
}

export function reduce(state: ChatState, message: HostMessage): ChatState {
  switch (message.type) {
    case 'providers':
      return { ...state, providers: message.providers }
    case 'provider':
      return { ...state, provider: message.provider }
    case 'assets':
      return { ...state, attachmentsUri: message.attachments }
    case 'reply':
    case 'insertAttachments':
    case 'editPrompt':
      return state
    case 'editorContext':
      return { ...state, editorContext: message.context }
    case 'empty':
      return { ...initialState, provider: state.provider, providers: state.providers, editorContext: state.editorContext, sessions: state.sessions, lanes: state.lanes, quotas: state.quotas, signIns: state.signIns, empty: true }
    case 'title':
      if (message.sessionId !== state.sessionId || !state.record) return state
      return { ...state, record: { ...state.record, title: message.title } }
    case 'sessions':
      return { ...state, sessions: message.sessions }
    case 'lanes':
      return { ...state, lanes: message.lanes }
    case 'lane': {
      if (message.sessionId !== state.sessionId || !state.record) return state
      const { laneId: _previous, ...record } = state.record
      return { ...state, record: message.laneId ? { ...record, laneId: message.laneId } : record }
    }
    case 'quota':
      return { ...state, quotas: { ...state.quotas, [message.providerId]: message.quota } }
    case 'signInProgress': {
      const signIns = { ...state.signIns }
      if (message.progress) signIns[message.providerId] = message.progress
      else delete signIns[message.providerId]
      return { ...state, signIns }
    }
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
