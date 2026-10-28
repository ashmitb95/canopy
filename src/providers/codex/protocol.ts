// The subset of the Codex app-server protocol AgentDeck uses, transcribed from
// `codex app-server generate-ts` (codex-cli 0.165.0). Fields AgentDeck ignores are omitted.

export type UserInput = { type: 'text'; text: string; text_elements: [] }

export type CommandAction = { type: 'read' | 'listFiles' | 'search' | 'unknown'; command: string; path?: string | null }

export type FileUpdateChange = {
  path: string
  kind: { type: 'add' } | { type: 'delete' } | { type: 'update'; move_path: string | null }
  diff: string
}

type Status = 'inProgress' | 'completed' | 'failed' | 'declined'

export type ThreadItem =
  | { type: 'agentMessage'; id: string; text: string }
  | { type: 'reasoning'; id: string; summary: string[] }
  | {
      type: 'commandExecution'
      id: string
      command: string
      status: Status
      commandActions: CommandAction[]
      aggregatedOutput: string | null
    }
  | { type: 'fileChange'; id: string; changes: FileUpdateChange[]; status: Status }
  | {
      type: 'mcpToolCall'
      id: string
      server: string
      tool: string
      status: Exclude<Status, 'declined'>
      arguments: unknown
      result: { content: unknown[] } | null
      error: { message: string } | null
    }

export type Turn = {
  id: string
  status: 'completed' | 'interrupted' | 'failed' | 'inProgress'
  error: { message: string } | null
  durationMs: number | null
}

export type PlanStep = { step: string; status: 'pending' | 'inProgress' | 'completed' }

export type TokenUsage = {
  last: { totalTokens: number }
  modelContextWindow: number | null
}

export type McpServerStatus = {
  name: string
  runtimeStatus:
    | 'notStarted'
    | 'starting'
    | 'connected'
    | 'authenticationRequired'
    | 'failed'
    | 'cancelled'
    | 'disabled'
    | null
  authStatus: 'unknown' | 'unsupported' | 'notLoggedIn' | 'bearerToken' | 'oAuth'
  tools: Record<string, unknown>
  toolsError: string | null
}

export type ModelInfo = { id: string; displayName: string; description: string; hidden: boolean }

export type ApprovalPolicy = 'on-request' | 'never'
export type SandboxMode = 'workspace-write' | 'danger-full-access'
export type SandboxPolicy =
  | { type: 'dangerFullAccess' }
  | { type: 'workspaceWrite'; writableRoots: string[]; networkAccess: boolean; excludeTmpdirEnvVar: boolean; excludeSlashTmp: boolean }
