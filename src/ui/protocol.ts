import type { Capability, PermissionMode, PromptPart, PromptResponse, ProviderState, Quota } from '../core/types'
import type { GroupState, TimelineItem } from '../group/chat'
import type { IssueRef } from '../integrations/issues'
import type { SessionItem } from '../core/types'
import type { SessionEvent } from '../sessions/manager'
import type { SessionRecord, SessionStatus } from '../sessions/store'

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

/** The full lane view: the primary checkout, lanes with a worktree (warm), and lanes that are only a branch (cold). */
export type LaneCard = {
  name: string
  goal?: string
  place: 'primary' | 'warm' | 'cold'
  /** Worktree folders, relative to the workspace. */
  paths: string[]
  dirty: number
  chats: number
  /** The chat to show on the card: one that needs you, else one working, else the latest. */
  status?: { agent: string; text: string; tone: 'needs' | 'working' | 'done' | 'idle' }
  /** For the primary checkout: files changed from the base branch, which chats on other lanes are told about. */
  shared?: { path: string; added: number; removed: number }[]
}

/** The setup page: agents, who does what, the workspace, and issue trackers. */
export type SetupData = {
  agents: { id: string; label: string; status: ProviderState['status']; account?: string; version?: string; installUrl: string }[]
  roster: { lead: string; research: string; implement: string; review: string; enforce: boolean; verify: string; questionsTo: 'lead' | 'user' }
  workspace?: { name: string; maxSlots: number; worktrees: boolean; envFiles: string[]; repos: { name: string; base?: string; setup?: string; envFiles: string[] }[] }
  github: 'signed-in' | 'signed-out' | 'missing'
  linear: boolean
  palette: string
}

/** The review screen for one group chat: who did what, with what Canopy recorded and each delegate's diff. */
export type ReviewData = {
  title: string
  laneId?: string
  inPrimary: boolean
  delegations: {
    id: string
    agent: string
    role?: string
    task: string
    status: string
    report?: string
    verify?: { command: string; ok: boolean }
    violations: string[]
    commands: number
    failedCommands: number
    undone: boolean
    handoff: boolean
    files: { path: string; added: number; removed: number; lines: string[] }[]
  }[]
}

/** The New Worktree form. */
export type NewLaneData = {
  repos: string[]
  agents: { id: string; label: string; ready: boolean }[]
  roster: { lead: string; research: string; implement: string; review: string }
  issues: IssueRef[]
  notes: string[]
}

/** What the group chat's composer shows: the session of the agent the next message goes to. */
export type GroupComposer = { agent: string; sessionId: string; provider: ProviderInfo; facts: SessionRecord['facts']; mode: PermissionMode }

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
  /** Files to put into the composer, from *Add to Canopy Chat*. */
  | { type: 'insertAttachments'; attachments: Attachment[] }
  /** A rewound message to edit and resend. */
  | { type: 'editPrompt'; parts: PromptPart[] }
  /** A group chat: everything so far, then live state and items. */
  | { type: 'groupSnapshot'; state: GroupState; items: TimelineItem[] }
  | { type: 'groupState'; state: GroupState }
  | { type: 'groupItem'; agent: string; item: SessionItem }
  | { type: 'side'; side: SideData }
  | { type: 'laneCards'; lanes: LaneCard[] }
  | { type: 'groupComposer'; composer: GroupComposer }
  | { type: 'setup'; setup: SetupData }
  | { type: 'review'; review: ReviewData }
  | { type: 'newLane'; data: NewLaneData }
  | { type: 'newLaneIssues'; issues: IssueRef[]; notes: string[]; pick?: string }
  | { type: 'newLaneError'; message: string }

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
  | { type: 'warmUpLane'; laneId: string }
  | { type: 'openLaneChat'; laneId: string }
  | { type: 'openLanes' }
  | { type: 'setRoster'; role: 'lead' | 'research' | 'implement' | 'review' | 'verify'; value: string }
  | { type: 'setEnforce'; value: boolean }
  | { type: 'editWorkspaceConfig' }
  | { type: 'manageAgents' }
  | { type: 'installAgent'; providerId: string }
  | { type: 'addAgent' }
  | { type: 'setQuestionsTo'; value: 'lead' | 'user' }
  | { type: 'setPalette'; value: string }
  | { type: 'setRepoSetup'; repo: string; command: string }
  | { type: 'setRepoEnvFiles'; repo: string; value: string }
  | { type: 'finishSetup' }
  | { type: 'openSetup' }
  | { type: 'newLaneFindIssue'; ref: string }
  | { type: 'newLaneCreate'; name: string; repos: string[]; lead: string; issue?: Pick<IssueRef, 'source' | 'id'> }
  | { type: 'viewHandoff'; id: string }
  | { type: 'openLaneDiff' }
  | { type: 'createPullRequest' }
  | { type: 'openReview' }
  | { type: 'groupSetLead'; agent: string }
  | { type: 'groupSendNow'; text: string }
  | { type: 'resumeDelegation'; id: string }
  | { type: 'cancelDelegation'; id: string }
  | { type: 'answerDelegate'; id: string; text: string }
  | { type: 'allowViolation'; id: string }
  | { type: 'connectLinear' }
  | { type: 'disconnectLinear' }
  | { type: 'groupAnswer'; agent: string; itemId: string; response: PromptResponse }
  | { type: 'answerQuestion'; id: string; text: string }
  | { type: 'stopAndSend'; queuedId: string }
  | { type: 'cancelQueued'; queuedId: string }
  | { type: 'groupStop' }
  | { type: 'groupRetry' }
  | { type: 'undoViolation'; id: string }
  | { type: 'undoDelegation'; id: string }
