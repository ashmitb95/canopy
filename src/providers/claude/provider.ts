import { execFile } from 'node:child_process'
import { randomUUID, type UUID } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { promisify } from 'node:util'
import type {
  CanUseTool,
  EffortLevel,
  HookInput,
  HookJSONOutput,
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
  ModelOption,
  OpenOptions,
  PermissionMode,
  PromptPart,
  PromptResponse,
  ProviderDefinition,
  ProviderSession,
  ProviderState,
  QuestionItem,
  Quota,
  SessionFact,
  SessionItem,
  SignInEvent,
  WriteBoundary
} from '../../core/types'
import type { Env } from '../../env'
import { BRANCH_SWITCH, claudeWritePaths, switchesBranch, writable } from '../boundary'
import { refreshUntilSettled } from '../mcp-settle'
import { PromptHolder } from '../prompt-holder'
import { claudeAnswers } from '../prompts'
import { encodePrompt, imageParts } from '../encode'
import { findClaude } from './locate'
import { claudeSignIn } from './sign-in'
import { claudeQuota, type RateLimitInfo } from './quota'
import { approvalDetail } from './tools'
import { ClaudeTranslator } from './translate'

const run = promisify(execFile)

type QueryFn = typeof import('@anthropic-ai/claude-agent-sdk').query
type ApprovalContext = Parameters<CanUseTool>[2]

const MODES: Record<PermissionMode, SdkPermissionMode> = {
  ask: 'default',
  'accept-edits': 'acceptEdits',
  auto: 'auto',
  plan: 'plan',
  'full-access': 'bypassPermissions'
}
const MODE_LIST: readonly PermissionMode[] = ['ask', 'accept-edits', 'auto', 'plan', 'full-access']

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
  signInCommand: () => 'claude auth login --claudeai',
  async startSignIn(env: Env, onEvent: (event: SignInEvent) => void) {
    const path = await findClaude(env)
    if (!path) throw new Error('The claude CLI was not found.')
    return claudeSignIn(path, claudeEnv(env), onEvent)
  },
  capabilities: new Set(['resume', 'interrupt', 'models', 'setModel', 'modes', 'setMode', 'mcpStatus', 'context', 'effort', 'steer', 'compact', 'fork', 'rewind', 'rewindFiles']),
  modes: MODE_LIST,

  async probe(env: Env): Promise<ProviderState> {
    const path = await findClaude(env)
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
    const path = await findClaude(options.env)
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

const EDIT_TOOLS = new Set(['Edit', 'Write'])

const PLAN_OPTIONS = [
  { id: 'approve:ask', label: 'Approve · Ask before edits' },
  { id: 'approve:accept-edits', label: 'Approve · Accept edits' },
  { id: 'approve:auto', label: 'Approve · Auto' },
  { id: 'keep-planning', label: 'Keep planning' }
]

class ClaudeSession implements ProviderSession {
  readonly nativeId: string
  private readonly items = new Emitter<SessionItem>()
  private readonly facts = new Emitter<SessionFact>()
  private readonly exits = new Emitter<{ error?: string }>()
  readonly onItem = this.items.event
  readonly onFact = this.facts.event
  readonly onExit = this.exits.event
  private readonly quotas = new Emitter<Quota>()
  readonly onQuota = this.quotas.event
  private readonly translator = new ClaudeTranslator((item) => this.items.fire(item))
  private readonly holder = new PromptHolder((item) => this.items.fire(item))
  private boundary: WriteBoundary | undefined
  private readonly query: Query
  private readonly inbox: SDKUserMessage[] = []
  private wake: (() => void) | null = null
  private closed = false
  private models: ModelOption[] = []
  private model: string
  private efforts = new Map<string, string[]>()
  private effort: string | undefined
  private costUsd: number | undefined

  constructor(
    query: QueryFn,
    cliPath: string,
    private readonly options: OpenOptions
  ) {
    this.nativeId = options.resumeId && !options.resumeAt ? options.resumeId : randomUUID()
    this.model = options.model ?? 'default'
    this.effort = options.effort
    this.query = query({
      prompt: this.messages(),
      options: {
        pathToClaudeCodeExecutable: cliPath,
        cwd: options.cwd,
        env: claudeEnv(options.env),
        model: options.model,
        ...(options.effort ? { effort: options.effort as EffortLevel } : {}),
        ...(options.toolServer ? { mcpServers: { [options.toolServer.name]: { type: 'http' as const, url: options.toolServer.url } } } : {}),
        includePartialMessages: true,
        enableFileCheckpointing: true,
        systemPrompt: { type: 'preset', preset: 'claude_code' },
        settingSources: ['user', 'project', 'local'],
        permissionMode: MODES[options.mode],
        // Permits switching to full access mid-session; the starting mode is still options.mode.
        allowDangerouslySkipPermissions: true,
        ...(options.resumeId && options.resumeAt
          ? { resume: options.resumeId, resumeSessionAt: options.resumeAt, forkSession: true, sessionId: this.nativeId }
          : options.resumeId
            ? { resume: options.resumeId }
            : { sessionId: this.nativeId }),
        canUseTool: (toolName, input, context) => this.requestApproval(toolName, input, context),
        // Hooks run in every permission mode, so lane boundaries hold in full access too.
        hooks: { PreToolUse: [{ hooks: [(input) => this.guard(input)] }] }
      }
    })
    void this.pump()
    void this.loadFacts()
  }

  async prompt(parts: PromptPart[]): Promise<void> {
    const promptRef = randomUUID()
    this.translator.startTurn(promptRef)
    this.push(parts, promptRef)
  }

  async setEffort(effort: string): Promise<void> {
    await this.query.applyFlagSettings({ effortLevel: effort as EffortLevel })
    this.effort = effort
    this.fireEffort()
  }

  async compact(): Promise<void> {
    await this.prompt([{ type: 'command', name: 'compact' }])
  }

  async steer(parts: PromptPart[]): Promise<void> {
    // The CLI reads streaming input during a turn and takes the message at its next step.
    this.push(parts)
  }

  private fireEffort(): void {
    const available = this.efforts.get(this.model) ?? this.efforts.get(this.models.find((model) => model.resolved === this.model)?.id ?? '') ?? []
    this.facts.fire({ kind: 'effort', ...(this.effort ? { current: this.effort } : {}), available })
  }

  private push(parts: PromptPart[], uuid?: UUID): void {
    const text = encodePrompt(parts, this.options.cwd)
    const images = imageParts(parts)
    const content =
      images.length === 0
        ? text
        : [
            { type: 'text' as const, text },
            ...images.map((image) => ({
              type: 'image' as const,
              source: {
                type: 'base64' as const,
                media_type: image.mimeType as 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp',
                data: readFileSync(image.path).toString('base64')
              }
            }))
          ]
    this.inbox.push({ type: 'user', message: { role: 'user', content }, parent_tool_use_id: null, ...(uuid ? { uuid } : {}) })
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
    this.fireEffort()
  }

  async setMode(mode: PermissionMode): Promise<void> {
    await this.query.setPermissionMode(MODES[mode])
    this.facts.fire({ kind: 'mode', current: mode, available: MODE_LIST })
  }

  answer(itemId: string, response: PromptResponse): void {
    this.holder.answer(itemId, response)
  }

  setBoundary(boundary: WriteBoundary | undefined): void {
    this.boundary = boundary
  }

  private async guard(input: HookInput): Promise<HookJSONOutput> {
    const boundary = this.boundary
    if (!boundary || input.hook_event_name !== 'PreToolUse') return {}
    const toolInput = (input.tool_input ?? {}) as Record<string, unknown>
    let reason: string | undefined
    if (input.tool_name === 'Bash' && typeof toolInput.command === 'string' && switchesBranch(toolInput.command)) reason = BRANCH_SWITCH
    for (const path of claudeWritePaths(input.tool_name, toolInput, this.options.cwd)) {
      if (!reason && !writable(boundary, path)) reason = await boundary.outside(path)
    }
    return reason ? { hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'deny', permissionDecisionReason: reason } } : {}
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

  async fork(): Promise<string> {
    const { forkSession } = await import('@anthropic-ai/claude-agent-sdk')
    const { sessionId } = await forkSession(this.nativeId, { dir: this.options.cwd })
    return sessionId
  }

  async rewind(target: { prompt?: string; keep?: string; files: boolean }): Promise<{ restart?: { resumeAt?: string } }> {
    if (target.files && target.prompt) {
      const result = await this.query.rewindFiles(target.prompt)
      if (!result.canRewind) throw new Error(result.error ?? 'Claude could not restore the files.')
    }
    return { restart: { ...(target.keep ? { resumeAt: target.keep } : {}) } }
  }

  async dispose(): Promise<void> {
    this.closed = true
    this.wake?.()
    this.holder.dismissAll()
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
        if (message.type === 'result') {
          this.costUsd = message.total_cost_usd
          void this.refreshContext()
        }
        if (message.type === 'rate_limit_event') {
          const quota = claudeQuota(message.rate_limit_info as RateLimitInfo)
          if (quota) this.quotas.fire(quota)
        }
      }
    } catch (caught) {
      if (!this.closed) error = caught instanceof Error ? caught.message : String(caught)
    }
    this.exits.fire({ error })
  }

  private async loadFacts(): Promise<void> {
    try {
      const models = await this.query.supportedModels()
      this.models = models.map((model) => ({
        id: model.value,
        label: model.displayName,
        description: model.description,
        resolved: model.resolvedModel
      }))
      this.efforts = new Map(models.map((model) => [model.value, model.supportedEffortLevels ?? []]))
    } catch {
      // The model picker then offers only the current model.
    }
    this.facts.fire({ kind: 'mode', current: this.options.mode, available: MODE_LIST })
    this.facts.fire({ kind: 'model', current: this.model, available: this.models })
    this.fireEffort()
    try {
      const commands = await this.query.supportedCommands()
      this.facts.fire({
        kind: 'commands',
        items: commands.map((command) => ({ name: command.name, description: command.description || undefined }))
      })
    } catch {
      // The / menu then lists nothing.
    }
    await this.refreshMcp().catch(() => undefined)
  }

  private async refreshContext(): Promise<void> {
    try {
      const usage = await this.query.getContextUsage({ detail: 'summary' })
      this.facts.fire({
        kind: 'context',
        usedTokens: usage.totalTokens,
        maxTokens: usage.maxTokens,
        ...(this.costUsd !== undefined ? { costUsd: this.costUsd } : {})
      })
    } catch {
      // Older CLIs lack this request; the context meter stays hidden.
    }
  }

  private requestApproval(
    toolName: string,
    input: Record<string, unknown>,
    context: ApprovalContext
  ): Promise<PermissionResult> {
    const prompt =
      toolName === 'AskUserQuestion' ? this.question(input, context.toolUseID) : this.approval(toolName, input, context)
    context.signal.addEventListener('abort', () => this.holder.answer(`${toolName === 'AskUserQuestion' ? 'question' : 'approval'}:${context.toolUseID}`, { kind: 'dismiss' }))
    return prompt
  }

  private question(input: Record<string, unknown>, toolUseId: string): Promise<PermissionResult> {
    const raw = (Array.isArray(input.questions) ? input.questions : []) as {
      question: string
      header?: string
      multiSelect?: boolean
      options?: { label: string; description?: string; preview?: string }[]
    }[]
    const item: QuestionItem = {
      kind: 'question',
      id: `question:${toolUseId}`,
      questions: raw.map((question, index) => ({
        id: `q${index + 1}`,
        header: question.header,
        question: question.question,
        multiSelect: question.multiSelect === true,
        allowOther: true,
        options: (question.options ?? []).map((option, optionIndex) => ({
          id: `o${optionIndex + 1}`,
          label: option.label,
          description: option.description,
          preview: option.preview
        }))
      }))
    }
    return this.holder.hold<PermissionResult>(item, (response) =>
      response.kind === 'answers'
        ? {
            resolved: { answers: response.answers },
            // The CLI rejects an allow without updatedInput, although the SDK types mark it optional.
            result: { behavior: 'allow', updatedInput: { ...input, answers: claudeAnswers(item.questions, response.answers) } }
          }
        : {
            resolved: 'dismissed',
            result: {
              behavior: 'deny',
              message: 'The user dismissed these questions without answering. End your turn and wait for them.'
            }
          }
    )
  }

  private approval(toolName: string, input: Record<string, unknown>, context: ApprovalContext): Promise<PermissionResult> {
    const plan = toolName === 'ExitPlanMode' && typeof input.plan === 'string' ? input.plan : undefined
    const filePath = typeof input.planFilePath === 'string' ? input.planFilePath : undefined
    const suggestions = context.suppressAlwaysAllowRule ? [] : (context.suggestions ?? [])
    const reason = [context.decisionReason, context.blockedPath && `Path: ${context.blockedPath}`].filter(Boolean).join(' · ')
    const item: ApprovalItem = {
      kind: 'approval',
      id: `approval:${context.toolUseID}`,
      title: plan ? 'Ready to code?' : (context.title ?? `Allow ${toolName}?`),
      ...(plan ? { subject: { kind: 'plan' as const, text: plan, ...(filePath ? { filePath } : {}) } } : { detail: approvalDetail(input) }),
      ...(context.description ? { description: context.description } : {}),
      ...(reason ? { reason } : {}),
      ...(EDIT_TOOLS.has(toolName) ? { diffIds: [`${context.toolUseID}:diff`] } : {}),
      options: plan
        ? PLAN_OPTIONS
        : [
            { id: 'allow', label: 'Allow once' },
            ...(suggestions.length > 0 ? [{ id: 'allowForSession', label: 'Allow for this session' }] : []),
            { id: 'deny', label: 'Deny' }
          ]
    }
    return this.holder.hold(item, (response) => {
      const optionId = response.kind === 'option' ? response.optionId : 'dismissed'
      return { resolved: optionId, result: this.approvalResult(optionId, input, suggestions, plan !== undefined) }
    })
  }

  private approvalResult(
    optionId: string,
    input: Record<string, unknown>,
    suggestions: PermissionUpdate[],
    plan: boolean
  ): PermissionResult {
    if (optionId.startsWith('approve:')) {
      const mode = optionId.slice('approve:'.length) as PermissionMode
      this.facts.fire({ kind: 'mode', current: mode, available: MODE_LIST })
      return {
        behavior: 'allow',
        updatedInput: input,
        updatedPermissions: [{ type: 'setMode', mode: MODES[mode], destination: 'session' }]
      }
    }
    if (optionId === 'allow' || optionId === 'allowForSession') {
      // The CLI rejects an allow without updatedInput, although the SDK types mark it optional.
      return {
        behavior: 'allow',
        updatedInput: input,
        // "For this session": the CLI's own suggestion, kept to this session rather than written to settings.
        ...(optionId === 'allowForSession'
          ? { updatedPermissions: suggestions.map((suggestion) => ({ ...suggestion, destination: 'session' as const })) }
          : {})
      }
    }
    const message =
      optionId === 'keep-planning'
        ? 'The user asked you to keep planning. Revise the plan and call ExitPlanMode again.'
        : optionId === 'dismissed'
          ? plan
            ? 'The user dismissed this plan without approving it. End your turn and wait for them to say what to change.'
            : 'The user dismissed this request. End your turn and wait for them.'
          : 'The user denied this action.'
    return { behavior: 'deny', message }
  }
}
