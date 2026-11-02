import { randomUUID } from 'node:crypto'
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { type Disposable, Emitter } from '../core/emitter'
import type { PermissionMode, PromptPart, PromptResponse, ProviderDefinition, SessionItem } from '../core/types'
import type { SessionEvent, SessionManager } from '../sessions/manager'
import type { SessionRecord, SessionStatus } from '../sessions/store'
import { catchUpText, Ledger } from './ledger'
import { parseMentions } from './mentions'
import { rollingLines } from './rolling'

export type Delivery = 'now' | 'end-of-turn' | 'queued'
export type QueuedMessage = { id: string; target: string; text: string }

/** Saved per chat: everything else comes from each agent's own session and the ledger. */
export type GroupRecord = {
  id: string
  title: string
  createdAt: string
  lead: string
  /** Who gets a message with no mention: the last agent addressed. */
  target: string
  /** One ordinary session per agent. */
  members: Record<string, string>
  /** How far each agent has read the ledger. */
  cursors: Record<string, number>
  queue: QueuedMessage[]
  laneId?: string
  mode: PermissionMode
  /** The reason the queue stopped, until the user retries. */
  blocked?: string
}

export type MemberState = { agent: string; status: SessionStatus; activity: string }
export type GroupState = { id: string; title: string; lead: string; target: string; running?: string; queue: QueuedMessage[]; members: MemberState[]; blocked?: string; laneId?: string }
export type TimelineItem = { agent: string; item: SessionItem }

export type GroupEvent = { type: 'item'; agent: string; item: SessionItem } | { type: 'state'; state: GroupState } | { type: 'queueChanged'; agent: string }

export type GroupDeps = {
  manager: SessionManager
  providers: ReadonlyMap<string, ProviderDefinition>
  dir: string
}

const isBusy = (status: SessionStatus) => status === 'running' || status === 'needs-input'

/**
 * One conversation across agents. AgentDeck owns the shared record; each agent keeps its own session and context.
 * One agent runs at a time, so writes need no locks; other messages wait in a queue the user can see and change.
 */
export class GroupChat implements Disposable {
  private readonly events = new Emitter<GroupEvent>()
  readonly onEvent = this.events.event
  readonly ledger: Ledger
  private readonly listeners = new Map<string, Disposable>()
  private readonly statuses = new Map<string, SessionStatus>()
  private readonly sessionQueues = new Map<string, { id: string }[]>()
  private readonly seenItems = new Set<string>()
  private readonly timeline: { agent: string; id: string }[] = []
  private readonly latest = new Map<string, SessionItem[]>()
  private current: { agent: string; entry: number; started: boolean } | undefined

  constructor(
    private readonly deps: GroupDeps,
    readonly record: GroupRecord
  ) {
    this.ledger = new Ledger(join(deps.dir, record.id, 'ledger.jsonl'))
    const timeline = join(deps.dir, record.id, 'timeline.jsonl')
    if (existsSync(timeline)) {
      for (const line of readFileSync(timeline, 'utf8').split('\n').filter(Boolean)) {
        const entry = JSON.parse(line) as { agent: string; id: string }
        this.timeline.push(entry)
        this.seenItems.add(`${entry.agent}:${entry.id}`)
      }
    }
    for (const agent of Object.keys(record.members)) this.watch(agent)
  }

  get agents(): string[] {
    return [...this.deps.providers.keys()]
  }

  state(): GroupState {
    const { record } = this
    return {
      id: record.id,
      title: record.title,
      lead: record.lead,
      target: record.target,
      queue: [...record.queue],
      members: Object.keys(record.members).map((agent) => ({ agent, status: this.statuses.get(agent) ?? 'idle', activity: this.activity(agent) })),
      ...(this.current ? { running: this.current.agent } : {}),
      ...(record.blocked ? { blocked: record.blocked } : {}),
      ...(record.laneId ? { laneId: record.laneId } : {})
    }
  }

  /** Everything said and done, in the order it happened, across agents. */
  items(): TimelineItem[] {
    return this.timeline.flatMap(({ agent, id }) => {
      const sessionId = this.record.members[agent]
      const item = sessionId ? this.deps.manager.item(sessionId, id) : undefined
      return item ? [{ agent, item }] : []
    })
  }

  /** Sends a message: each `@agent` part to that agent, the rest to whoever was last addressed. Says when each part arrives. */
  async send(text: string): Promise<{ id: string; target: string; delivery: Delivery }[]> {
    const results: { id: string; target: string; delivery: Delivery }[] = []
    for (const segment of parseMentions(text, this.agents)) {
      const target = segment.target ?? this.record.target
      this.record.target = target
      const queued: QueuedMessage = { id: randomUUID(), target, text: segment.text }
      results.push({ id: queued.id, target, delivery: await this.deliver(queued) })
    }
    this.save()
    this.changed()
    void this.pump()
    return results
  }

  private async deliver(message: QueuedMessage): Promise<Delivery> {
    const running = this.current?.agent === message.target && this.statuses.get(message.target) === 'running'
    if (running && this.deps.providers.get(message.target)?.capabilities.has('steer')) {
      await this.steer(message)
      return 'now'
    }
    if (running) {
      // Ahead of anyone else's turn: the agent being spoken to hears it as soon as it stops.
      this.record.queue.unshift(message)
      return 'end-of-turn'
    }
    this.record.queue.push(message)
    return this.current ? 'queued' : 'now'
  }

  private async steer(message: QueuedMessage): Promise<void> {
    const sessionId = this.record.members[message.target]
    this.ledger.append({ from: 'user', to: message.target, text: message.text })
    await this.deps.manager.prompt(sessionId, [{ type: 'text', text: message.text }])
    const queued = this.sessionQueues.get(message.target)?.at(-1)
    if (queued) await this.deps.manager.steer(sessionId, queued.id)
  }

  /** Interrupts the running agent, so a queued message for it goes now. */
  async stopAndSend(queuedId: string): Promise<void> {
    const index = this.record.queue.findIndex((message) => message.id === queuedId)
    if (index < 0 || !this.current) return
    const [message] = this.record.queue.splice(index, 1)
    this.record.queue.unshift(message)
    this.save()
    await this.deps.manager.cancel(this.record.members[this.current.agent])
  }

  cancelQueued(queuedId: string): void {
    this.record.queue = this.record.queue.filter((message) => message.id !== queuedId)
    this.save()
    this.changed()
  }

  /** Moves a queued message earlier or later. */
  moveQueued(queuedId: string, index: number): void {
    const from = this.record.queue.findIndex((message) => message.id === queuedId)
    if (from < 0) return
    const [message] = this.record.queue.splice(from, 1)
    this.record.queue.splice(Math.max(0, index), 0, message)
    this.save()
    this.changed()
  }

  setLead(agent: string): void {
    this.record.lead = agent
    this.record.target = agent
    this.save()
    this.changed()
  }

  async setLane(laneId: string | undefined): Promise<void> {
    if (laneId) this.record.laneId = laneId
    else delete this.record.laneId
    for (const sessionId of Object.values(this.record.members)) await this.deps.manager.setLane(sessionId, laneId)
    this.save()
    this.changed()
  }

  /** Answers a permission or question from an agent. */
  answer(agent: string, itemId: string, response: PromptResponse): void {
    const sessionId = this.record.members[agent]
    if (sessionId) this.deps.manager.answer(sessionId, itemId, response)
  }

  async stop(): Promise<void> {
    if (this.current) await this.deps.manager.cancel(this.record.members[this.current.agent])
  }

  /** Clears a stop, such as a failed turn or a limit, and carries on with the queue. */
  retry(): void {
    delete this.record.blocked
    this.save()
    this.changed()
    void this.pump()
  }

  dispose(): void {
    for (const listener of this.listeners.values()) listener.dispose()
    this.listeners.clear()
  }

  /** The manager's `decorate` hook for one member: what this agent missed, ahead of what it is told. */
  catchUp(agent: string, parts: PromptPart[]): PromptPart[] {
    const cursor = this.record.cursors[agent] ?? 0
    const text = catchUpText(this.ledger.missed(cursor, agent, this.current?.agent === agent ? this.current.entry : undefined))
    this.record.cursors[agent] = this.ledger.length
    this.save()
    return text ? [{ type: 'text', text }, ...parts] : parts
  }

  private async pump(): Promise<void> {
    if (this.current || this.record.blocked) return
    const next = this.record.queue[0]
    if (!next) return
    this.record.queue.shift()
    const sessionId = await this.member(next.target)
    const entry = this.ledger.append({ from: 'user', to: next.target, text: next.text })
    this.current = { agent: next.target, entry: entry.seq, started: false }
    this.save()
    this.changed()
    await this.deps.manager.prompt(sessionId, [{ type: 'text', text: next.text }])
  }

  private async member(agent: string): Promise<string> {
    const existing = this.record.members[agent]
    if (existing) return existing
    const record = await this.deps.manager.create(agent, this.record.mode)
    if (this.record.laneId) await this.deps.manager.setLane(record.id, this.record.laneId)
    this.record.members[agent] = record.id
    this.save()
    this.watch(agent)
    return record.id
  }

  private watch(agent: string): void {
    if (this.listeners.has(agent)) return
    const sessionId = this.record.members[agent]
    const listener = this.deps.manager.subscribe(sessionId, (event) => this.onSession(agent, event))
    this.listeners.set(agent, listener)
  }

  private onSession(agent: string, event: SessionEvent): void {
    if (event.type === 'snapshot') {
      this.statuses.set(agent, event.status)
      this.sessionQueues.set(agent, event.queue)
      this.latest.set(agent, event.items)
      return
    }
    if (event.type === 'queue') this.sessionQueues.set(agent, event.queue)
    if (event.type === 'item') this.onItem(agent, event.item)
    if (event.type === 'status') this.onStatus(agent, event.status)
  }

  private onItem(agent: string, item: SessionItem): void {
    const items = this.latest.get(agent) ?? []
    const index = items.findIndex((other) => other.id === item.id)
    if (index >= 0) items[index] = item
    else items.push(item)
    this.latest.set(agent, items)
    const key = `${agent}:${item.id}`
    if (!this.seenItems.has(key)) {
      this.seenItems.add(key)
      this.timeline.push({ agent, id: item.id })
      const dir = join(this.deps.dir, this.record.id)
      mkdirSync(dir, { recursive: true })
      writeFileSync(join(dir, 'timeline.jsonl'), `${JSON.stringify({ agent, id: item.id })}\n`, { flag: 'a' })
    }
    this.events.fire({ type: 'item', agent, item })
  }

  private onStatus(agent: string, status: SessionStatus): void {
    this.statuses.set(agent, status)
    const current = this.current
    if (current?.agent === agent && isBusy(status)) current.started = true
    if (current?.agent === agent && current.started && !isBusy(status)) {
      const reply = this.deps.manager.lastReply(this.record.members[agent])
      if (reply) this.ledger.append({ from: agent, text: reply })
      this.current = undefined
      if (status === 'error') this.record.blocked = `${agent} stopped with an error.`
      this.save()
      this.changed()
      void this.pump()
      return
    }
    this.changed()
  }

  private activity(agent: string): string {
    const lines = rollingLines(this.latest.get(agent) ?? [])
    const tool = [...lines].reverse().find((line) => line.kind === 'tool' && line.live)
    return tool?.text ?? lines.at(-1)?.text ?? ''
  }

  private changed(): void {
    this.events.fire({ type: 'state', state: this.state() })
  }

  private save(): void {
    const dir = join(this.deps.dir, this.record.id)
    mkdirSync(dir, { recursive: true })
    writeFileSync(join(dir, 'record.json'), JSON.stringify(this.record))
  }
}

/** All group chats in a workspace. A chat that is not a group chat is untouched. */
export class GroupChats implements Disposable {
  private readonly chats = new Map<string, GroupChat>()

  constructor(private readonly deps: GroupDeps) {
    if (!existsSync(deps.dir)) return
    for (const id of readdirSync(deps.dir)) {
      const path = join(deps.dir, id, 'record.json')
      if (!existsSync(path)) continue
      const record = JSON.parse(readFileSync(path, 'utf8')) as GroupRecord
      this.chats.set(id, new GroupChat(deps, record))
    }
  }

  list(): GroupChat[] {
    return [...this.chats.values()]
  }

  get(id: string): GroupChat | undefined {
    return this.chats.get(id)
  }

  create(options: { lead: string; title?: string; mode?: PermissionMode; laneId?: string }): GroupChat {
    const record: GroupRecord = {
      id: randomUUID(),
      title: options.title ?? 'New chat',
      createdAt: new Date().toISOString(),
      lead: options.lead,
      target: options.lead,
      members: {},
      cursors: {},
      queue: [],
      mode: options.mode ?? 'ask',
      ...(options.laneId ? { laneId: options.laneId } : {})
    }
    const chat = new GroupChat(this.deps, record)
    this.chats.set(record.id, chat)
    return chat
  }

  delete(id: string): void {
    this.chats.get(id)?.dispose()
    this.chats.delete(id)
    rmSync(join(this.deps.dir, id), { recursive: true, force: true })
  }

  /** Composes onto the session manager's `decorate`: adds what a group member missed. */
  decorate = async (record: SessionRecord, parts: PromptPart[]): Promise<PromptPart[]> => {
    for (const chat of this.chats.values()) {
      const agent = Object.entries(chat.record.members).find(([, id]) => id === record.id)?.[0]
      if (agent) return chat.catchUp(agent, parts)
    }
    return parts
  }

  dispose(): void {
    for (const chat of this.chats.values()) chat.dispose()
  }
}

