import { type ChildProcess, execFile } from 'node:child_process'
import { homedir } from 'node:os'
import { promisify } from 'node:util'
import { Emitter } from '../../core/emitter'
import type {
  ApprovalItem,
  ApprovalOption,
  ModelOption,
  OpenOptions,
  PermissionMode,
  PromptPart,
  ProviderDefinition,
  ProviderSession,
  ProviderState,
  SessionFact,
  SessionItem
} from '../../core/types'
import type { Env } from '../../env'
import { spawnGroup, stopGroup } from '../../process'
import { encodePrompt } from '../encode'
import { RpcPeer, type ServerRequest } from '../rpc'
import { type AcpAgentSpec, findAgentCli } from './spec'
import { AcpTranslator, type SessionUpdate } from './translate'

const run = promisify(execFile)

const MODE_LIST: readonly PermissionMode[] = ['ask', 'accept-edits', 'full-access']
const STDERR_TAIL = 4000

type AcpModel = { modelId: string; name: string; description?: string | null; _meta?: { totalContextTokens?: number } | null }
type SessionResult = { sessionId?: string; models?: { currentModelId: string; availableModels: AcpModel[] } | null }
type PermissionOption = { optionId: string; name: string; kind: 'allow_once' | 'allow_always' | 'reject_once' | 'reject_always' }
type PermissionRequest = { toolCall: { toolCallId: string; title?: string | null; kind?: string | null }; options: PermissionOption[] }

const selected = (optionId: string) => ({ outcome: { outcome: 'selected', optionId } })
const CANCELLED = { outcome: { outcome: 'cancelled' } }

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

class AcpSession implements ProviderSession {
  nativeId = ''
  private readonly items = new Emitter<SessionItem>()
  private readonly facts = new Emitter<SessionFact>()
  private readonly exits = new Emitter<{ error?: string }>()
  readonly onItem = this.items.event
  readonly onFact = this.facts.event
  readonly onExit = this.exits.event
  private readonly translator = new AcpTranslator((item) => this.items.fire(item))
  private readonly approvals = new Map<string, { item: ApprovalItem; optionIds: Map<string, string>; resolve: (result: unknown) => void }>()
  private models: (ModelOption & { contextWindow?: number })[] = []
  private model = ''
  private mode: PermissionMode
  private replaying = false
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
      // session/load replays the conversation; the journal already holds it.
      if (method === 'session/update' && !this.replaying) this.translator.feed((params as { update: SessionUpdate }).update)
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
    this.translator.startTurn()
    this.rpc
      .request<{ stopReason: string; _meta?: { totalTokens?: number } | null }>('session/prompt', {
        sessionId: this.nativeId,
        prompt: [{ type: 'text', text: encodePrompt(parts, this.options.cwd) }]
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
    for (const id of [...this.approvals.keys()]) this.settle(id, CANCELLED, 'deny')
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

  answer(itemId: string, optionId: string): void {
    const pending = this.approvals.get(itemId)
    if (!pending) return
    const acpOption = pending.optionIds.get(optionId)
    this.settle(itemId, acpOption ? selected(acpOption) : CANCELLED, optionId)
  }

  async dispose(): Promise<void> {
    this.closed = true
    for (const id of [...this.approvals.keys()]) this.settle(id, CANCELLED, 'deny')
    await stopGroup(this.child)
  }

  private async handshake(): Promise<void> {
    const init = await this.rpc.request<{ authMethods?: { id: string }[]; agentCapabilities?: { loadSession?: boolean } }>(
      'initialize',
      {
        protocolVersion: 1,
        clientCapabilities: { fs: { readTextFile: false, writeTextFile: false }, terminal: false },
        clientInfo: { name: 'agentdeck', version: '0.1.0' }
      }
    )
    const method = this.spec.authMethod((init.authMethods ?? []).map((auth) => auth.id), this.options.env)
    if (method) await this.rpc.request('authenticate', { methodId: method })
    const params = { cwd: this.options.cwd, mcpServers: [] }
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
  }

  private serverRequest({ method, params }: ServerRequest): Promise<unknown> {
    if (method === 'session/request_permission') return this.permission(params as PermissionRequest)
    return Promise.reject(new Error(`AgentDeck does not handle ${method}.`))
  }

  private permission({ toolCall, options }: PermissionRequest): Promise<unknown> {
    const allow = options.find((option) => option.kind === 'allow_once') ?? options.find((option) => option.kind === 'allow_always')
    const autoAllow = this.mode === 'full-access' || (this.mode === 'accept-edits' && toolCall.kind === 'edit')
    if (autoAllow && allow) return Promise.resolve(selected(allow.optionId))
    const optionIds = new Map<string, string>()
    const choices: ApprovalOption[] = []
    for (const [kind, id, label] of [
      ['allow_once', 'allow', 'Allow once'],
      ['allow_always', 'always', undefined],
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
      options: choices
    }
    return new Promise((resolve) => {
      this.approvals.set(item.id, { item, optionIds, resolve })
      this.items.fire(item)
    })
  }

  private settle(itemId: string, result: unknown, resolved: string): void {
    const pending = this.approvals.get(itemId)
    if (!pending) return
    this.approvals.delete(itemId)
    this.items.fire({ ...pending.item, resolved })
    pending.resolve(result)
  }
}
