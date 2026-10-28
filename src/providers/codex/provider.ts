import { type ChildProcess, execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { Emitter } from '../../core/emitter'
import type {
  ApprovalItem,
  McpServer,
  McpSignIn,
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
import { refreshUntilSettled } from '../mcp-settle'
import { findCodex } from './locate'
import type { ApprovalPolicy, McpServerStatus, ModelInfo, SandboxMode, SandboxPolicy, TokenUsage } from './protocol'
import { RpcPeer, type ServerRequest } from '../rpc'
import { unwrapShell } from './text'
import { CodexTranslator } from './translate'

const run = promisify(execFile)

const MODE_LIST: readonly PermissionMode[] = ['ask', 'accept-edits', 'full-access']
const STDERR_TAIL = 4000

const RUNTIME: Record<string, McpServer['status']> = {
  notStarted: 'pending',
  starting: 'pending',
  connected: 'connected',
  authenticationRequired: 'needs-auth',
  failed: 'failed',
  cancelled: 'failed',
  disabled: 'disabled'
}

const STARTUP: Record<string, McpServer['status']> = {
  starting: 'pending',
  ready: 'connected',
  failed: 'failed',
  cancelled: 'failed'
}

function policy(mode: PermissionMode): { approvalPolicy: ApprovalPolicy; sandbox: SandboxMode } {
  return mode === 'full-access'
    ? { approvalPolicy: 'never', sandbox: 'danger-full-access' }
    : { approvalPolicy: 'on-request', sandbox: 'workspace-write' }
}

function sandboxPolicy(mode: PermissionMode, cwd: string): SandboxPolicy {
  return mode === 'full-access'
    ? { type: 'dangerFullAccess' }
    : { type: 'workspaceWrite', writableRoots: [cwd], networkAccess: false, excludeTmpdirEnvVar: false, excludeSlashTmp: false }
}

export const codexProvider: ProviderDefinition = {
  id: 'codex',
  label: 'Codex',
  cli: { command: 'codex', installUrl: 'https://developers.openai.com/codex/cli' },
  signInCommand: (env: Env) => `"${findCodex(env) ?? 'codex'}" login`,
  capabilities: new Set(['resume', 'interrupt', 'models', 'setModel', 'modes', 'setMode', 'mcpStatus', 'context']),
  modes: MODE_LIST,

  async probe(env: Env): Promise<ProviderState> {
    const path = findCodex(env)
    if (!path) return { status: 'not-installed' }
    const options = { env, timeout: 15_000 }
    try {
      const version = (await run(path, ['--version'], options)).stdout.trim().split(' ').pop()
      // `codex login status` exits non-zero when signed out; its output says which.
      const status = await run(path, ['login', 'status'], options).then(
        ({ stdout, stderr }) => `${stdout}${stderr}`,
        (error: { stdout?: string; stderr?: string }) => `${error.stdout ?? ''}${error.stderr ?? ''}`
      )
      const signedIn = /logged in/i.test(status) && !/not logged in/i.test(status)
      return { status: signedIn ? 'signed-in' : 'signed-out', version }
    } catch {
      return { status: 'unknown' }
    }
  },

  async open(options: OpenOptions): Promise<ProviderSession> {
    const path = findCodex(options.env)
    if (!path) throw new Error('The codex CLI was not found.')
    return CodexSession.start(path, options)
  }
}

class CodexSession implements ProviderSession {
  nativeId = ''
  private readonly items = new Emitter<SessionItem>()
  private readonly facts = new Emitter<SessionFact>()
  private readonly exits = new Emitter<{ error?: string }>()
  readonly onItem = this.items.event
  readonly onFact = this.facts.event
  readonly onExit = this.exits.event
  private readonly translator = new CodexTranslator((item) => this.items.fire(item))
  private readonly approvals = new Map<string, { item: ApprovalItem; resolve: (decision: string) => void }>()
  private readonly startup = new Map<string, McpServer['status']>()
  private models: ModelOption[] = []
  private model: string | undefined
  private mode: PermissionMode
  private turnId: string | undefined
  private ready = false
  private closed = false
  private stderr = ''

  static async start(path: string, options: OpenOptions): Promise<CodexSession> {
    const child = spawnGroup(path, ['app-server'], { cwd: options.cwd, env: options.env, stdio: ['pipe', 'pipe', 'pipe'] })
    const session = new CodexSession(child, new RpcPeer(child.stdout!, child.stdin!), options)
    try {
      await session.handshake()
    } catch (error) {
      session.closed = true
      await stopGroup(child)
      throw error
    }
    // Facts are emitted after open() resolves, once the caller has subscribed.
    void session.loadFacts()
    return session
  }

  private constructor(
    private readonly child: ChildProcess,
    private readonly rpc: RpcPeer,
    private readonly options: OpenOptions
  ) {
    this.mode = options.mode
    this.model = options.model
    rpc.onNotification(({ method, params }) => this.notification(method, params))
    rpc.onRequest((request) => this.serverRequest(request))
    child.stderr?.setEncoding('utf8')
    child.stderr?.on('data', (chunk: string) => {
      this.stderr = (this.stderr + chunk).slice(-STDERR_TAIL)
    })
    child.on('exit', (code, signal) => {
      rpc.close(new Error('codex app-server exited'))
      const error = this.closed ? undefined : `codex app-server exited (${code ?? signal}).\n${this.stderr.trim()}`
      this.exits.fire({ error })
    })
  }

  async prompt(parts: PromptPart[]): Promise<void> {
    await this.rpc.request('turn/start', {
      threadId: this.nativeId,
      input: [{ type: 'text', text: encodePrompt(parts, this.options.cwd), text_elements: [] }],
      approvalPolicy: policy(this.mode).approvalPolicy,
      sandboxPolicy: sandboxPolicy(this.mode, this.options.cwd),
      model: this.model ?? null
    })
  }

  async cancel(): Promise<void> {
    if (!this.turnId) return
    this.translator.interrupted()
    await this.rpc.request('turn/interrupt', { threadId: this.nativeId, turnId: this.turnId })
  }

  async setModel(id: string): Promise<void> {
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
    this.approvals.delete(itemId)
    this.items.fire({ ...pending.item, resolved: optionId })
    pending.resolve(optionId === 'allow' ? 'accept' : optionId === 'always' ? 'acceptForSession' : 'decline')
  }

  async refreshMcp(): Promise<void> {
    await refreshUntilSettled(
      async () => {
        const { data } = await this.rpc.request<{ data: McpServerStatus[] }>('mcpServerStatus/list', {})
        return data.map((server) => this.mcpServer(server))
      },
      (servers) => this.facts.fire({ kind: 'mcp', servers }),
      { intervalMs: 1000, attempts: 30, closed: () => this.closed }
    )
  }

  async reconnectMcp(): Promise<void> {
    await this.rpc.request('config/mcpServer/reload')
    await this.refreshMcp()
  }

  async mcpSignIn(server: string): Promise<McpSignIn> {
    const { authorizationUrl } = await this.rpc.request<{ authorizationUrl: string }>('mcpServer/oauth/login', {
      name: server,
      threadId: this.nativeId
    })
    return { kind: 'url', url: authorizationUrl }
  }

  async dispose(): Promise<void> {
    this.closed = true
    for (const id of [...this.approvals.keys()]) this.answer(id, 'deny')
    await stopGroup(this.child)
  }

  private async handshake(): Promise<void> {
    await this.rpc.request('initialize', {
      clientInfo: { name: 'agentdeck', title: 'AgentDeck', version: '0.0.1' },
      capabilities: { experimentalApi: true, requestAttestation: false }
    })
    this.rpc.notify('initialized')
    const params = { cwd: this.options.cwd, ...policy(this.mode), model: this.options.model ?? null }
    const result = this.options.resumeId
      ? await this.rpc.request<{ thread: { id: string }; model: string }>('thread/resume', { ...params, threadId: this.options.resumeId })
      : await this.rpc.request<{ thread: { id: string }; model: string }>('thread/start', params)
    this.nativeId = result.thread.id
    this.model ??= result.model
  }

  private async loadFacts(): Promise<void> {
    this.ready = true
    try {
      const { data } = await this.rpc.request<{ data: ModelInfo[] }>('model/list', {})
      this.models = data.filter((model) => !model.hidden).map((model) => ({ id: model.id, label: model.displayName, description: model.description }))
    } catch {
      // The model picker then offers only the current model.
    }
    this.facts.fire({ kind: 'mode', current: this.mode, available: MODE_LIST })
    this.facts.fire({ kind: 'model', current: this.model ?? '', available: this.models })
    await this.refreshMcp().catch(() => undefined)
  }

  private notification(method: string, params: unknown): void {
    this.translator.feed(method, params)
    switch (method) {
      case 'turn/started':
        this.turnId = (params as { turn: { id: string } }).turn.id
        return
      case 'turn/completed':
        this.turnId = undefined
        return
      case 'thread/tokenUsage/updated': {
        const { tokenUsage } = params as { tokenUsage: TokenUsage }
        if (tokenUsage.modelContextWindow) {
          this.facts.fire({ kind: 'context', usedTokens: tokenUsage.last.totalTokens, maxTokens: tokenUsage.modelContextWindow })
        }
        return
      }
      case 'mcpServer/startupStatus/updated': {
        const { name, status } = params as { name: string; status: string }
        this.startup.set(name, STARTUP[status] ?? 'pending')
        if (this.ready) void this.refreshMcp().catch(() => undefined)
        return
      }
    }
  }

  private serverRequest({ method, params }: ServerRequest): Promise<unknown> {
    if (method === 'item/commandExecution/requestApproval') {
      const request = params as { itemId: string; command?: string | null; reason?: string | null }
      const detail = request.command ? unwrapShell(request.command) : (request.reason ?? undefined)
      return this.ask(request.itemId, 'Allow Codex to run this command?', detail)
    }
    if (method === 'item/fileChange/requestApproval') {
      const request = params as { itemId: string; reason?: string | null; grantRoot?: string | null }
      if (this.mode === 'accept-edits') return Promise.resolve({ decision: 'accept' })
      return this.ask(request.itemId, 'Allow Codex to change files?', request.grantRoot ?? request.reason ?? undefined)
    }
    return Promise.reject(new Error(`AgentDeck does not handle ${method} yet.`))
  }

  private ask(itemId: string, title: string, detail: string | undefined): Promise<{ decision: string }> {
    const item: ApprovalItem = {
      kind: 'approval',
      id: `approval:${itemId}`,
      title,
      detail,
      options: [
        { id: 'allow', label: 'Allow once' },
        { id: 'always', label: 'Allow for this session' },
        { id: 'deny', label: 'Deny' }
      ]
    }
    return new Promise((resolve) => {
      this.approvals.set(item.id, { item, resolve: (decision) => resolve({ decision }) })
      this.items.fire(item)
    })
  }

  private mcpServer(server: McpServerStatus): McpServer {
    const status =
      (server.runtimeStatus ? RUNTIME[server.runtimeStatus] : undefined) ??
      this.startup.get(server.name) ??
      (server.authStatus === 'notLoggedIn' ? 'needs-auth' : 'connected')
    return { name: server.name, status, tools: Object.keys(server.tools ?? {}), error: server.toolsError ?? undefined }
  }
}
