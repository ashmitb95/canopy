import type { Capability, PermissionMode, ProviderState } from '../core/types'
import type { SessionEvent } from '../sessions/manager'

export type EditorContext = { path: string; label: string; range?: [number, number] }

export type ProviderInfo = {
  id: string
  label: string
  installUrl: string
  capabilities: Capability[]
  modes: readonly PermissionMode[]
  state: ProviderState
}

/** Extension host → webview. */
export type HostMessage =
  | { type: 'session'; sessionId: string; event: SessionEvent }
  | { type: 'title'; sessionId: string; title: string }
  | { type: 'provider'; provider: ProviderInfo }
  | { type: 'editorContext'; context: EditorContext | null }
  /** The sidebar has no session yet. */
  | { type: 'empty' }

/** Webview → extension host. */
export type WebviewMessage =
  | { type: 'ready' }
  | { type: 'prompt'; text: string; includeContext: boolean }
  | { type: 'cancel' }
  | { type: 'answer'; itemId: string; optionId: string }
  | { type: 'removeQueued'; queuedId: string }
  | { type: 'newChat' }
  | { type: 'signIn' }
  | { type: 'openFile'; path: string; line?: number }
