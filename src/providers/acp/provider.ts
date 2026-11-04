import { type ChildProcess, execFile } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { promisify } from 'node:util'
import { Emitter } from '../../core/emitter'
import type {
  ApprovalItem,
  ApprovalOption,
  CommandOption,
  ModelOption,
  OpenOptions,
  PermissionMode,
  PromptPart,
  PromptResponse,
  ProviderDefinition,
  ProviderSession,
  ProviderState,
  Question,
  QuestionItem,
  SessionFact,
  SessionItem,
  SignInEvent,
  WriteBoundary
} from '../../core/types'
import type { Env } from '../../env'
import { spawnGroup, stopGroup } from '../../process'
import { encodePrompt, imageParts } from '../encode'
import { writable } from '../boundary'
import { PromptHolder } from '../prompt-holder'
import { grokAnswers } from '../prompts'
import { RpcPeer, type ServerRequest } from '../rpc'
import { deviceLink, runLoginCli } from '../sign-in'
import { type AcpAgentSpec, findAgentCli } from './spec'
import { AcpTranslator, type SessionUpdate } from './translate'

const run = promisify(execFile)

const MODE_LIST: readonly PermissionMode[] = ['ask', 'accept-edits', 'full-access']
const STDERR_TAIL = 4000

type AcpModel = { modelId: string; name: string; description?: string | null; _meta?: { totalContextTokens?: number } | null }
type SessionResult = { sessionId?: string; models?: { currentModelId: string; availableModels: AcpModel[] } | null }
type PermissionOption = { optionId: string; name: string; kind: 'allow_once' | 'allow_always' | 'reject_once' | 'reject_always' }
type PermissionRequest = {
  toolCall: {
    toolCallId: string
    title?: string | null
    kind?: string | null
    locations?: { path: string }[] | null
    content?: { type: string; path?: string }[] | null
  }
  options: PermissionOption[]
}

type AgentQuestionRequest = {
  toolCallId: string
  questions: {
    question: string
    multiSelect?: boolean | null
    options: { label: string; description?: string | null; preview?: string | null }[]
  }[]
}

type AgentPlanRequest = { toolCallId: string; planContent?: string | null; plan?: string | null }

const selected = (optionId: string) => ({ outcome: { outcome: 'selected', optionId } })
const CANCELLED = { outcome: { outcome: 'cancelled' } }
const WRITES = new Set(['edit', 'delete', 'move'])

const APPROVAL_TITLES: Record<string, string> = { edit: 'edit this file', execute: 'run this command', fetch: 'fetch this' }

function home(env: Env): string {
  return env.HOME ?? homedir()
}

export function acpProvider(spec: AcpAgentSpec): ProviderDefinition {
  return {
    id: spec.id,
    label: spec.label,
    cli: { command: spec.command, installUrl: spec.installUrl },
    signInCommand: (env) => [`"${findAgentCli(spec, env, home(env)) ?? spec.command}"`, ...spec.loginArgs].join(' '),
    async startSignIn(env: Env, onEvent: (event: SignInEvent) => void) {
      const path = findAgentCli(spec, env, home(env))
      if (!path) throw new Error(`The ${spec.command} CLI was not found.`)
      return runLoginCli(path, spec.loginArgs, env, onEvent, deviceLink)
    },
    capabilities: new Set(['resume', 'interrupt', 'models', 'setModel', 'modes', 'setMode', 'context']),
    modes: MODE_LIST,

    async probe(env: Env): Promise<ProviderState> {
      const path = findAgentCli(spec, env, home(env))
      if (!path) return { status: 'not-installed' }
      try {
        const { stdout } = await run(path, ['--version'], { env, timeout: 15_000 })
        const version = stdout.match(/\d+\.\d+\.\d+/)?.[0]
        return { status: spec.signedIn(env, home(env)) ? 'signed-in' : 'signed-out', version }
      } catch {
        return { status: 'unknown' }
      }
    },

    async open(options: OpenOptions): Promise<ProviderSession> {
      const path = findAgentCli(spec, options.env, home(options.env))
      if (!path) throw new Error(`The ${spec.command} CLI was not found.`)
      return AcpSession.start(spec, path, options)
    }
  }
}

/** The files a tool call says it will write. */
function editPaths(toolCall: PermissionRequest['toolCall']): string[] {
  return [...(toolCall.locations ?? []).map((location) => location.path), ...(toolCall.content ?? []).flatMap((block) => (block.type === 'diff' && block.path ? [block.path] : []))]
}

class AcpSession implements ProviderSession {
  nativeId = ''
  private readonly items = new Emitter<SessionItem>()
  private readonly facts = new Emitter<SessionFact>()
  private readonly exits = new Emitter<{ error?: string }>()
  readonly onItem = this.items.event
  readonly onFact = this.facts.event
  readonly onExit = this.exits.event
  private readonly translator = new AcpTranslator((item) => this.items.fire(item))
  private readonly holder = new PromptHolder((item) => this.items.fire(item))
  private models: (ModelOption & { contextWindow?: number })[] = []
  private model = ''
  private mode: PermissionMode
  private boundary: WriteBoundary | undefined
  private replaying = false
  private imagesAccepted = false
  private commands: CommandOption[] = []
  private closed = false
  private stderr = ''

  static async start(spec: AcpAgentSpec, path: string, options: OpenOptions): Promise<AcpSession> {
    const child = spawnGroup(path, spec.args, { cwd: options.cwd, env: options.env, stdio: ['pipe', 'pipe', 'pipe'] })
    const rpc = new RpcPeer(child.stdout!, child.stdin!, { envelope: { jsonrpc: '2.0' } })
    const session = new AcpSession(spec, child, rpc, options)
    try {
      await session.handshake()
    } catch (error) {
      session.closed = true
      await stopGroup(child)
      throw error
    }
    // Facts go out after open() resolves, once the caller has subscribed.
    setImmediate(() => void session.announce())
    return session
  }

  private constructor(
    private readonly spec: AcpAgentSpec,
    private readonly child: ChildProcess,
    private readonly rpc: RpcPeer,
    private readonly options: OpenOptions
  ) {
    this.mode = options.mode
    rpc.onNotification(({ method, params }) => {
      if (method !== 'session/update') return
      const update = (params as { update: SessionUpdate }).update
      if (update.sessionUpdate === 'available_commands_update') {
        this.commands = (update.availableCommands ?? []).map((command) => ({
          name: command.name,
          description: command.description ?? undefined
        }))
        this.facts.fire({ kind: 'commands', items: this.commands })
      } else if (!this.replaying) {
        // session/load replays the conversation; the journal already holds it.
        this.translator.feed(update)
      }
    })
    rpc.onRequest((request) => this.serverRequest(request))
    child.stderr?.setEncoding('utf8')
    child.stderr?.on('data', (chunk: string) => {
      this.stderr = (this.stderr + chunk).slice(-STDERR_TAIL)
    })
    child.on('exit', (code, signal) => {
      rpc.close(new Error(`${spec.command} exited`))
      this.exits.fire({ error: this.closed ? undefined : `${spec.command} exited (${code ?? signal}).\n${this.stderr.trim()}` })
    })
  }

  async prompt(parts: PromptPart[]): Promise<void> {
    if (imageParts(parts).length > 0 && !this.imagesAccepted) {
      this.items.fire({
        kind: 'notice',
        id: `notice:${randomUUID()}`,
        level: 'warning',
        text: `${this.spec.label} does not accept images, so they were left out of this message.`
      })
    }
    this.translator.startTurn()
    this.rpc
      .request<{ stopReason: string; _meta?: { totalTokens?: number } | null }>('session/prompt', {
        sessionId: this.nativeId,
        prompt: [
          { type: 'text', text: encodePrompt(parts, this.options.cwd) },
          ...(this.imagesAccepted
            ? imageParts(parts).map((image) => ({ type: 'image', mimeType: image.mimeType, data: readFileSync(image.path).toString('base64') }))
            : [])
        ]
      })
      .then(
        (result) => {
          this.translator.endTurn(result.stopReason)
          const used = result._meta?.totalTokens
          const window = this.models.find((model) => model.id === this.model)?.contextWindow
          if (used && window) this.facts.fire({ kind: 'context', usedTokens: used, maxTokens: window })
        },
        (error: Error) => {
          if (!this.closed) this.translator.failTurn(error.message)
        }
      )
  }

  async cancel(): Promise<void> {
    this.translator.interrupted()
    this.holder.dismissAll()
    this.rpc.notify('session/cancel', { sessionId: this.nativeId })
  }

  async setModel(id: string): Promise<void> {
    try {
      await this.rpc.request('session/set_model', { sessionId: this.nativeId, modelId: id })
    } catch {
      await this.rpc.request('session/set_config_option', { sessionId: this.nativeId, configId: 'model', value: id })
    }
    this.model = id
    this.facts.fire({ kind: 'model', current: id, available: this.models })
  }

  async setMode(mode: PermissionMode): Promise<void> {
    this.mode = mode
    this.facts.fire({ kind: 'mode', current: mode, available: MODE_LIST })
  }

  answer(itemId: string, response: PromptResponse): void {
    this.holder.answer(itemId, response)
  }

  setBoundary(boundary: WriteBoundary | undefined): void {
    this.boundary = boundary
  }

  async dispose(): Promise<void> {
    this.closed = true
    this.holder.dismissAll()
    await stopGroup(this.child)
  }

  private async handshake(): Promise<void> {
    const init = await this.rpc.request<{ authMethods?: { id: string }[]; agentCapabilities?: { loadSession?: boolean; promptCapabilities?: { image?: boolean } } }>(
      'initialize',
      {
        protocolVersion: 1,
        clientCapabilities: { fs: { readTextFile: false, writeTextFile: false }, terminal: false },
        clientInfo: { name: 'canopy', version: '1.0.1' }
      }
    )
    this.imagesAccepted = init.agentCapabilities?.promptCapabilities?.image === true
    const method = this.spec.authMethod((init.authMethods ?? []).map((auth) => auth.id), this.options.env)
    if (method) await this.rpc.request('authenticate', { methodId: method })
    const tool = this.options.toolServer
    const params = { cwd: this.options.cwd, mcpServers: tool ? [{ type: 'http', name: tool.name, url: tool.url, headers: [] }] : [] }
    let result: SessionResult
    if (this.options.resumeId && init.agentCapabilities?.loadSession) {
      this.replaying = true
      try {
        result = await this.rpc.request<SessionResult>('session/load', { ...params, sessionId: this.options.resumeId })
      } finally {
        this.replaying = false
      }
      this.nativeId = this.options.resumeId
    } else {
      result = await this.rpc.request<SessionResult>('session/new', params)
      this.nativeId = result.sessionId ?? ''
    }
    this.models = (result.models?.availableModels ?? []).map((model) => ({
      id: model.modelId,
      label: model.name,
      description: model.description ?? undefined,
      contextWindow: model._meta?.totalContextTokens
    }))
    this.model = result.models?.currentModelId ?? ''
  }

  private async announce(): Promise<void> {
    if (this.options.model && this.options.model !== this.model) await this.setModel(this.options.model).catch(() => undefined)
    this.facts.fire({ kind: 'mode', current: this.mode, available: MODE_LIST })
    this.facts.fire({ kind: 'model', current: this.model, available: this.models })
    if (this.commands.length > 0) this.facts.fire({ kind: 'commands', items: this.commands })
  }

  private serverRequest({ method, params }: ServerRequest): Promise<unknown> {
    // Grok's extensions arrive with or without a leading underscore.
    const name = method.replace(/^_/, '')
    if (name === 'session/request_permission') return this.permission(params as PermissionRequest)
    if (name === 'x.ai/ask_user_question') return this.question(params as AgentQuestionRequest)
    if (name === 'x.ai/exit_plan_mode') return this.plan(params as AgentPlanRequest)
    return Promise.reject(new Error(`Canopy does not handle ${method}.`))
  }

  private refuseEdit(options: PermissionRequest['options']): unknown {
    const reject = options.find((option) => option.kind === 'reject_once') ?? options.find((option) => option.kind === 'reject_always')
    return reject ? selected(reject.optionId) : { outcome: { outcome: 'cancelled' } }
  }

  private permission({ toolCall, options }: PermissionRequest): Promise<unknown> {
    const outside = this.outsideBoundary(toolCall)
    if (outside) return outside
    // A read-only role runs reads and checks without a person present. Edits are refused unless they are to its notes,
    // which the boundary check above has already allowed; a shell write is caught after the turn.
    const readOnly = this.boundary?.readOnly || this.boundary?.roots.length === 0
    if (readOnly && toolCall.kind === 'edit' && editPaths(toolCall).length === 0) return Promise.resolve(this.refuseEdit(options))
    const allow = options.find((option) => option.kind === 'allow_once') ?? options.find((option) => option.kind === 'allow_always')
    const autoAllow = readOnly || this.mode === 'full-access' || (this.mode === 'accept-edits' && toolCall.kind === 'edit')
    if (autoAllow && allow) return Promise.resolve(selected(allow.optionId))
    const optionIds = new Map<string, string>()
    const choices: ApprovalOption[] = []
    for (const [kind, id, label] of [
      ['allow_once', 'allow', 'Allow once'],
      ['allow_always', 'allowForSession', undefined],
      ['reject_once', 'deny', 'Deny']
    ] as const) {
      const option = options.find((candidate) => candidate.kind === kind)
      if (!option) continue
      optionIds.set(id, option.optionId)
      choices.push({ id, label: label ?? option.name })
    }
    const item: ApprovalItem = {
      kind: 'approval',
      id: `approval:${toolCall.toolCallId}`,
      title: `Allow ${this.spec.label} to ${APPROVAL_TITLES[toolCall.kind ?? ''] ?? 'use this tool'}?`,
      detail: toolCall.title?.replaceAll('`', '') ?? undefined,
      ...(this.translator.diffIdsFor(toolCall.toolCallId).length > 0 ? { diffIds: this.translator.diffIdsFor(toolCall.toolCallId) } : {}),
      options: choices
    }
    return this.holder.hold(item, (response) => {
      const optionId = response.kind === 'option' ? response.optionId : 'dismissed'
      const chosen = optionIds.get(optionId)
      return { resolved: optionId, result: chosen ? selected(chosen) : CANCELLED }
    })
  }

  /** An edit outside the lane is refused without asking; the reason shows in the transcript. */
  private outsideBoundary(toolCall: PermissionRequest['toolCall']): Promise<unknown> | undefined {
    const boundary = this.boundary
    if (!boundary || !WRITES.has(toolCall.kind ?? '')) return undefined
    const refused = editPaths(toolCall).find((path) => !writable(boundary, path))
    if (!refused) return undefined
    return boundary.outside(refused).then((reason) => {
      this.items.fire({ kind: 'notice', id: `notice:${toolCall.toolCallId}`, level: 'warning', text: reason })
      return CANCELLED
    })
  }

  private question(request: AgentQuestionRequest): Promise<unknown> {
    const questions: Question[] = request.questions.map((question, index) => ({
      id: `q${index + 1}`,
      question: question.question,
      multiSelect: question.multiSelect === true,
      allowOther: true,
      options: question.options.map((option, optionIndex) => ({
        id: `o${optionIndex + 1}`,
        label: option.label,
        description: option.description ?? undefined,
        preview: option.preview ?? undefined
      }))
    }))
    const item: QuestionItem = { kind: 'question', id: `question:${request.toolCallId}`, questions }
    return this.holder.hold(item, (response) =>
      response.kind === 'answers'
        ? { resolved: { answers: response.answers }, result: grokAnswers(questions, response.answers) }
        : { resolved: 'dismissed', result: { outcome: 'cancelled' } }
    )
  }

  /** Grok treats any error reply as a disconnected client, so every verdict is a result. */
  private plan(request: AgentPlanRequest): Promise<unknown> {
    const item: ApprovalItem = {
      kind: 'approval',
      id: `approval:plan:${request.toolCallId}`,
      title: 'Ready to build?',
      subject: { kind: 'plan', text: request.planContent ?? request.plan ?? '' },
      options: [
        { id: 'approve', label: 'Approve' },
        { id: 'keep-planning', label: 'Keep planning' }
      ]
    }
    return this.holder.hold(item, (response) => {
      const optionId = response.kind === 'option' ? response.optionId : 'dismissed'
      const outcome = optionId === 'approve' ? 'approved' : optionId === 'keep-planning' ? 'cancelled' : 'abandoned'
      return { resolved: optionId, result: { outcome } }
    })
  }
}
