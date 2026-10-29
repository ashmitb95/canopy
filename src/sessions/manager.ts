import { randomUUID } from 'node:crypto'
import { rmSync } from 'node:fs'
import { join } from 'node:path'
import { type Disposable, Emitter } from '../core/emitter'
import type {
  McpSignIn,
  PermissionMode,
  PromptPart,
  PromptResponse,
  ProviderDefinition,
  ProviderSession,
  Quota,
  SessionFact,
  SessionItem
} from '../core/types'
import type { Env } from '../env'
import { Journal } from './journal'
import type { SessionRecord, SessionStatus, SessionStore } from './store'

export type QueuedPrompt = { id: string; parts: PromptPart[] }

/** What a chat surface receives: a snapshot first, then live events. */
export type SessionEvent =
  | { type: 'snapshot'; record: SessionRecord; status: SessionStatus; items: SessionItem[]; queue: QueuedPrompt[] }
  | { type: 'item'; item: SessionItem }
  | { type: 'fact'; fact: SessionFact }
  | { type: 'status'; status: SessionStatus }
  | { type: 'queue'; queue: QueuedPrompt[] }

export type Attention = { sessionId: string; reason: 'needs-input' | 'turn-ended' }

export type QuotaReport = { providerId: string; quota: Quota }

export type SessionManagerDeps = {
  providers: ReadonlyMap<string, ProviderDefinition>
  store: SessionStore
  journalDir: string
  cwd: string
  env: () => Promise<Env>
  /** Adds context to what the provider receives (the transcript keeps what the user wrote). May update the record, which is saved after. */
  decorate?: (record: SessionRecord, parts: PromptPart[]) => Promise<PromptPart[]>
}

type Live = {
  record: SessionRecord
  status: SessionStatus
  items: Map<string, SessionItem>
  queue: QueuedPrompt[]
  journal: Journal
  prompts: Set<string>
  subscribers: Set<(event: SessionEvent) => void>
  session?: ProviderSession
  opening?: Promise<ProviderSession>
  listeners: Disposable[]
  /** Items received since the provider session was opened; zero means it never produced output. */
  received: number
  resumed: boolean
}

const NEW_TITLE = 'New chat'
const MAX_TITLE = 60

export class SessionManager {
  private readonly live = new Map<string, Live>()
  private readonly changed = new Emitter<void>()
  private readonly attention = new Emitter<Attention>()
  private readonly quotas = new Emitter<QuotaReport>()
  /** Fires when the session list, a title, or a status changes. */
  readonly onDidChange = this.changed.event
  /** Fires when a session needs the user or finishes a turn. */
  readonly onAttention = this.attention.event
  /** Fires when a provider's CLI reports its account's usage limits. */
  readonly onQuota = this.quotas.event

  constructor(private readonly deps: SessionManagerDeps) {}

  list(): { record: SessionRecord; status: SessionStatus }[] {
    return this.deps.store.list().map((record) => {
      const live = this.live.get(record.id)
      return live ? { record: live.record, status: live.status } : { record, status: 'idle' }
    })
  }

  async create(providerId: string, mode: PermissionMode = 'ask'): Promise<SessionRecord> {
    if (!this.deps.providers.has(providerId)) throw new Error(`Unknown provider: ${providerId}`)
    const now = new Date().toISOString()
    const record: SessionRecord = {
      id: randomUUID(),
      providerId,
      title: NEW_TITLE,
      createdAt: now,
      updatedAt: now,
      mode,
      hasTurns: false,
      facts: {}
    }
    await this.deps.store.put(record)
    this.changed.fire()
    return record
  }

  subscribe(id: string, listener: (event: SessionEvent) => void): Disposable {
    const live = this.load(id)
    live.subscribers.add(listener)
    listener({
      type: 'snapshot',
      record: live.record,
      status: live.status,
      items: [...live.items.values()],
      queue: [...live.queue]
    })
    return { dispose: () => live.subscribers.delete(listener) }
  }

  /** Starts the provider CLI so models and MCP status are available before the first prompt. */
  async warm(id: string): Promise<void> {
    const live = this.load(id)
    try {
      await this.connect(live)
    } catch (error) {
      this.fail(live, errorText(error))
    }
  }

  async prompt(id: string, parts: PromptPart[]): Promise<void> {
    const live = this.load(id)
    if (live.status === 'running' || live.status === 'needs-input') {
      live.queue.push({ id: randomUUID(), parts })
      this.broadcast(live, { type: 'queue', queue: [...live.queue] })
      return
    }
    await this.send(live, parts)
  }

  removeQueued(id: string, queuedId: string): void {
    const live = this.load(id)
    live.queue = live.queue.filter((queued) => queued.id !== queuedId)
    this.broadcast(live, { type: 'queue', queue: [...live.queue] })
  }

  async cancel(id: string): Promise<void> {
    await this.live.get(id)?.session?.cancel()
  }

  answer(id: string, itemId: string, response: PromptResponse): void {
    this.live.get(id)?.session?.answer(itemId, response)
  }

  item(id: string, itemId: string): SessionItem | undefined {
    return this.live.get(id)?.items.get(itemId)
  }

  async setModel(id: string, model: string): Promise<void> {
    const live = this.load(id)
    live.record.model = model
    await this.save(live)
    await live.session?.setModel?.(model)
  }

  async setMode(id: string, mode: PermissionMode): Promise<void> {
    const live = this.load(id)
    live.record.mode = mode
    await this.save(live)
    await live.session?.setMode?.(mode)
  }

  async refreshMcp(id: string): Promise<void> {
    await this.live.get(id)?.session?.refreshMcp?.()
  }

  async reconnectMcp(id: string, server: string): Promise<void> {
    await this.live.get(id)?.session?.reconnectMcp?.(server)
  }

  async mcpSignIn(id: string, server: string): Promise<McpSignIn | undefined> {
    return this.live.get(id)?.session?.mcpSignIn?.(server)
  }

  async rename(id: string, title: string): Promise<void> {
    const live = this.load(id)
    live.record.title = title
    await this.save(live)
    this.changed.fire()
  }

  async setLane(id: string, laneId: string | undefined): Promise<void> {
    const live = this.load(id)
    if (laneId === undefined) delete live.record.laneId
    else live.record.laneId = laneId
    delete live.record.laneSeen
    await this.save(live)
    this.changed.fire()
  }

  /** Files the chat's diffs touched, as the provider reported them (absolute, or relative to the workspace root). */
  diffPaths(id: string): string[] {
    return [...this.load(id).items.values()].flatMap((item) => (item.kind === 'diff' ? [item.path] : []))
  }

  lastReply(id: string): string | undefined {
    const replies = [...this.load(id).items.values()].flatMap((item) =>
      item.kind === 'message' && item.role === 'assistant' ? [item.text] : []
    )
    return replies.at(-1)
  }

  /** Stops the CLI. The session stays listed and resumes on the next prompt. */
  async stop(id: string): Promise<void> {
    const live = this.live.get(id)
    if (!live) return
    const session = live.session ?? (await live.opening?.catch(() => undefined))
    live.session = undefined
    live.queue = []
    this.broadcast(live, { type: 'queue', queue: [] })
    this.setStatus(live, 'stopped')
    await session?.dispose()
    this.detach(live)
    live.journal.flush()
  }

  async delete(id: string): Promise<void> {
    await this.stop(id)
    this.live.delete(id)
    rmSync(this.journalPath(id), { force: true })
    await this.deps.store.delete(id)
    this.changed.fire()
  }

  async dispose(): Promise<void> {
    await Promise.all([...this.live.keys()].map((id) => this.stop(id)))
  }

  private load(id: string): Live {
    const existing = this.live.get(id)
    if (existing) return existing
    const record = this.deps.store.get(id)
    if (!record) throw new Error(`Unknown session: ${id}`)
    const path = this.journalPath(id)
    const live: Live = {
      record,
      status: 'idle',
      items: new Map(Journal.read(path).map((item) => [item.id, settled(item)])),
      queue: [],
      journal: new Journal(path),
      prompts: new Set(),
      subscribers: new Set(),
      listeners: [],
      received: 0,
      resumed: false
    }
    this.live.set(id, live)
    return live
  }

  private journalPath(id: string): string {
    return join(this.deps.journalDir, `${id}.jsonl`)
  }

  private async send(live: Live, parts: PromptPart[]): Promise<void> {
    if (live.record.title === NEW_TITLE) live.record.title = titleFrom(parts)
    live.record.updatedAt = new Date().toISOString()
    this.setStatus(live, 'running')
    this.upsert(live, { kind: 'message', id: `user:${randomUUID()}`, role: 'user', parts })
    try {
      const session = await this.connect(live)
      const sent = this.deps.decorate ? await this.deps.decorate(live.record, parts).catch(() => parts) : parts
      live.record.hasTurns = true
      await this.save(live)
      await session.prompt(sent)
    } catch (error) {
      this.fail(live, errorText(error))
    }
  }

  private connect(live: Live): Promise<ProviderSession> {
    if (live.session) return Promise.resolve(live.session)
    live.opening ??= this.open(live).finally(() => {
      live.opening = undefined
    })
    return live.opening
  }

  private async open(live: Live): Promise<ProviderSession> {
    const provider = this.deps.providers.get(live.record.providerId)
    if (!provider) throw new Error(`Unknown provider: ${live.record.providerId}`)
    const resumeId = live.record.hasTurns ? live.record.nativeId : undefined
    const session = await provider.open({
      env: await this.deps.env(),
      cwd: this.deps.cwd,
      mode: live.record.mode,
      model: live.record.model,
      resumeId
    })
    live.session = session
    live.received = 0
    live.resumed = resumeId !== undefined
    live.listeners = [
      session.onItem((item) => {
        live.received++
        this.upsert(live, item)
      }),
      session.onFact((fact) => this.fact(live, fact)),
      session.onExit(({ error }) => this.exited(live, session, error)),
      ...(session.onQuota
        ? [session.onQuota((quota) => this.quotas.fire({ providerId: live.record.providerId, quota }))]
        : [])
    ]
    live.record.nativeId = session.nativeId
    await this.save(live)
    return session
  }

  private upsert(live: Live, item: SessionItem): void {
    if (item.kind === 'turn' && item.state === 'ended' && !item.at) item = { ...item, at: new Date().toISOString() }
    live.items.set(item.id, item)
    live.journal.append(item)
    this.broadcast(live, { type: 'item', item })
    if (item.kind === 'approval' || item.kind === 'question') this.promptChanged(live, item.id, item.resolved !== undefined)
    if (item.kind === 'turn' && item.state === 'ended') this.turnEnded(live)
  }

  private promptChanged(live: Live, id: string, resolved: boolean): void {
    if (!resolved) {
      live.prompts.add(id)
      this.setStatus(live, 'needs-input')
      this.attention.fire({ sessionId: live.record.id, reason: 'needs-input' })
      return
    }
    live.prompts.delete(id)
    if (live.prompts.size === 0 && live.status === 'needs-input') this.setStatus(live, 'running')
  }

  private turnEnded(live: Live): void {
    live.journal.flush()
    live.record.updatedAt = new Date().toISOString()
    void this.save(live)
    live.prompts.clear()
    this.setStatus(live, 'idle')
    this.attention.fire({ sessionId: live.record.id, reason: 'turn-ended' })
    const next = live.queue.shift()
    if (!next) return
    this.broadcast(live, { type: 'queue', queue: [...live.queue] })
    void this.send(live, next.parts)
  }

  private fact(live: Live, fact: SessionFact): void {
    if (fact.kind === 'mode') live.record.mode = fact.current
    live.record.facts[fact.kind] = fact
    void this.save(live)
    this.broadcast(live, { type: 'fact', fact })
  }

  private exited(live: Live, session: ProviderSession, error: string | undefined): void {
    if (live.session !== session) return
    live.session = undefined
    this.detach(live)
    live.journal.flush()
    if (!error) {
      if (live.status !== 'idle') this.setStatus(live, 'stopped')
      return
    }
    if (live.resumed && live.received === 0) {
      live.record.hasTurns = false
      void this.save(live)
      error += '\nThe next message starts a new agent session. Earlier messages stay here, but the agent will not remember them.'
    }
    this.fail(live, error)
  }

  private detach(live: Live): void {
    for (const listener of live.listeners) listener.dispose()
    live.listeners = []
  }

  private fail(live: Live, text: string): void {
    this.upsert(live, { kind: 'notice', id: `notice:${randomUUID()}`, level: 'error', text, action: 'retry' })
    live.prompts.clear()
    this.setStatus(live, 'error')
  }

  private setStatus(live: Live, status: SessionStatus): void {
    if (live.status === status) return
    live.status = status
    this.broadcast(live, { type: 'status', status })
    this.changed.fire()
  }

  private broadcast(live: Live, event: SessionEvent): void {
    for (const subscriber of [...live.subscribers]) subscriber(event)
  }

  private async save(live: Live): Promise<void> {
    await this.deps.store.put(live.record)
  }
}

/** Items from a previous run that can no longer change. */
function settled(item: SessionItem): SessionItem {
  if ((item.kind === 'approval' || item.kind === 'question') && item.resolved === undefined) return { ...item, resolved: 'expired' }
  if ((item.kind === 'message' && item.role === 'assistant') || item.kind === 'thought') {
    return item.streaming ? { ...item, streaming: false } : item
  }
  return item
}

function titleFrom(parts: PromptPart[]): string {
  for (const part of parts) {
    if (part.type !== 'text') continue
    const line = part.text
      .split('\n')
      .map((value) => value.trim())
      .find(Boolean)
    if (line) return line.length > MAX_TITLE ? `${line.slice(0, MAX_TITLE - 1)}…` : line
  }
  return NEW_TITLE
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
