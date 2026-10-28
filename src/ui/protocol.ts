import type { Capability, PermissionMode, ProviderState } from '../core/types'
import type { SessionEvent } from '../sessions/manager'
import type { SessionStatus } from '../sessions/store'

export type EditorContext = { path: string; label: string; range?: [number, number] }

export type ProviderInfo = {
  id: string
  label: string
  installUrl: string
  capabilities: Capability[]
  modes: readonly PermissionMode[]
  state: ProviderState
}

export type SessionSummary = { id: string; title: string; providerId: string; status: SessionStatus; updatedAt: string }

/** Extension host → webview. */
export type HostMessage =
  | { type: 'session'; sessionId: string; event: SessionEvent }
  | { type: 'title'; sessionId: string; title: string }
  | { type: 'provider'; provider: ProviderInfo }
  /** Every provider with its install and sign-in state, for the chooser. */
  | { type: 'providers'; providers: ProviderInfo[] }
  | { type: 'editorContext'; context: EditorContext | null }
  /** Recent sessions, for the sidebar's session switcher. */
  | { type: 'sessions'; sessions: SessionSummary[] }
  /** The sidebar has no session yet. */
  | { type: 'empty' }

/** Webview → extension host. */
export type WebviewMessage =
  | { type: 'ready' }
  | { type: 'prompt'; text: string; includeContext: boolean }
  | { type: 'cancel' }
  | { type: 'answer'; itemId: string; optionId: string }
  | { type: 'removeQueued'; queuedId: string }
  | { type: 'newChat'; providerId?: string }
  | { type: 'signIn'; providerId?: string }
  | { type: 'openFile'; path: string; line?: number }
  | { type: 'setModel'; model: string }
  | { type: 'setMode'; mode: PermissionMode }
  | { type: 'refreshMcp' }
  | { type: 'reconnectMcp'; server: string }
  | { type: 'mcpSignIn'; server: string; scope?: string }
  | { type: 'openDiff'; itemId: string }
  | { type: 'switchSession'; sessionId: string }
