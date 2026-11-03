import type { Capability, PermissionMode, PromptPart, PromptResponse, ProviderState, Quota } from '../core/types'
import type { GroupState, TimelineItem } from '../group/chat'
import type { SessionItem } from '../core/types'
import type { SessionEvent } from '../sessions/manager'
import type { SessionStatus } from '../sessions/store'

export type EditorContext = { path: string; label: string; range?: [number, number] }

export type FileMatch = { path: string; label: string }

export type Attachment = { kind: 'image'; path: string; mimeType: string; name: string } | { kind: 'file'; path: string; label: string }

export type ProviderInfo = {
  id: string
  label: string
  installUrl: string
  capabilities: Capability[]
  modes: readonly PermissionMode[]
  state: ProviderState
}

export type LaneInfo = { name: string; where: string }

/** The primary sidebar: lanes, group chats, and single-agent sessions. */
export type SideData = {
  lanes?: { name: string; where: string; primary: boolean; warm: boolean; dirty: number }[]
  groups: { id: string; title: string; lead: string; running?: string; activity?: string; needsYou: boolean; agents: string[]; laneId?: string }[]
  sessions: SessionSummary[]
}

/** The full lane view: every lane, where each repo has it, and the chats working on it. */
export type LaneCard = {
  name: string
  repos: { repo: string; location: 'primary' | 'worktree'; dirty: number; slot?: string }[]
  chats: { kind: 'group' | 'session'; id: string; title: string; agents: string[]; state: string; needsYou: boolean }[]
}

export type SessionSummary = {
  id: string
  title: string
  providerId: string
  status: SessionStatus
  updatedAt: string
  inTab: boolean
  unread?: boolean
  laneId?: string
}

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
  | { type: 'palette'; palette: string }
  /** Recent sessions, for the sidebar's session switcher. */
  | { type: 'sessions'; sessions: SessionSummary[] }
  | { type: 'quota'; providerId: string; quota: Quota }
  /** Lanes for the chat's lane chip; sent only when a folder is open. */
  | { type: 'lanes'; lanes: LaneInfo[] }
  /** The lane a chat is on. */
  | { type: 'lane'; sessionId: string; laneId?: string }
  /** The sidebar has no session yet. */
  | { type: 'empty' }
  | { type: 'signInProgress'; providerId: string; progress: SignInProgress | null }
  /** The answer to a webview request with the same requestId. */
  | { type: 'reply'; requestId: number; value: unknown }
  /** Webview URI of the attachment store, for showing attached images. */
  | { type: 'assets'; attachments: string }
  /** Files to put into the composer, from *Add to AgentDeck Chat*. */
  | { type: 'insertAttachments'; attachments: Attachment[] }
  /** A rewound message to edit and resend. */
  | { type: 'editPrompt'; parts: PromptPart[] }
  /** A group chat: everything so far, then live state and items. */
  | { type: 'groupSnapshot'; state: GroupState; items: TimelineItem[] }
  | { type: 'groupState'; state: GroupState }
  | { type: 'groupItem'; agent: string; item: SessionItem }
  | { type: 'side'; side: SideData }
  | { type: 'laneCards'; lanes: LaneCard[] }

/** Webview → extension host. */
export type WebviewMessage =
  | { type: 'ready' }
  | { type: 'prompt'; parts: PromptPart[]; includeContext: boolean }
  | { type: 'searchFiles'; requestId: number; query: string }
  | { type: 'pickAttachments'; requestId: number }
  | { type: 'saveImage'; requestId: number; name: string; mimeType: string; data: string }
  | { type: 'cancel' }
  | { type: 'rewind'; itemId: string }
  | { type: 'answer'; itemId: string; response: PromptResponse }
  | { type: 'removeQueued'; queuedId: string }
  | { type: 'newChat'; providerId?: string }
  | { type: 'signIn'; providerId?: string }
  | { type: 'cancelSignIn'; providerId: string }
  | { type: 'signInInTerminal'; providerId: string }
  | { type: 'refreshProviders' }
  | { type: 'openFile'; path: string; line?: number }
  | { type: 'setModel'; model: string }
  | { type: 'setMode'; mode: PermissionMode }
  | { type: 'setEffort'; effort: string }
  | { type: 'steer'; queuedId: string }
  | { type: 'compact' }
  | { type: 'refreshMcp' }
  | { type: 'reconnectMcp'; server: string }
  | { type: 'mcpSignIn'; server: string; scope?: string }
  | { type: 'openDiff'; itemId: string }
  | { type: 'switchSession'; sessionId: string }
  | { type: 'reviewChanges'; itemIds: string[] }
  | { type: 'openSession'; sessionId: string }
  | { type: 'setLane'; laneId?: string }
  | { type: 'newLane' }
  | { type: 'handOff' }
  | { type: 'forkSession' }
  | { type: 'renameSession'; sessionId?: string }
  | { type: 'deleteSession'; sessionId?: string }
  | { type: 'reviewLane'; laneId: string }
  | { type: 'groupSend'; text: string }
  | { type: 'openGroup'; groupId: string }
  | { type: 'newGroupChat' }
  | { type: 'switchLane'; laneId: string }
  | { type: 'parkLane'; laneId: string }
  | { type: 'openLanes' }
  | { type: 'groupAnswer'; agent: string; itemId: string; response: PromptResponse }
  | { type: 'answerQuestion'; id: string; text: string }
  | { type: 'stopAndSend'; queuedId: string }
  | { type: 'cancelQueued'; queuedId: string }
  | { type: 'groupStop' }
  | { type: 'groupRetry' }
  | { type: 'undoViolation'; id: string }
  | { type: 'undoDelegation'; id: string }
