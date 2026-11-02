import type { Env } from '../env'
import type { Event } from './emitter'

export type PromptPart =
  | { type: 'text'; text: string }
  | { type: 'file'; path: string; range?: [number, number] }
  | { type: 'command'; name: string }
  | { type: 'pasted'; text: string }
  /** An image in AgentDeck's attachment store. */
  | { type: 'image'; path: string; mimeType: string; name: string }

export type ToolKind = 'read' | 'edit' | 'execute' | 'search' | 'fetch' | 'mcp' | 'other'

export type PlanEntry = { text: string; status: 'pending' | 'in_progress' | 'done' }

export type ApprovalOption = { id: string; label: string }

/** What an approval is about, beyond a tool call: a plan to accept before the agent builds. */
export type ApprovalSubject = { kind: 'plan'; text: string; filePath?: string }

export type AssistantMessage = { kind: 'message'; id: string; role: 'assistant'; text: string; streaming: boolean }
export type UserMessage = { kind: 'message'; id: string; role: 'user'; parts: PromptPart[] }
export type Thought = { kind: 'thought'; id: string; text: string; streaming: boolean }
export type ToolItem = {
  kind: 'tool'
  id: string
  title: string
  toolKind: ToolKind
  status: 'running' | 'done' | 'failed'
  input?: unknown
  output?: string
  paths?: string[]
  parentId?: string
}
export type DiffItem = { kind: 'diff'; id: string; path: string; oldText: string | null; newText: string; parentId?: string }
export type PlanItem = { kind: 'plan'; id: string; entries: PlanEntry[] }
export type ApprovalItem = {
  kind: 'approval'
  id: string
  title: string
  detail?: string
  /** Extra context from the provider, e.g. what the tool will be able to do. */
  description?: string
  /** Why the provider is asking, e.g. a blocked path or a matched rule. */
  reason?: string
  subject?: ApprovalSubject
  /** Diff items this approval would apply, for Review changes. */
  diffIds?: string[]
  options: ApprovalOption[]
  /** The chosen option id, `dismissed`, or `expired`. */
  resolved?: string
}

export type PromptOption = { id: string; label: string; description?: string; preview?: string }

export type Question = {
  id: string
  header?: string
  question: string
  options: PromptOption[]
  multiSelect: boolean
  /** Whether a typed answer is accepted besides the options. */
  allowOther: boolean
  /** A typed answer is a secret: masked while typing and never stored. */
  secret?: boolean
}

export type QuestionAnswer = { questionId: string; optionIds: string[]; other?: string }

export type QuestionItem = {
  kind: 'question'
  id: string
  title?: string
  questions: Question[]
  resolved?: { answers: QuestionAnswer[] } | 'dismissed' | 'expired'
}

/** The user's reply to an approval or a question. */
export type PromptResponse =
  | { kind: 'option'; optionId: string }
  | { kind: 'answers'; answers: QuestionAnswer[] }
  | { kind: 'dismiss' }

/**
 * Where a chat may write for its coming turns: under `roots` but not under `except` (other lanes' checkouts nested
 * inside a root). `outside` explains a refused path, and may act first (e.g. join the lane to a new repo).
 */
export type WriteBoundary = { roots: string[]; except: string[]; outside(path: string): Promise<string> }
export type TurnItem = {
  kind: 'turn'
  id: string
  state: 'started' | 'ended'
  stopReason?: string
  durationMs?: number
  /** When the turn ended (ISO), stamped by the session manager. */
  at?: string
  /** The provider's id for the prompt that started the turn (on both its started and ended items). */
  promptRef?: string
  /** On an ended turn: where the provider can resume up to this turn. */
  ref?: string
}
export type NoticeItem = {
  kind: 'notice'
  id: string
  level: 'info' | 'warning' | 'error'
  text: string
  action?: 'sign-in' | 'retry'
}

/** One transcript entry. An item whose id was seen before replaces the earlier one in place. */
export type SessionItem =
  | AssistantMessage
  | UserMessage
  | Thought
  | ToolItem
  | DiffItem
  | PlanItem
  | ApprovalItem
  | QuestionItem
  | TurnItem
  | NoticeItem

export type PermissionMode = 'ask' | 'accept-edits' | 'auto' | 'plan' | 'full-access'

export type McpServer = {
  name: string
  status: 'connected' | 'failed' | 'needs-auth' | 'pending' | 'disabled'
  /** Where the server is configured, e.g. user, project, local, claudeai. */
  scope?: string
  error?: string
  tools: string[]
}

/** A model the picker offers; the description carries notes such as extra-usage billing. `resolved` is the concrete model id an alias such as `opus` maps to. */
export type ModelOption = { id: string; label: string; description?: string; resolved?: string }

/** A slash command or skill the composer's `/` menu offers. */
export type CommandOption = { name: string; description?: string }

/** Session state shown outside the transcript. The latest fact of each kind wins. */
export type SessionFact =
  /** How the provider's CLI signed in; `source` names where an API key came from. */
  | { kind: 'signIn'; method: 'account' | 'api-key'; source?: string }
  | { kind: 'model'; current: string; available: ModelOption[] }
  | { kind: 'effort'; current?: string; available: string[] }
  | { kind: 'mode'; current: PermissionMode; available: readonly PermissionMode[] }
  | {
      kind: 'context'
      usedTokens: number
      maxTokens: number
      /** Session total at API prices (Claude reports it; subscriptions are not billed this). */
      costUsd?: number
    }
  | { kind: 'mcp'; servers: McpServer[] }
  | { kind: 'commands'; items: CommandOption[] }

export type Capability = 'resume' | 'interrupt' | 'models' | 'setModel' | 'modes' | 'setMode' | 'mcpStatus' | 'context' | 'steer' | 'effort' | 'compact' | 'fork' | 'rewind' | 'rewindFiles'

/** An account's usage limits as its CLI last reported them; shown with their age. */
export type Quota = {
  observedAt: string
  windows: { label: string; usedPercent: number; resetsAt?: string; status: 'ok' | 'warning' | 'limited' }[]
}

export type ProviderState = {
  status: 'signed-in' | 'signed-out' | 'not-installed' | 'unknown'
  version?: string
  account?: string
}

export type OpenOptions = { env: Env; cwd: string; mode: PermissionMode; model?: string; effort?: string; resumeId?: string; resumeAt?: string; toolServer?: { name: string; url: string } }

/** Where a user signs in to an MCP server: a web page, or a CLI flow in a terminal. */
export type McpSignIn = { kind: 'url'; url: string } | { kind: 'terminal'; command: string; hint: string }

/** Progress of a provider's own login. The CLI completes the OAuth and keeps the token. */
export type SignInEvent = { kind: 'link'; url: string; code?: string } | { kind: 'done' } | { kind: 'failed'; message: string }

export type SignInFlow = { cancel(): void }

export interface ProviderDefinition {
  readonly id: string
  readonly label: string
  readonly cli: { command: string; installUrl: string }
  /** Shell command the UI runs in a terminal to sign in; depends on where the CLI was found. */
  signInCommand(env: Env): string
  /** Runs the login inside AgentDeck, reporting the link to open; without it, sign-in runs in a terminal. */
  startSignIn?(env: Env, onEvent: (event: SignInEvent) => void): Promise<SignInFlow>
  readonly capabilities: ReadonlySet<Capability>
  readonly modes: readonly PermissionMode[]
  probe(env: Env): Promise<ProviderState>
  open(options: OpenOptions): Promise<ProviderSession>
  mcpSignIn?(server: string, scope: string | undefined): McpSignIn
}

/**
 * A running provider CLI for one session. It emits nothing until `open()` has resolved, so the
 * caller can subscribe first: initial facts come from asynchronous work.
 */
export interface ProviderSession {
  readonly nativeId: string
  /** Starts a turn. Resolves once the prompt is handed to the CLI; a `turn` item marks its end. */
  prompt(parts: PromptPart[]): Promise<void>
  cancel(): Promise<void>
  /** Copies the conversation into a new provider session; returns its native id. */
  fork?(): Promise<string>
  /**
   * Drops the turn started by `prompt` and everything after; `keep` is the last kept turn's `ref`.
   * Returns `restart` when the provider must be reopened (with `resumeAt`) to finish the rewind.
   */
  rewind?(target: { prompt?: string; keep?: string; files: boolean }): Promise<{ restart?: { resumeAt?: string } }>
  setModel?(id: string): Promise<void>
  /** Sets the reasoning effort for this and later turns. */
  setEffort?(effort: string): Promise<void>
  /** Summarizes the conversation to free context. */
  compact?(): Promise<void>
  /** Adds a message to the running turn instead of waiting for it to end. */
  steer?(parts: PromptPart[]): Promise<void>
  setMode?(mode: PermissionMode): Promise<void>
  /** Settles a pending approval or question. */
  answer(itemId: string, response: PromptResponse): void
  /** Limits writes from the next turn on; undefined lifts the limit. Reads stay open. */
  setBoundary?(boundary: WriteBoundary | undefined): void
  refreshMcp?(): Promise<void>
  reconnectMcp?(server: string): Promise<void>
  /** Starts an MCP server's sign-in from the running CLI, when the provider supports that. */
  mcpSignIn?(server: string): Promise<McpSignIn>
  dispose(): Promise<void>
  readonly onItem: Event<SessionItem>
  readonly onFact: Event<SessionFact>
  readonly onExit: Event<{ error?: string }>
  /** Usage limits, for providers whose CLI reports them. */
  readonly onQuota?: Event<Quota>
}
