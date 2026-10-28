import type { Env } from '../env'
import type { Event } from './emitter'

export type PromptPart =
  | { type: 'text'; text: string }
  | { type: 'file'; path: string; range?: [number, number] }

export type ToolKind = 'read' | 'edit' | 'execute' | 'search' | 'fetch' | 'mcp' | 'other'

export type PlanEntry = { text: string; status: 'pending' | 'in_progress' | 'done' }

export type ApprovalOption = { id: string; label: string }

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
  options: ApprovalOption[]
  resolved?: string
}
export type TurnItem = { kind: 'turn'; id: string; state: 'started' | 'ended'; stopReason?: string; durationMs?: number }
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
  | TurnItem
  | NoticeItem

export type PermissionMode = 'ask' | 'accept-edits' | 'plan' | 'full-access'

export type McpServer = {
  name: string
  status: 'connected' | 'failed' | 'needs-auth' | 'pending' | 'disabled'
  /** Where the server is configured, e.g. user, project, local, claudeai. */
  scope?: string
  error?: string
  tools: string[]
}

/** Session state shown outside the transcript. The latest fact of each kind wins. */
export type SessionFact =
  | { kind: 'model'; current: string; available: { id: string; label: string }[] }
  | { kind: 'mode'; current: PermissionMode; available: readonly PermissionMode[] }
  | { kind: 'context'; usedTokens: number; maxTokens: number }
  | { kind: 'mcp'; servers: McpServer[] }

export type Capability = 'resume' | 'interrupt' | 'models' | 'setModel' | 'modes' | 'setMode' | 'mcpStatus' | 'context'

export type ProviderState = {
  status: 'signed-in' | 'signed-out' | 'not-installed' | 'unknown'
  version?: string
  account?: string
}

export type OpenOptions = { env: Env; cwd: string; mode: PermissionMode; model?: string; resumeId?: string }

/** Where a user signs in to an MCP server: a web page, or a CLI flow in a terminal. */
export type McpSignIn = { kind: 'url'; url: string } | { kind: 'terminal'; command: string; hint: string }

export interface ProviderDefinition {
  readonly id: string
  readonly label: string
  readonly cli: { command: string; installUrl: string }
  /** Shell command the UI runs in a terminal to sign in. */
  readonly signInCommand: string
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
  setModel?(id: string): Promise<void>
  setMode?(mode: PermissionMode): Promise<void>
  /** Settles a pending approval item with one of its option ids. */
  answer(itemId: string, optionId: string): void
  refreshMcp?(): Promise<void>
  reconnectMcp?(server: string): Promise<void>
  dispose(): Promise<void>
  readonly onItem: Event<SessionItem>
  readonly onFact: Event<SessionFact>
  readonly onExit: Event<{ error?: string }>
}
