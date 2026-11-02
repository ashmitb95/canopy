import { execFile, execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { existsSync, mkdirSync, readdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { type Disposable, Emitter } from '../core/emitter'
import type { PermissionMode, PromptPart, PromptResponse, ProviderDefinition, SessionItem, WriteBoundary } from '../core/types'
import type { SessionEvent, SessionManager } from '../sessions/manager'
import type { SessionRecord, SessionStatus } from '../sessions/store'
import { catchUpText, Ledger } from './ledger'
import { parseMentions } from './mentions'
import { rollingLines } from './rolling'
import type { Tool } from './tool-server'

export type Delivery = 'now' | 'end-of-turn' | 'queued'
export type QueuedMessage = { id: string; target: string; text: string; delegation?: string; internal?: boolean }

export const ROLES = ['research', 'plan', 'implement', 'review'] as const
export type Role = (typeof ROLES)[number]
export type Roster = Partial<Record<Role, string>>

export type DelegationStatus = 'queued' | 'running' | 'done' | 'blocked' | 'question' | 'unknown' | 'failed'
export type Facts = { files: string[]; commands: { command: string; failed: boolean }[]; verify?: { command: string; ok: boolean; output: string }; violations: string[] }
export type Delegation = { id: string; lead: string; agent: string; role?: Role; task: string; doneWhen: string; status: DelegationStatus; report?: string; facts?: Facts; handoff?: string; before?: string[] }
export type Violation = { id: string; agent: string; files: string[]; before: { path: string; tree: string }[]; undone?: boolean }

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
  roster: Roster
  /** Only the agent holding Implement may write; others are blocked and told to delegate. */
  enforce: boolean
  /** A command AgentDeck runs itself after a delegate writes, such as the test suite. */
  verify?: string
  delegations: Delegation[]
  violations: Violation[]
  /** Which lead was last told how this chat works. */
  briefed?: string
  /** The lead has been reminded once this turn to really delegate. */
  nudged?: boolean
  /** The reason the queue stopped, until the user retries. */
  blocked?: string
}

export type MemberState = { agent: string; status: SessionStatus; activity: string }
export type GroupState = { id: string; title: string; lead: string; target: string; running?: string; queue: QueuedMessage[]; members: MemberState[]; blocked?: string; laneId?: string; roster: Roster; delegations: Delegation[]; violations: Violation[] }
export type TimelineItem = { agent: string; item: SessionItem }

export type GroupEvent = { type: 'item'; agent: string; item: SessionItem } | { type: 'state'; state: GroupState } | { type: 'queueChanged'; agent: string }

export type GroupDeps = {
  manager: SessionManager
  providers: ReadonlyMap<string, ProviderDefinition>
  dir: string
  /** Tool lines show paths relative to this. */
  root?: string
  /** Where a lane's code is: its checkouts, or the primary checkouts for a chat on no lane. */
  checkouts?: (lane: string | undefined) => string[]
  memoryDir?: (lane: string) => string
}

/** Everything in a folder, untracked files included, without touching the working tree, the index, or the stash list. */
function snapshotTree(path: string): string {
  const index = join(realpathSync(tmpdir()), `agentdeck-index-${process.pid}-${randomUUID()}`)
  const git = (args: string[]) => execFileSync('git', args, { cwd: path, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], env: { ...process.env, GIT_INDEX_FILE: index } }).trim()
  try {
    git(['add', '-A', '.'])
    return git(['write-tree'])
  } finally {
    rmSync(index, { force: true })
  }
}

const changed = (path: string, from: string, to: string) => execFileSync('git', ['diff', '--name-status', from, to], { cwd: path, encoding: 'utf8' }).split('\n').filter(Boolean)

/** Puts a folder's files back to a snapshot, removing files added since. */
function restoreTree(path: string, tree: string): void {
  const added = changed(path, tree, snapshotTree(path)).filter((row) => row.startsWith('A\t')).map((row) => row.slice(2))
  for (const file of added) rmSync(join(path, file), { force: true })
  const index = join(realpathSync(tmpdir()), `agentdeck-undo-${process.pid}-${randomUUID()}`)
  const env = { ...process.env, GIT_INDEX_FILE: index }
  try {
    execFileSync('git', ['read-tree', tree], { cwd: path, env })
    execFileSync('git', ['checkout-index', '--all', '--force'], { cwd: path, env })
  } finally {
    rmSync(index, { force: true })
  }
}

const NARRATE = 'Before each step, say in one short line what you are doing or what you just found.'
const SAID_DELEGATE = /\b(hand(ing)?( it| this| that)? (off|over)|delegat(e|ing)|pass(ing)? (it|this) to)\b/i

/** The tools every provider's CLI can call. `caller` carries which chat and agent is calling. */
export function groupTools(handle: (caller: string, name: string, args: Record<string, unknown>) => string): Tool[] {
  return [
    {
      name: 'delegate',
      description: 'Hands work to another agent in this chat, by role or by name. It returns at once. End your turn right after; the report starts your next turn.',
      inputSchema: { type: 'object', properties: { to: { type: 'string', description: 'A role (research, plan, implement, review) or an agent name.' }, task: { type: 'string' }, doneWhen: { type: 'string' } }, required: ['to', 'task'] },
      call: (args, caller) => handle(caller, 'delegate', args)
    }
  ]
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
  private current: { agent: string; entry: number; started: boolean; delegation?: string; itemsAtStart: number; before: { path: string; tree: string }[] } | undefined

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
      ...(record.laneId ? { laneId: record.laneId } : {}),
      roster: record.roster,
      delegations: record.delegations,
      violations: record.violations
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
    this.record.nudged = false
    const results: { id: string; target: string; delivery: Delivery }[] = []
    // The first message of an idle chat goes at once; the rest wait for it.
    let busy = Boolean(this.current) || this.record.queue.length > 0 || Boolean(this.record.blocked)
    for (const segment of parseMentions(text, this.agents)) {
      const target = segment.target ?? this.record.target
      this.record.target = target
      const queued: QueuedMessage = { id: randomUUID(), target, text: segment.text }
      results.push({ id: queued.id, target, delivery: await this.deliver(queued, busy) })
      busy = true
    }
    this.save()
    this.changed()
    void this.pump()
    return results
  }

  private async deliver(message: QueuedMessage, busy: boolean): Promise<Delivery> {
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
    return busy ? 'queued' : 'now'
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

  /** Called through the tool server by an agent in this chat. */
  handleTool(agent: string, name: string, args: Record<string, unknown>): string {
    if (name !== 'delegate') return `Unknown tool ${name}.`
    if (agent !== this.record.lead) return `Only the lead (${this.record.lead}) can delegate.`
    const to = String(args.to ?? '').toLowerCase()
    const role = ROLES.find((candidate) => candidate === to)
    const target = role ? this.record.roster[role] : this.agents.find((candidate) => candidate === to)
    if (!target) return `Nobody holds "${to}". Roster: ${this.rosterText()}.`
    if (target === agent) return `That is you: do this work yourself, without delegating.`
    const held = role ?? ROLES.find((candidate) => this.record.roster[candidate] === target)
    const delegation: Delegation = { id: randomUUID(), lead: agent, agent: target, ...(held ? { role: held } : {}), task: String(args.task ?? ''), doneWhen: String(args.doneWhen ?? ''), status: 'queued' }
    this.record.delegations.push(delegation)
    this.save()
    this.changed()
    return `Accepted: ${target} will do this. End your turn now; its report starts your next turn.`
  }

  /** Read-only for anyone but the Implement agent, when roles are enforced. */
  readOnlyBoundary(agent: string): WriteBoundary | undefined {
    if (!this.record.enforce || !this.record.roster.implement || agent === this.record.roster.implement) return undefined
    const writer = this.record.roster.implement
    return { roots: [], except: [], outside: async () => `Your role is read-only here. ${agent === this.record.lead ? `Delegate this edit to ${writer}.` : `Report what should change; ${writer} edits code.`}` }
  }

  /** Puts files back after a write the role did not allow. */
  undoViolation(id: string): void {
    const violation = this.record.violations.find((candidate) => candidate.id === id)
    if (!violation || violation.undone) return
    for (const { path, tree } of violation.before) restoreTree(path, tree)
    violation.undone = true
    this.ledger.append({ from: 'agentdeck', text: `Undid the write by ${violation.agent}: ${violation.files.join(', ')}.` })
    this.save()
    this.changed()
  }

  private rosterText(): string {
    return ROLES.flatMap((role) => (this.record.roster[role] ? [`${role}: ${this.record.roster[role]}`] : [])).join(', ')
  }

  private leadBrief(agent: string): string {
    const writer = this.record.roster.implement
    return `You lead a group chat of coding agents run by AgentDeck, and you own the work you hand out. Roster: ${this.rosterText()}.${writer && this.record.enforce && writer !== agent ? ` Only ${writer} may edit code; you are read-only.` : ''} When work belongs to another agent, call the delegate tool from the agentdeck MCP server with its role, without asking the user, then end your turn. Reports start your next turn: read them, judge them against what AgentDeck recorded, and decide what happens next.`
  }

  private delegationText(delegation: Delegation): string {
    return `You are ${delegation.agent}, delegated this by ${delegation.lead} in a group chat run by AgentDeck${delegation.role ? `, in the ${delegation.role} role` : ''}.\nTask: ${delegation.task}${delegation.doneWhen ? `\nDone when: ${delegation.doneWhen}` : ''}\n${NARRATE}\nWhen you stop, end your reply with one line: STATUS: done, STATUS: blocked, or STATUS: question, followed by the reason or question. Only say done for what you actually did and checked.`
  }

  /** The manager's `decorate` hook for one member: what this agent missed, ahead of what it is told. */
  catchUp(agent: string, parts: PromptPart[]): PromptPart[] {
    const cursor = this.record.cursors[agent] ?? 0
    const text = catchUpText(this.ledger.missed(cursor, agent, this.current?.agent === agent ? this.current.entry : undefined))
    this.record.cursors[agent] = this.ledger.length
    const brief = agent === this.record.lead && Object.keys(this.record.roster).length > 0 && this.record.briefed !== agent
    if (brief) this.record.briefed = agent
    this.save()
    return [...(brief ? [{ type: 'text' as const, text: this.leadBrief(agent) }] : []), ...(text ? [{ type: 'text' as const, text }] : []), ...parts]
  }

  private async pump(): Promise<void> {
    if (this.current || this.record.blocked) return
    const next = this.record.queue[0]
    if (!next) return
    this.record.queue.shift()
    const sessionId = await this.member(next.target)
    const delegation = next.delegation ? this.record.delegations.find((candidate) => candidate.id === next.delegation) : undefined
    const entry = this.ledger.append(next.internal ? { from: 'agentdeck', to: next.target, text: next.text } : delegation ? { from: delegation.lead, to: next.target, text: `${delegation.task}` } : { from: 'user', to: next.target, text: next.text })
    if (delegation) delegation.status = 'running'
    this.current = { agent: next.target, entry: entry.seq, started: false, ...(delegation ? { delegation: delegation.id } : {}), itemsAtStart: this.latest.get(next.target)?.length ?? 0, before: this.snapshot() }
    await this.applyRole(next.target, sessionId)
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
      void this.turnFinished(agent, status, current)
      return
    }
    this.changed()
  }

  private async turnFinished(agent: string, status: SessionStatus, current: NonNullable<GroupChat['current']>): Promise<void> {
    const reply = this.deps.manager.lastReply(this.record.members[agent])
    if (reply) this.ledger.append({ from: agent, text: reply })
    const violation = this.checkViolation(agent, current.before)
    if (status === 'error') this.record.blocked = `${agent} stopped with an error.`
    const delegation = current.delegation ? this.record.delegations.find((candidate) => candidate.id === current.delegation) : undefined
    if (delegation) await this.finishDelegation(delegation, agent, status, reply ?? '', current, violation)
    this.current = undefined
    if (!delegation) this.afterLeadTurn(agent, reply ?? '')
    // New work the lead asked for goes first, in the order it was asked.
    const pending = this.record.delegations.filter((candidate) => candidate.status === 'queued' && !this.record.queue.some((message) => message.delegation === candidate.id))
    if (pending.length > 0) {
      this.record.nudged = false
      this.record.queue.unshift(...pending.map((candidate) => ({ id: randomUUID(), target: candidate.agent, text: this.delegationText(candidate), delegation: candidate.id })))
    }
    this.save()
    this.changed()
    void this.pump()
  }

  /** A lead that says it will delegate but has not called the tool gets one reminder. */
  private afterLeadTurn(agent: string, reply: string): void {
    if (agent !== this.record.lead || this.record.nudged || !SAID_DELEGATE.test(reply)) return
    if (this.record.delegations.some((candidate) => candidate.status === 'queued')) return
    this.record.nudged = true
    this.record.queue.unshift({ id: randomUUID(), target: agent, internal: true, text: 'You said you would hand this off, but no delegate call reached AgentDeck. Call the delegate tool now if you meant to; otherwise carry on.' })
  }

  private async finishDelegation(delegation: Delegation, agent: string, status: SessionStatus, reply: string, current: NonNullable<GroupChat['current']>, violation: Violation | undefined): Promise<void> {
    const items = (this.latest.get(agent) ?? []).slice(current.itemsAtStart)
    const commands = items.flatMap((item) => (item.kind === 'tool' && (item.toolKind === 'execute' || item.title.startsWith('Run ') || item.title.startsWith('Bash ')) ? [{ command: item.title.replace(/^(Bash|Run|Command Execute)\s+/, '').split('\n')[0].slice(0, 160), failed: item.status === 'failed' }] : []))
    const files = current.before.flatMap(({ path, tree }) => changed(path, tree, snapshotTree(path)))
    const facts: Facts = { files, commands, violations: violation ? violation.files : [] }
    if (this.record.verify && agent === this.record.roster.implement && files.length > 0) facts.verify = await this.runVerify(this.record.verify)
    delegation.facts = facts
    delegation.report = reply
    const stated = /STATUS:\s*(done|blocked|question)/i.exec(reply)?.[1]?.toLowerCase() as DelegationStatus | undefined
    delegation.status = status === 'error' ? 'failed' : (stated ?? 'unknown')
    delegation.handoff = this.saveHandoff(delegation, items)
    if (status === 'error') return
    this.record.queue.unshift({ id: randomUUID(), target: delegation.lead, internal: true, text: this.reportText(delegation) })
  }

  private reportText(delegation: Delegation): string {
    const facts = delegation.facts
    const lines = [
      `Report from ${delegation.agent} on: ${delegation.task}`,
      delegation.report ?? '(no reply)',
      '',
      'Recorded by AgentDeck, not by the agent:',
      `Files changed: ${facts?.files.join('; ') || 'none'}`,
      `Commands run: ${facts?.commands.map((command) => `${command.command}${command.failed ? ' (failed)' : ''}`).join('; ') || 'none'}`,
      ...(facts?.verify ? [`AgentDeck ran ${facts.verify.command}: ${facts.verify.ok ? 'passed' : `FAILED\n${facts.verify.output}`}`] : []),
      ...(facts?.violations.length ? [`Writes its role does not allow: ${facts.violations.join('; ')}`] : []),
      ...(delegation.status === 'unknown' ? ['It did not give a status line, so treat it as not finished until checked.'] : []),
      ...(delegation.handoff ? [`Full record: ${delegation.handoff}`] : []),
      '',
      'Tell the user the real result, and hand out what comes next if the roster calls for it. Do not repeat a claim the record does not support.'
    ]
    return lines.join('\n')
  }

  private saveHandoff(delegation: Delegation, items: SessionItem[]): string {
    const dir = join(this.deps.dir, this.record.id, 'handoffs')
    mkdirSync(dir, { recursive: true })
    const path = join(dir, `${this.record.delegations.indexOf(delegation) + 1}-${delegation.lead}-to-${delegation.agent}.md`)
    const record = rollingLines(items, this.deps.root).map((line) => `${line.kind === 'tool' ? '- ' : line.kind === 'output' ? '    ' : ''}${line.text}${line.stat ? ` ${line.stat}` : ''}`)
    writeFileSync(path, [`# ${delegation.lead} to ${delegation.agent}`, '', `Task: ${delegation.task}`, delegation.doneWhen ? `Done when: ${delegation.doneWhen}` : '', '', '## Facts', JSON.stringify(delegation.facts, null, 2), '', '## Report', delegation.report ?? '', '', '## Record', ...record].join('\n'))
    return path
  }

  private runVerify(command: string): Promise<NonNullable<Facts['verify']>> {
    const cwd = this.deps.checkouts?.(this.record.laneId)[0] ?? this.deps.root ?? process.cwd()
    return new Promise((resolve) => {
      execFile('sh', ['-c', command], { cwd, timeout: 600_000, maxBuffer: 16 * 1024 * 1024 }, (error, stdout, stderr) => {
        resolve({ command, ok: !error, output: `${stdout}${stderr}`.trim().split('\n').slice(-20).join('\n') })
      })
    })
  }

  private snapshot(): { path: string; tree: string }[] {
    return (this.deps.checkouts?.(this.record.laneId) ?? []).flatMap((path) => {
      try {
        return [{ path, tree: snapshotTree(path) }]
      } catch {
        return []
      }
    })
  }

  /** The backstop: edit tools are blocked for read-only roles, but a shell command can still write. */
  private checkViolation(agent: string, before: { path: string; tree: string }[]): Violation | undefined {
    if (!this.record.enforce || !this.record.roster.implement || agent === this.record.roster.implement) return undefined
    const files = before.flatMap(({ path, tree }) => changed(path, tree, snapshotTree(path)))
    if (files.length === 0) return undefined
    const violation: Violation = { id: randomUUID(), agent, files, before }
    this.record.violations.push(violation)
    this.ledger.append({ from: 'agentdeck', text: `${agent} changed files its role does not allow: ${files.join('; ')}. The user can undo this.` })
    return violation
  }

  /** ACP agents only stop at permission requests, which full access skips. */
  private async applyRole(agent: string, sessionId: string): Promise<void> {
    if (agent === 'claude' || agent === 'codex' || !this.record.roster.implement || !this.record.enforce) return
    await this.deps.manager.setMode(sessionId, agent === this.record.roster.implement ? this.record.mode : 'ask').catch(() => undefined)
  }

  private activity(agent: string): string {
    const lines = rollingLines(this.latest.get(agent) ?? [], this.deps.root)
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

  /** The session's chat and agent, and the address its CLI connects to. */
  toolServer(record: SessionRecord, url: string): { name: string; url: string } | undefined {
    const found = this.memberOf(record.id)
    return found ? { name: 'agentdeck', url: `${url}/${found.chat.record.id}/${found.agent}` } : undefined
  }

  boundary(record: SessionRecord): WriteBoundary | undefined {
    const found = this.memberOf(record.id)
    return found?.chat.readOnlyBoundary(found.agent)
  }

  handleTool(caller: string, name: string, args: Record<string, unknown>): string {
    const [, chatId, agent] = /\/([\w-]+)\/([\w-]+)$/.exec(caller) ?? []
    const chat = chatId ? this.chats.get(chatId) : undefined
    return chat ? chat.handleTool(agent, name, args) : 'This chat is not open.'
  }

  private memberOf(sessionId: string): { chat: GroupChat; agent: string } | undefined {
    for (const chat of this.chats.values()) {
      const agent = Object.entries(chat.record.members).find(([, id]) => id === sessionId)?.[0]
      if (agent) return { chat, agent }
    }
    return undefined
  }

  create(options: { lead: string; title?: string; mode?: PermissionMode; laneId?: string; roster?: Roster; enforce?: boolean; verify?: string }): GroupChat {
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
      roster: options.roster ?? {},
      enforce: options.enforce ?? true,
      delegations: [],
      violations: [],
      ...(options.verify ? { verify: options.verify } : {}),
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
    const found = this.memberOf(record.id)
    return found ? found.chat.catchUp(found.agent, parts) : parts
  }

  dispose(): void {
    for (const chat of this.chats.values()) chat.dispose()
  }
}

