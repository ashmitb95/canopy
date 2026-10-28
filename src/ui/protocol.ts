import type { Capability, PermissionMode, ProviderState, Quota } from '../core/types'
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

export type SessionSummary = { id: string; title: string; providerId: string; status: SessionStatus; updatedAt: string; inTab: boolean }

/** Where a sign-in flow is; `null` clears it. */
export type SignInProgress =
  | { step: 'starting' }
  | { step: 'link'; url: string; code?: string }
  | { step: 'failed'; message: string }

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
  | { type: 'quota'; providerId: string; quota: Quota }
  /** The sidebar has no session yet. */
  | { type: 'empty' }
  | { type: 'signInProgress'; providerId: string; progress: SignInProgress | null }

/** Webview → extension host. */
export type WebviewMessage =
  | { type: 'ready' }
  | { type: 'prompt'; text: string; includeContext: boolean }
  | { type: 'cancel' }
  | { type: 'answer'; itemId: string; optionId: string }
  | { type: 'removeQueued'; queuedId: string }
  | { type: 'newChat'; providerId?: string }
  | { type: 'signIn'; providerId?: string }
  | { type: 'cancelSignIn'; providerId: string }
  | { type: 'signInInTerminal'; providerId: string }
  | { type: 'refreshProviders' }
  | { type: 'openFile'; path: string; line?: number }
  | { type: 'setModel'; model: string }
  | { type: 'setMode'; mode: PermissionMode }
  | { type: 'refreshMcp' }
  | { type: 'reconnectMcp'; server: string }
  | { type: 'mcpSignIn'; server: string; scope?: string }
  | { type: 'openDiff'; itemId: string }
  | { type: 'switchSession'; sessionId: string }
  | { type: 'reviewChanges'; itemIds: string[] }
  | { type: 'openSession'; sessionId: string }
