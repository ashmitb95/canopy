import { execFile } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { promisify } from 'node:util'
import type {
  CanUseTool,
  PermissionResult,
  PermissionUpdate,
  Query,
  PermissionMode as SdkPermissionMode,
  SDKUserMessage
} from '@anthropic-ai/claude-agent-sdk'
import { Emitter } from '../../core/emitter'
import type {
  ApprovalItem,
  McpSignIn,
  OpenOptions,
  PermissionMode,
  PromptPart,
  ProviderDefinition,
  ProviderSession,
  ProviderState,
  SessionFact,
  SessionItem
} from '../../core/types'
import { type Env, findOnPath } from '../../env'
import { refreshUntilSettled } from '../mcp-settle'
import { encodePrompt } from './encode'
import { approvalDetail } from './tools'
import { ClaudeTranslator } from './translate'

const run = promisify(execFile)

type QueryFn = typeof import('@anthropic-ai/claude-agent-sdk').query
type ApprovalContext = Parameters<CanUseTool>[2]
type PendingApproval = {
  item: ApprovalItem
  input: Record<string, unknown>
  suggestions?: PermissionUpdate[]
  resolve: (result: PermissionResult) => void
}

const MODES: Record<PermissionMode, SdkPermissionMode> = {
  ask: 'default',
  'accept-edits': 'acceptEdits',
  plan: 'plan',
  'full-access': 'bypassPermissions'
}
const MODE_LIST: readonly PermissionMode[] = ['ask', 'accept-edits', 'plan', 'full-access']

/** An inherited API key would bill the API instead of the claude.ai subscription. */
export function claudeEnv(env: Env): Env {
  const copy = { ...env }
  delete copy.ANTHROPIC_API_KEY
  return copy
}

export const claudeProvider: ProviderDefinition = {
  id: 'claude',
  label: 'Claude',
  cli: { command: 'claude', installUrl: 'https://docs.anthropic.com/en/docs/claude-code/setup' },
  signInCommand: 'claude auth login --claudeai',
  capabilities: new Set(['resume', 'interrupt', 'models', 'setModel', 'modes', 'setMode', 'mcpStatus', 'context']),
  modes: MODE_LIST,

  async probe(env: Env): Promise<ProviderState> {
    const path = findOnPath(env, 'claude')
    if (!path) return { status: 'not-installed' }
    const options = { env: claudeEnv(env), timeout: 15_000 }
    try {
      const [version, auth] = await Promise.all([run(path, ['--version'], options), authStatus(path, options)])
      return {
        status: auth.loggedIn ? 'signed-in' : 'signed-out',
        version: version.stdout.trim().split(' ')[0],
        account: auth.email
      }
    } catch {
      return { status: 'unknown' }
    }
  },

  async open(options: OpenOptions): Promise<ProviderSession> {
    const path = findOnPath(options.env, 'claude')
    if (!path) throw new Error('The claude CLI was not found on PATH.')
    // Loaded on first use so activating the extension stays fast.
    const { query } = await import('@anthropic-ai/claude-agent-sdk')
    return new ClaudeSession(query, path, options)
  },

  mcpSignIn(server: string, scope: string | undefined): McpSignIn {
    if (scope === 'claudeai') return { kind: 'url', url: 'https://claude.ai/settings/connectors' }
    return {
      kind: 'terminal',
      command: 'claude',
      hint: `In the terminal, run /mcp and choose ${server} to sign in. Then press Reconnect in AgentDeck.`
    }
  }
}

/** `claude auth status` prints JSON; it may exit non-zero when signed out. */
async function authStatus(
  path: string,
  options: { env: Env; timeout: number }
): Promise<{ loggedIn: boolean; email?: string }> {
  try {
    const { stdout } = await run(path, ['auth', 'status'], options)
    return JSON.parse(stdout)
  } catch (error) {
    const stdout = (error as { stdout?: string }).stdout
    return stdout ? JSON.parse(stdout) : { loggedIn: false }
  }
}

class ClaudeSession implements ProviderSession {
  readonly nativeId: string
  private readonly items = new Emitter<SessionItem>()
  private readonly facts = new Emitter<SessionFact>()
  private readonly exits = new Emitter<{ error?: string }>()
  readonly onItem = this.items.event
  readonly onFact = this.facts.event
  readonly onExit = this.exits.event
  private readonly translator = new ClaudeTranslator((item) => this.items.fire(item))
  private readonly query: Query
  private readonly inbox: SDKUserMessage[] = []
  private wake: (() => void) | null = null
  private closed = false
  private readonly approvals = new Map<string, PendingApproval>()
  private models: { id: string; label: string }[] = []
  private model: string

  constructor(
    query: QueryFn,
    cliPath: string,
    private readonly options: OpenOptions
  ) {
    this.nativeId = options.resumeId ?? randomUUID()
    this.model = options.model ?? 'default'
    this.query = query({
      prompt: this.messages(),
      options: {
        pathToClaudeCodeExecutable: cliPath,
        cwd: options.cwd,
        env: claudeEnv(options.env),
        model: options.model,
        includePartialMessages: true,
        systemPrompt: { type: 'preset', preset: 'claude_code' },
        settingSources: ['user', 'project', 'local'],
        permissionMode: MODES[options.mode],
        // Permits switching to full access mid-session; the starting mode is still options.mode.
        allowDangerouslySkipPermissions: true,
        ...(options.resumeId ? { resume: options.resumeId } : { sessionId: this.nativeId }),
        canUseTool: (toolName, input, context) => this.requestApproval(toolName, input, context)
      }
    })
    void this.pump()
    void this.loadFacts()
  }

  async prompt(parts: PromptPart[]): Promise<void> {
    this.translator.startTurn()
    this.inbox.push({
      type: 'user',
      message: { role: 'user', content: encodePrompt(parts, this.options.cwd) },
      parent_tool_use_id: null
    })
    this.wake?.()
  }

  async cancel(): Promise<void> {
    this.translator.interrupted()
    await this.query.interrupt()
  }

  async setModel(id: string): Promise<void> {
    await this.query.setModel(id)
    this.model = id
    this.facts.fire({ kind: 'model', current: id, available: this.models })
  }

  async setMode(mode: PermissionMode): Promise<void> {
    await this.query.setPermissionMode(MODES[mode])
    this.facts.fire({ kind: 'mode', current: mode, available: MODE_LIST })
  }

  answer(itemId: string, optionId: string): void {
    const pending = this.approvals.get(itemId)
    if (!pending) return
    this.approvals.delete(itemId)
    this.items.fire({ ...pending.item, resolved: optionId })
    if (optionId === 'deny') return pending.resolve({ behavior: 'deny', message: 'The user denied this action.' })
    // The CLI rejects an allow without updatedInput, although the SDK types mark it optional.
    pending.resolve({
      behavior: 'allow',
      updatedInput: pending.input,
      updatedPermissions: optionId === 'always' ? pending.suggestions : undefined
    })
  }

  async refreshMcp(): Promise<void> {
    await refreshUntilSettled(
      async () =>
        (await this.query.mcpServerStatus()).map((server) => ({
          name: server.name,
          status: server.status,
          scope: server.scope,
          error: server.error,
          tools: (server.tools ?? []).map((tool) => tool.name)
        })),
      (servers) => this.facts.fire({ kind: 'mcp', servers }),
      { intervalMs: 1000, attempts: 30, minAttempts: 5, closed: () => this.closed }
    )
  }

  async reconnectMcp(server: string): Promise<void> {
    await this.query.reconnectMcpServer(server)
    await this.refreshMcp()
  }

  async dispose(): Promise<void> {
    this.closed = true
    this.wake?.()
    for (const id of [...this.approvals.keys()]) this.answer(id, 'deny')
    this.query.close()
  }

  private async *messages(): AsyncGenerator<SDKUserMessage> {
    while (!this.closed) {
      const next = this.inbox.shift()
      if (next) {
        yield next
        continue
      }
      await new Promise<void>((resolve) => (this.wake = resolve))
      this.wake = null
    }
  }

  private async pump(): Promise<void> {
    let error: string | undefined
    try {
      for await (const message of this.query) {
        this.translator.feed(message)
        if (message.type === 'system' && message.subtype === 'init') void this.refreshMcp().catch(() => undefined)
        if (message.type === 'system' && message.subtype === 'init' && message.model !== this.model) {
          this.model = message.model
          this.facts.fire({ kind: 'model', current: this.model, available: this.models })
        }
        if (message.type === 'result') void this.refreshContext()
      }
    } catch (caught) {
      if (!this.closed) error = caught instanceof Error ? caught.message : String(caught)
    }
    this.exits.fire({ error })
  }

  private async loadFacts(): Promise<void> {
    try {
      const models = await this.query.supportedModels()
      this.models = models.map((model) => ({ id: model.value, label: model.displayName }))
    } catch {
      // The model picker then offers only the current model.
    }
    this.facts.fire({ kind: 'mode', current: this.options.mode, available: MODE_LIST })
    this.facts.fire({ kind: 'model', current: this.model, available: this.models })
    await this.refreshMcp().catch(() => undefined)
  }

  private async refreshContext(): Promise<void> {
    try {
      const usage = await this.query.getContextUsage({ detail: 'summary' })
      this.facts.fire({ kind: 'context', usedTokens: usage.totalTokens, maxTokens: usage.maxTokens })
    } catch {
      // Older CLIs lack this request; the context meter stays hidden.
    }
  }

  private requestApproval(
    toolName: string,
    input: Record<string, unknown>,
    context: ApprovalContext
  ): Promise<PermissionResult> {
    if (toolName === 'AskUserQuestion') {
      return Promise.resolve({
        behavior: 'deny',
        message: 'This client cannot show questions yet. Ask the user in plain text instead.'
      })
    }
    const suggestions = context.suppressAlwaysAllowRule ? undefined : context.suggestions
    const item: ApprovalItem = {
      kind: 'approval',
      id: `approval:${context.toolUseID}`,
      title: context.title ?? `Allow ${toolName}?`,
      detail: approvalDetail(input),
      options: [
        { id: 'allow', label: 'Allow once' },
        ...(suggestions?.length ? [{ id: 'always', label: 'Always allow' }] : []),
        { id: 'deny', label: 'Deny' }
      ]
    }
    return new Promise((resolve) => {
      this.approvals.set(item.id, { item, input, suggestions, resolve })
      context.signal.addEventListener('abort', () => this.answer(item.id, 'deny'))
      this.items.fire(item)
    })
  }
}
