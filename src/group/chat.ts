import { execFile, execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { type Disposable, Emitter } from '../core/emitter'
import type { PermissionMode, PromptPart, PromptResponse, ProviderDefinition, SessionItem, Quota, WriteBoundary } from '../core/types'
import type { SessionEvent, SessionManager } from '../sessions/manager'
import type { SessionRecord, SessionStatus } from '../sessions/store'
import { catchUpText, Ledger } from './ledger'
import { parseMentions } from './mentions'
import { rollingLines } from './rolling'
import { activity, baseline, stop as stopProcesses, waitForSettled } from './settle'
import type { Tool } from './tool-server'

export type Delivery = 'now' | 'end-of-turn' | 'queued'
export type QueuedMessage = { id: string; target: string; text: string; delegation?: string; internal?: boolean; reportOf?: string; redirect?: boolean }

export const ROLES = ['research', 'plan', 'implement', 'review'] as const
export type Role = (typeof ROLES)[number]
export type Roster = Partial<Record<Role, string>>

export type DelegationStatus = 'queued' | 'running' | 'settling' | 'done' | 'blocked' | 'question' | 'overdue' | 'unknown' | 'failed' | 'interrupted' | 'stopped' | 'planned'
export type Facts = { files: string[]; commands: { command: string; failed: boolean }[]; verify?: { command: string; ok: boolean; output: string }; violations: string[]; stillRunning?: string[]; servicesLeft?: string[] }
export type Delegation = { id: string; lead: string; agent: string; role?: Role; task: string; doneWhen: string; context?: string; status: DelegationStatus; series?: string; phase?: number; phases?: number; report?: string; facts?: Facts; handoff?: string; rounds?: number; verified?: boolean; snapshots?: { path: string; before: string; after: string }[]; undone?: boolean; startedAt?: string; resuming?: boolean; added?: string[]; answers?: { question: string; answer: string; by: string }[] }
export type UserQuestion = { id: string; from: string; delegation?: string; question: string; itemId?: string }
export type Violation = { id: string; agent: string; files: string[]; before: { path: string; tree: string }[]; undone?: boolean; allowed?: boolean }

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
  /** Where delegate questions go first. Permissions always go to the user. */
  questionsTo: 'lead' | 'user'
  /** Questions waiting for the user. */
  userQuestions: UserQuestion[]
  /** Which lead was last told how this chat works. */
  briefed?: string
  /** The lead has been reminded once this turn to really delegate. */
  nudged?: boolean
  /** The reason the queue stopped, until the user retries. */
  blocked?: string
}

export type MemberState = { agent: string; status: SessionStatus; activity: string }
export type GroupState = { id: string; title: string; lead: string; target: string; running?: string; active: string[]; queue: QueuedMessage[]; members: MemberState[]; blocked?: string; laneId?: string; roster: Roster; delegations: Delegation[]; violations: Violation[]; userQuestions: UserQuestion[]; limited?: string; quotas: Record<string, Quota> }
export type TimelineItem = { agent: string; item: SessionItem }

export type GroupEvent = { type: 'item'; agent: string; item: SessionItem } | { type: 'state'; state: GroupState }

export type GroupDeps = {
  manager: SessionManager
  providers: ReadonlyMap<string, ProviderDefinition>
  dir: string
  /** Tool lines show paths relative to this. */
  root?: string
  /** Where a lane's code is: its checkouts, or the primary checkouts for a chat on no lane. */
  checkouts?: (lane: string | undefined) => string[]
  memoryDir?: (lane: string) => string
  /** How long AgentDeck waits for background work before telling the lead. */
  settleLimitMs?: number
  /** Off only in tests that have no real processes to watch. */
  watchProcesses?: boolean
  quota?: (agent: string) => Quota | undefined
}

/** Everything in a folder, untracked files included, without touching the working tree, the index, or the stash list. */
function snapshotTree(path: string): string {
  const index = join(realpathSync(tmpdir()), `agentdeck-index-${process.pid}-${randomUUID()}`)
  const git = (args: string[]) => execFileSync('git', args, { cwd: path, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], env: { ...process.env, GIT_INDEX_FILE: index } }).trim()
  try {
    // Starting from the checkout's own index, Git only rehashes what changed: seconds become milliseconds on large repos.
    const own = execFileSync('git', ['rev-parse', '--path-format=absolute', '--git-path', 'index'], { cwd: path, encoding: 'utf8' }).trim()
    if (existsSync(own)) copyFileSync(own, index)
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

/** Shorter than this, a delegation's context cannot hold findings or a plan. */
const MIN_CONTEXT = 80

/** What the lead must give each role. */
const NEEDS: Record<Role | 'other', string> = {
  research: 'the questions to answer and what is already known',
  plan: 'the goal, the constraints, and what is already known',
  implement: 'your findings and the implementation plan: files to change, the approach, the steps, and facts you verified',
  review: 'what changed, where, and the plan or requirements to check it against',
  other: 'the goal, what is already known, and what to do'
}

/** How each role works from the lead's context. */
const GUIDE: Record<Role | 'other', string> = {
  research: 'Answer the questions in the context. Report findings with file paths and evidence. Do not edit files.',
  plan: 'Write a concrete plan from the context: files, approach, steps, and risks. Do not edit code.',
  implement: 'The lead has done the research and written the plan above. Go straight to the change: read only the files the plan names or the change needs, and do not re-research the codebase. If the plan is wrong or something you need is missing, stop with STATUS: question and say what.',
  review: 'Check the change against the plan above. Read the diff and the files it touches. Report problems with file and line, and say plainly when it passes. Do not edit files.',
  other: 'Work from the context above. If something you need is missing, stop with STATUS: question and say what.'
}

const MAX_QUESTION_ROUNDS = 5
const DEFAULT_SETTLE_MS = 120_000
const BACKGROUND_GRACE_MS = 2_000
/** The live activity line only needs the latest items, however long the session. */
const ACTIVITY_WINDOW = 200

const NARRATE = 'Before each step, say in one short line what you are doing or what you just found.'
const SAID_DELEGATE = /\b(hand(ing)?( it| this| that)? (off|over)|delegat(e|ing)|pass(ing)? (it|this) to)\b/i

/** The tools every provider's CLI can call. `caller` carries which chat and agent is calling. */
export function groupTools(handle: (caller: string, name: string, args: Record<string, unknown>) => string): Tool[] {
  return [
    {
      name: 'delegate',
      description: 'Hands work to another agent in this chat, by role or by name. It returns at once. End your turn right after; the report starts your next turn.',
      inputSchema: {
        type: 'object',
        properties: {
          to: { type: 'string', description: 'A role (research, plan, implement, review) or an agent name.' },
          task: { type: 'string' },
          doneWhen: { type: 'string' },
          phases: {
            type: 'array',
            description: 'For a plan with several phases: one entry per phase, in order. AgentDeck hands them over one at a time and starts the next only when the last reports done and its checks pass.',
            items: { type: 'object', properties: { task: { type: 'string' }, doneWhen: { type: 'string' } }, required: ['task'] }
          },
          context: { type: 'string', description: 'Everything the delegate needs for its role, so it can start at once. Implement: your findings and the plan (files, approach, steps, facts you verified). Review: what changed and what to check it against. Research: the questions and what is already known.' }
        },
        required: ['to', 'task', 'context']
      },
      call: (args, caller) => handle(caller, 'delegate', args)
    },
    {
      name: 'commit_work',
      description: 'Commits everything changed in this lane, including new files. Use this when your sandbox cannot run git commit. Only the agent allowed to write can use it.',
      inputSchema: { type: 'object', properties: { message: { type: 'string' } }, required: ['message'] },
      call: (args, caller) => handle(caller, 'commit_work', args)
    },
    {
      name: 'answer_delegate',
      description: 'Answers a question from a delegate, when this conversation already settles it. Cite where. Never guess at a product decision.',
      inputSchema: { type: 'object', properties: { agent: { type: 'string' }, answer: { type: 'string' } }, required: ['agent', 'answer'] },
      call: (args, caller) => handle(caller, 'answer_delegate', args)
    },
    {
      name: 'ask_user',
      description: 'Sends a delegate question to the user, when this conversation does not settle it.',
      inputSchema: { type: 'object', properties: { agent: { type: 'string' }, question: { type: 'string' } }, required: ['question'] },
      call: (args, caller) => handle(caller, 'ask_user', args)
    },
    {
      name: 'message_delegate',
      description: 'Sends more instructions to a delegate, in the same session it has been working in.',
      inputSchema: { type: 'object', properties: { agent: { type: 'string' }, text: { type: 'string' } }, required: ['agent', 'text'] },
      call: (args, caller) => handle(caller, 'message_delegate', args)
    },
    {
      name: 'stop_work',
      description: 'Stops background work and servers a delegate left running in this chat. A shell and its children stop together.',
      inputSchema: { type: 'object', properties: { pid: { type: 'number', description: 'Only this process and what the record shows as work; omit for everything left running.' } } },
      call: (args, caller) => handle(caller, 'stop_work', args)
    }
  ]
}

type Turn = { agent: string; entry: number; started: boolean; delegation?: string; itemsAtStart: number; before: { path: string; tree: string; outsideLane?: boolean }[]; processes: Set<number>; stopped?: boolean; overlapped?: boolean }

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
  /** Agents working now, each on its own turn. Read-only agents run alongside others; two writers never do. */
  private readonly running = new Map<string, Turn>()
  private limited: string | undefined
  private readonly starting = new Set<string>()
  /** Facts settling found, per delegation, for its report. */
  private readonly pendingFacts = new Map<string, Pick<Facts, 'stillRunning' | 'servicesLeft'>>()

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

  private get watchesProcesses(): boolean {
    // Process watching reads `ps` and `lsof`, which Windows lacks.
    return this.deps.watchProcesses !== false && process.platform !== 'win32'
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
      ...(this.running.size > 0 ? { running: [...this.running.keys()].at(-1) } : {}),
      active: [...this.running.keys()],
      ...(record.blocked ? { blocked: record.blocked } : {}),
      ...(record.laneId ? { laneId: record.laneId } : {}),
      roster: record.roster,
      delegations: record.delegations,
      violations: record.violations,
      userQuestions: record.userQuestions,
      ...(this.limited ? { limited: this.limited } : {}),
      quotas: Object.fromEntries(Object.keys(record.members).flatMap((agent) => {
        const quota = this.deps.quota?.(agent)
        return quota ? [[agent, quota]] : []
      }))
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

  /** Sends a message at once: each `@agent` part to that agent, the rest to the lead. Says when each part arrives. */
  async send(text: string): Promise<{ id: string; target: string; delivery: Delivery }[]> {
    this.record.nudged = false
    const results: { id: string; target: string; delivery: Delivery }[] = []
    for (const segment of parseMentions(text, this.agents)) {
      const target = segment.target ?? this.record.lead
      // The mention stays in the text, so the message reads as written in the chat and in everyone's catch-up.
      const queued: QueuedMessage = { id: randomUUID(), target, text: segment.target ? `@${segment.target} ${segment.text}` : segment.text }
      results.push({ id: queued.id, target, delivery: await this.deliver(queued) })
    }
    this.save()
    this.changed()
    void this.pump()
    return results
  }

  private async deliver(message: QueuedMessage): Promise<Delivery> {
    const running = this.running.has(message.target) && this.statuses.get(message.target) === 'running'
    if (running && this.deps.providers.get(message.target)?.capabilities.has('steer')) {
      await this.steer(message)
      return 'now'
    }
    if (running) {
      // It cannot take a message mid-turn: stop it, and the message starts its next turn at once.
      this.record.queue.unshift(message)
      this.save()
      await this.deps.manager.cancel(this.record.members[message.target])
      return 'now'
    }
    this.record.queue.push(message)
    await this.pump()
    // Still waiting only when its agent is busy with an earlier message, or another writer is working.
    return this.record.queue.includes(message) ? 'queued' : 'now'
  }

  /** Whether an agent may start now: anyone read-only may; one that can write waits while another writer works. */
  private canStart(agent: string): boolean {
    const writes = (candidate: string) => !this.readOnlyBoundary(candidate)
    if (!writes(agent)) return true
    return ![...this.running.keys(), ...this.starting].some((other) => other !== agent && writes(other))
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
    if (index < 0 || !this.running.has(this.record.queue[index].target)) return
    const [message] = this.record.queue.splice(index, 1)
    this.record.queue.unshift(message)
    this.save()
    await this.deps.manager.cancel(this.record.members[message.target])
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
    for (const [agent, turn] of this.running) {
      turn.stopped = true
      await this.deps.manager.cancel(this.record.members[agent])
    }
  }

  /** Sends a message, stopping the agent it is for if that agent is working, so it goes now. */
  async sendNow(text: string): Promise<void> {
    const results = await this.send(text)
    const forRunning = results.find((result) => this.running.has(result.target) && result.delivery !== 'now')
    if (forRunning) await this.stopAndSend(forRunning.id)
  }

  /** Carries on a delegate the user stopped, in the same session. */
  resumeDelegation(id: string): void {
    const delegation = this.record.delegations.find((candidate) => candidate.id === id)
    if (delegation?.status !== 'stopped') return
    this.resumeDelegate(delegation, 'You were stopped by the user partway through. Check what got done, then carry on with the task. End with a STATUS line as before.')
  }

  /** Drops a delegate that has not started. */
  cancelDelegation(id: string): void {
    const delegation = this.record.delegations.find((candidate) => candidate.id === id)
    if (delegation?.status !== 'queued') return
    delegation.status = 'stopped'
    this.record.queue = this.record.queue.filter((message) => message.delegation !== id)
    this.ledger.append({ from: 'user', text: `Cancelled ${delegation.agent}'s task before it started: ${delegation.task}` })
    this.save()
    this.changed()
  }

  /** The user answers a delegate's question themselves; the lead's pending turn about it is dropped. */
  answerDelegate(id: string, answer: string): void {
    const delegation = this.record.delegations.find((candidate) => candidate.id === id)
    if (!delegation || (delegation.status !== 'question' && delegation.status !== 'blocked')) return
    this.record.queue = this.record.queue.filter((message) => message.reportOf !== id)
    this.record.userQuestions = this.record.userQuestions.filter((question) => question.delegation !== id)
    this.ledger.append({ from: 'user', to: delegation.agent, text: `Answer: ${answer}` })
    this.recordAnswer(delegation, answer, 'user')
    this.resumeDelegate(delegation, `The user answered your question: ${answer}\nCarry on. End with a STATUS line as before.`)
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
    if (name === 'commit_work') return this.commitWork(agent, String(args.message ?? ''))
    if (agent === this.record.lead) {
      if (name === 'answer_delegate') return this.leadAnswers(String(args.agent ?? ''), String(args.answer ?? ''))
      if (name === 'ask_user') return this.askUser(String(args.agent ?? ''), String(args.question ?? ''))
      if (name === 'message_delegate') return this.leadMessages(String(args.agent ?? ''), String(args.text ?? ''))
      if (name === 'stop_work') {
        void this.stopWork()
        return 'Stopping what was left running. End your turn now.'
      }
    } else if (['answer_delegate', 'ask_user', 'message_delegate', 'stop_work'].includes(name)) return `Only the lead (${this.record.lead}) can do this.`
    if (name !== 'delegate') return `Unknown tool ${name}.`
    if (agent !== this.record.lead) return `Only the lead (${this.record.lead}) can delegate.`
    const to = String(args.to ?? '').toLowerCase()
    const role = ROLES.find((candidate) => candidate === to)
    const target = role ? this.record.roster[role] : this.agents.find((candidate) => candidate === to)
    if (!target) return `Nobody holds "${to}". Roster: ${this.rosterText()}.`
    if (target === agent) return `That is you: do this work yourself, without delegating.`
    const limit = this.quotaWarning(target)
    const held = role ?? ROLES.find((candidate) => this.record.roster[candidate] === target)
    const context = String(args.context ?? '').trim()
    // A delegate should start on its work, not rediscover what the lead already knows.
    if (context.length < MIN_CONTEXT) return `Not sent: give ${target} what it needs as \`context\`: ${NEEDS[held ?? 'other']}. Research it yourself first, or delegate the research.`
    const base = { lead: agent, agent: target, ...(held ? { role: held } : {}), context }
    const phases = Array.isArray(args.phases) ? args.phases.filter((phase): phase is { task: string; doneWhen?: string } => typeof phase === 'object' && phase !== null && typeof (phase as { task?: unknown }).task === 'string') : []
    if (phases.length > 1) {
      const series = randomUUID()
      for (const [index, phase] of phases.entries()) {
        this.record.delegations.push({ id: randomUUID(), ...base, task: phase.task, doneWhen: String(phase.doneWhen ?? ''), status: index === 0 ? 'queued' : 'planned', series, phase: index + 1, phases: phases.length })
      }
    } else {
      this.record.delegations.push({ id: randomUUID(), ...base, task: String(phases[0]?.task ?? args.task ?? ''), doneWhen: String(phases[0]?.doneWhen ?? args.doneWhen ?? ''), status: 'queued' })
    }
    this.save()
    this.changed()
    const how = phases.length > 1 ? ` in ${phases.length} phases, one at a time` : ''
    return `Accepted: ${target} will do this${how}.${limit ? ` Warning: ${limit}` : ''} End your turn now; its report starts your next turn.`
  }

  private quotaWarning(agent: string): string | undefined {
    const limited = this.deps.quota?.(agent)?.windows.find((window) => window.status !== 'ok')
    return limited ? `${agent} is ${limited.status === 'limited' ? 'at its limit' : 'close to its limit'} (${limited.label}: ${limited.usedPercent}% used).` : undefined
  }

  private leadAnswers(agent: string, answer: string): string {
    const delegation = this.waitingOn(agent)
    if (!delegation) return `${agent} is not waiting on a question.`
    this.ledger.append({ from: this.record.lead, to: agent, text: `Answer: ${answer}` })
    this.recordAnswer(delegation, answer, this.record.lead)
    this.resumeDelegate(delegation, `The lead answered your question: ${answer}\nCarry on. End with a STATUS line as before.`)
    return 'Sent. End your turn now.'
  }

  private recordAnswer(delegation: Delegation, answer: string, by: string): void {
    const question = /STATUS:\s*question\W*(.*)/i.exec(delegation.report ?? '')?.[1]?.trim() || delegation.report || ''
    delegation.answers = [...(delegation.answers ?? []), { question, answer, by }]
  }

  private askUser(agent: string, question: string): string {
    const delegation = this.waitingOn(agent)
    this.record.userQuestions.push({ id: randomUUID(), from: agent || this.record.lead, question, ...(delegation ? { delegation: delegation.id } : {}) })
    this.save()
    this.changed()
    return 'Sent to the user. End your turn now; their answer reaches the agent that asked.'
  }

  /** The user answers a question that came to them, and the agent that asked carries on. */
  answerQuestion(id: string, answer: string): void {
    const question = this.record.userQuestions.find((candidate) => candidate.id === id)
    if (!question) return
    this.record.userQuestions = this.record.userQuestions.filter((candidate) => candidate.id !== id)
    this.ledger.append({ from: 'user', to: question.from, text: `Answer to "${question.question}": ${answer}` })
    if (question.itemId) {
      const item = this.deps.manager.item(this.record.members[question.from], question.itemId)
      if (item?.kind === 'question') this.answer(question.from, question.itemId, { kind: 'answers', answers: item.questions.map((asked) => ({ questionId: asked.id, optionIds: [], other: answer })) })
    } else {
      const delegation = this.record.delegations.find((candidate) => candidate.id === question.delegation)
      if (delegation) this.recordAnswer(delegation, answer, 'user')
      if (delegation) this.resumeDelegate(delegation, `The user answered your question: ${answer}\nCarry on. End with a STATUS line as before.`)
      else this.record.queue.unshift({ id: randomUUID(), target: question.from, text: answer })
    }
    this.save()
    this.changed()
    void this.pump()
  }

  private leadMessages(agent: string, text: string): string {
    if (!this.record.members[agent]) return `${agent} has not worked in this chat yet: delegate to it instead.`
    // More instructions reopen the delegate's latest task, so its next reply is tracked and reported like the first.
    const delegation = [...this.record.delegations].reverse().find((candidate) => candidate.agent === agent && candidate.status !== 'planned')
    const reopen = delegation && !delegation.undone && !['running', 'settling', 'queued'].includes(delegation.status) ? delegation : undefined
    if (reopen) reopen.status = 'queued'
    this.record.queue.push({ id: randomUUID(), target: agent, text, internal: true, ...(reopen ? { delegation: reopen.id } : {}) })
    this.save()
    this.changed()
    return `Sent to ${agent}. End your turn now.`
  }

  /** Stops what a delegate left running. Stops every process seen as this turn's work, never just one. */
  private async stopWork(): Promise<void> {
    const left = this.record.delegations.flatMap((delegation) => [...(delegation.facts?.stillRunning ?? []), ...(delegation.facts?.servicesLeft ?? [])])
    stopProcesses(left.flatMap((entry) => {
      const pid = Number(entry.split(' ')[0])
      return Number.isFinite(pid) ? [pid] : []
    }))
    for (const delegation of this.record.delegations) {
      if (delegation.facts) {
        delete delegation.facts.stillRunning
        delete delegation.facts.servicesLeft
      }
    }
    this.ledger.append({ from: 'agentdeck', text: 'Stopped what delegates left running.' })
    this.save()
    this.changed()
  }

  private waitingOn(agent: string): Delegation | undefined {
    return [...this.record.delegations].reverse().find((delegation) => delegation.agent === agent && (delegation.status === 'question' || delegation.status === 'blocked'))
  }

  private resumeDelegate(delegation: Delegation, text: string): void {
    delegation.status = 'queued'
    this.record.queue.unshift({ id: randomUUID(), target: delegation.agent, text, delegation: delegation.id, internal: true })
    this.save()
    this.changed()
    void this.pump()
  }

  /** After a restart nothing is running: an interrupted delegate resumes its session and is told to ask again. */
  resumeAfterRestart(): void {
    for (const delegation of this.record.delegations) {
      if (delegation.status !== 'running' && delegation.status !== 'settling') continue
      delegation.resuming = true
      this.resumeDelegate(delegation, 'AgentDeck restarted while you were working. Check what got done, then finish. If you were waiting for an approval or an answer, ask again. End with a STATUS line.')
    }
  }

  /** Commits for an agent whose sandbox protects Git's own files. Never amends, resets, or pushes. */
  private commitWork(agent: string, message: string): string {
    const writer = this.record.roster.implement
    if (this.record.enforce && writer && agent !== writer) return `Only ${writer} can commit here.`
    if (!message.trim()) return 'A commit message is required.'
    const done: string[] = []
    for (const path of this.deps.checkouts?.(this.record.laneId) ?? []) {
      try {
        const git = (args: string[]) => execFileSync('git', args, { cwd: path, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim()
        if (!git(['status', '--porcelain'])) continue
        git(['add', '-A'])
        git(['commit', '-m', message])
        done.push(git(['log', '-1', '--format=%h']))
      } catch (error) {
        return `The commit failed in ${path}: ${(error as Error).message.split('\n')[0]}`
      }
    }
    return done.length > 0 ? `Committed ${done.join(', ')}.` : 'Nothing to commit.'
  }

  /** Read-only for anyone but the Implement agent, when roles are enforced. */
  readOnlyBoundary(agent: string): WriteBoundary | undefined {
    if (!this.record.enforce || !this.record.roster.implement || agent === this.record.roster.implement) return undefined
    const writer = this.record.roster.implement
    return { roots: [], except: [], outside: async () => `Your role is read-only here. ${agent === this.record.lead ? `Delegate this edit to ${writer}.` : `Report what should change; ${writer} edits code.`}` }
  }

  /** What each delegate changed, as a diff, with its report and the facts AgentDeck recorded. */
  review(): { delegation: Delegation; diff: string }[] {
    return this.record.delegations.flatMap((delegation) => {
      if (!delegation.snapshots) return []
      const diff = delegation.snapshots.map(({ path, before, after }) => execFileSync('git', ['diff', before, after], { cwd: path, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })).join('')
      return [{ delegation, diff }]
    })
  }

  /** Reverses one delegate's changes, keeping later work. Refuses, changing nothing, when later edits overlap. */
  undoDelegation(id: string): string {
    const delegation = this.record.delegations.find((candidate) => candidate.id === id)
    if (!delegation?.snapshots || delegation.undone) return 'Nothing to undo.'
    const patches = delegation.snapshots.map(({ path, before, after }) => ({ path, patch: execFileSync('git', ['diff', '--binary', before, after], { cwd: path, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }) }))
    for (const { path, patch } of patches) {
      if (!patch) continue
      try {
        execFileSync('git', ['apply', '-R', '--check'], { cwd: path, input: patch, stdio: ['pipe', 'ignore', 'pipe'] })
      } catch {
        return `Later changes overlap ${delegation.agent}'s, so nothing was undone. Review the diff and undo by hand.`
      }
    }
    for (const { path, patch } of patches) if (patch) execFileSync('git', ['apply', '-R'], { cwd: path, input: patch })
    delegation.undone = true
    this.ledger.append({ from: 'user', text: `Undid ${delegation.agent}'s changes for: ${delegation.task}` })
    this.save()
    this.changed()
    return `Undid ${delegation.agent}'s changes.`
  }

  /** Puts files back after a write the role did not allow. */
  /** Keeps a write the role did not allow, this once. */
  allowViolation(id: string): void {
    const violation = this.record.violations.find((candidate) => candidate.id === id)
    if (!violation || violation.undone) return
    violation.allowed = true
    this.ledger.append({ from: 'user', text: `Allowed ${violation.agent}'s change to ${violation.files.join(', ')} this time.` })
    this.save()
    this.changed()
  }

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
    return `You lead a group chat of coding agents run by AgentDeck, and you own the work you hand out. Roster: ${this.rosterText()}. You own the research and the plan: before handing out implementation, find out what the change needs (yourself, or by delegating research), then pass your findings and a concrete plan in the delegate tool's context, so the implementer goes straight to the change. For a plan with several phases, pass them as phases: they are handed over one at a time, which keeps each delegate on track. Give every delegate the context its role needs, and answer its questions from what you know.${writer && this.record.enforce && writer !== agent ? ` Only ${writer} may edit code; you are read-only.` : ''} When work belongs to another agent, call the delegate tool from the agentdeck MCP server with its role, without asking the user, then end your turn. Reports start your next turn: read them, judge them against what AgentDeck recorded, and decide what happens next.`
  }

  private delegationText(delegation: Delegation): string {
    return `You are ${delegation.agent}, delegated this by ${delegation.lead} in a group chat run by AgentDeck${delegation.role ? `, in the ${delegation.role} role` : ''}.\nTask: ${delegation.phase ? `Phase ${delegation.phase} of ${delegation.phases}: ` : ''}${delegation.task}${delegation.phase ? `\nDo only this phase. The whole plan, for reference: ${this.seriesOf(delegation).map((phase) => `${phase.phase}. ${phase.task}`).join(' ')}` : ''}${delegation.doneWhen ? `\nDone when: ${delegation.doneWhen}` : ''}${delegation.context ? `\n\nContext from ${delegation.lead}:\n${delegation.context}` : ''}\n\n${GUIDE[delegation.role ?? 'other']}\n${NARRATE}\nWhen you stop, end your reply with one line: STATUS: done, STATUS: blocked, or STATUS: question, followed by the reason or question. Only say done for what you actually did and checked. If your sandbox cannot run git commit, use the commit_work tool from the agentdeck MCP server.`
  }

  /** The manager's `decorate` hook for one member: what this agent missed, ahead of what it is told. */
  catchUp(agent: string, parts: PromptPart[]): PromptPart[] {
    const cursor = this.record.cursors[agent] ?? 0
    const missed = this.ledger.missed(cursor, agent, this.running.get(agent)?.entry)
    const text = catchUpText(missed, join(this.deps.dir, this.record.id, 'ledger.jsonl'))
    // What AgentDeck put in a delegate's first prompt, for the handoff panel.
    const starting = this.record.delegations.find((delegation) => delegation.agent === agent && delegation.status === 'running' && !delegation.added)
    if (starting) {
      starting.added = [
        ...(missed.length > 0 ? [`${missed.length} ${missed.length === 1 ? 'message' : 'messages'} from the chat, word for word`] : []),
        ...(this.record.laneId ? [`The ${this.record.laneId} lane: goal, plan, notes, and what changed`] : [])
      ]
    }
    this.record.cursors[agent] = this.ledger.length
    const brief = agent === this.record.lead && Object.keys(this.record.roster).length > 0 && this.record.briefed !== agent
    if (brief) this.record.briefed = agent
    this.save()
    return [...(brief ? [{ type: 'text' as const, text: this.leadBrief(agent) }] : []), ...(text ? [{ type: 'text' as const, text }] : []), ...parts]
  }

  /** Starts every waiting message that can go now: the first one for each idle agent, in queue order. */
  private async pump(): Promise<void> {
    if (this.record.blocked) return
    const chosen = new Set<string>()
    for (const next of [...this.record.queue]) {
      const agent = next.target
      if (chosen.has(agent) || this.running.has(agent) || this.starting.has(agent) || !this.canStart(agent)) {
        chosen.add(agent)
        continue
      }
      chosen.add(agent)
      this.record.queue = this.record.queue.filter((message) => message.id !== next.id)
      this.starting.add(agent)
      void this.start(next).finally(() => this.starting.delete(agent))
    }
  }

  private async start(next: QueuedMessage): Promise<void> {
    const sessionId = await this.member(next.target)
    const delegation = next.delegation ? this.record.delegations.find((candidate) => candidate.id === next.delegation) : undefined
    let processes = new Set<number>()
    if (this.watchesProcesses) {
      // The CLI and its helpers are running first, so they do not count as this turn's work.
      await this.deps.manager.warm(sessionId).catch(() => undefined)
      processes = await baseline(this.deps.root ?? process.cwd()).catch(() => processes)
    }
    const entry = this.ledger.append(next.internal ? { from: 'agentdeck', to: next.target, text: next.text } : next.redirect ? { from: 'user', to: next.target, text: next.text } : delegation ? { from: delegation.lead, to: next.target, text: `${delegation.task}` } : { from: 'user', to: next.target, text: next.text })
    if (delegation) {
      delegation.status = 'running'
      delegation.startedAt = new Date().toISOString()
    }
    // Changes made while another agent also worked cannot be told apart, so neither turn flags the other's writes.
    const others = [...this.running.values()]
    for (const other of others) other.overlapped = true
    this.running.set(next.target, { agent: next.target, entry: entry.seq, started: false, ...(delegation ? { delegation: delegation.id } : {}), itemsAtStart: this.latest.get(next.target)?.length ?? 0, before: this.snapshot(), processes, ...(others.length > 0 ? { overlapped: true } : {}) })
    await this.applyRole(next.target, sessionId)
    this.save()
    this.changed()
    await this.deps.manager.prompt(sessionId, [{ type: 'text', text: next.text }])
  }

  /** The agent's session in this chat, created if it has none yet, so its model and mode can be set before it works. */
  ensureMember(agent: string): Promise<string> {
    return this.member(agent)
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
    if (item.kind === 'notice' && item.level === 'error' && /rate.?limit|usage limit|quota/i.test(item.text)) {
      this.limited = `${agent} hit a limit: ${item.text}. Retry later, give the work to another agent, or sign in again if your plan changed.`
      this.record.blocked = this.limited
      this.save()
      this.changed()
    }
    if (item.kind === 'question' && !item.resolved) this.routeQuestion(agent, item)
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

  /** A provider's own question tool leaves the agent paused. The lead may answer from the chat; otherwise it comes to the user. */
  private routeQuestion(agent: string, item: Extract<SessionItem, { kind: 'question' }>): void {
    if (this.record.userQuestions.some((question) => question.itemId === item.id)) return
    this.record.userQuestions.push({ id: randomUUID(), from: agent, itemId: item.id, question: item.questions.map((question) => question.question).join(' ') })
    this.save()
    this.changed()
  }

  private onStatus(agent: string, status: SessionStatus): void {
    this.statuses.set(agent, status)
    const current = this.running.get(agent)
    if (current && isBusy(status)) current.started = true
    if (current?.started && !isBusy(status)) {
      void this.turnFinished(agent, status, current)
      return
    }
    this.changed()
  }

  private async turnFinished(agent: string, status: SessionStatus, current: Turn): Promise<void> {
    const reply = this.deps.manager.lastReply(this.record.members[agent])
    if (reply) this.ledger.append({ from: agent, text: reply })
    const violation = current.overlapped ? undefined : this.checkViolation(agent, current.before)
    if (status === 'error') this.record.blocked = `${agent} stopped with an error.`
    const delegation = current.delegation ? this.record.delegations.find((candidate) => candidate.id === current.delegation) : undefined
    // A message for the delegate ended its turn early (a redirect). The delegation is not over: it carries on with that message.
    const next = this.record.queue.find((message) => message.target === agent)
    if (delegation && status !== 'error' && !current.stopped && !/STATUS:/i.test(reply ?? '') && next && !next.delegation) {
      next.delegation = delegation.id
      if (!next.internal) next.redirect = true
      delegation.status = 'queued'
      this.running.delete(agent)
      this.save()
      this.changed()
      void this.pump()
      return
    }
    if (delegation) {
      const carryOn = await this.settle(delegation, status, current)
      if (carryOn) {
        this.running.delete(agent)
        this.save()
        this.changed()
        void this.pump()
        return
      }
      await this.finishDelegation(delegation, agent, status, reply ?? '', current, violation)
    }
    this.running.delete(agent)
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

  /**
   * "Done" is a claim. Waits for work the turn left running. If some ran on after the agent stopped, the same agent
   * gets one more turn to check the results and correct its report. Returns true when that turn is queued.
   */
  private async settle(delegation: Delegation, status: SessionStatus, current: Turn): Promise<boolean> {
    if (status === 'error' || !this.watchesProcesses || !this.deps.root) return false
    const root = this.deps.root
    delegation.status = 'settling'
    this.changed()
    // Shells and helpers wind down as a turn ends; only what outlives this pause counts as background work.
    await new Promise((resolve) => setTimeout(resolve, BACKGROUND_GRACE_MS))
    const first = await activity(root, current.processes)
    const outcome = await waitForSettled(root, current.processes, this.deps.settleLimitMs ?? DEFAULT_SETTLE_MS)
    const describe = (proc: { pid: number; command: string }) => `${proc.pid} ${proc.command.slice(0, 80)}`
    const services = outcome.activity.services.map((proc) => `${proc.pid} ${proc.command.slice(0, 80)} (port ${proc.ports.join(',')})`)
    current.processes = new Set([...current.processes])
    if (!outcome.settled) {
      delegation.status = 'overdue'
      this.pendingFacts.set(delegation.id, { stillRunning: outcome.activity.work.map(describe), servicesLeft: services })
      return false
    }
    this.pendingFacts.set(delegation.id, services.length > 0 ? { servicesLeft: services } : {})
    if (first.work.length > 0 && !delegation.verified) {
      delegation.verified = true
      delegation.status = 'running'
      this.record.queue.unshift({ id: randomUUID(), target: delegation.agent, delegation: delegation.id, internal: true, text: 'The background work you started has now really finished. Check its results, not just that it ran, and correct your report. End with a STATUS line: done only if it succeeded.' })
      return true
    }
    return false
  }

  /** A lead that says it will delegate but has not called the tool gets one reminder. */
  private afterLeadTurn(agent: string, reply: string): void {
    if (agent !== this.record.lead || this.record.nudged || !SAID_DELEGATE.test(reply)) return
    if (this.record.delegations.some((candidate) => candidate.status === 'queued')) return
    this.record.nudged = true
    this.record.queue.unshift({ id: randomUUID(), target: agent, internal: true, text: 'You said you would hand this off, but no delegate call reached AgentDeck. Call the delegate tool now if you meant to; otherwise carry on.' })
  }

  private async finishDelegation(delegation: Delegation, agent: string, status: SessionStatus, reply: string, current: Turn, violation: Violation | undefined): Promise<void> {
    const items = (this.latest.get(agent) ?? []).slice(current.itemsAtStart)
    const commands = items.flatMap((item) => (item.kind === 'tool' && (item.toolKind === 'execute' || item.title.startsWith('Run ') || item.title.startsWith('Bash ')) ? [{ command: item.title.replace(/^(Bash|Run|Command Execute)\s+/, '').split('\n')[0].slice(0, 160), failed: item.status === 'failed' }] : []))
    const files = current.before.filter((entry) => !entry.outsideLane).flatMap(({ path, tree }) => changed(path, tree, snapshotTree(path)))
    delegation.snapshots = current.before.filter((entry) => !entry.outsideLane).map(({ path, tree }) => ({ path, before: tree, after: snapshotTree(path) }))
    const facts: Facts = { files, commands, violations: violation ? violation.files : [], ...this.pendingFacts.get(delegation.id) }
    this.pendingFacts.delete(delegation.id)
    if (this.record.verify && agent === this.record.roster.implement && files.length > 0) facts.verify = await this.runVerify(this.record.verify)
    delegation.facts = facts
    delegation.report = reply
    const stated = /STATUS:\s*(done|blocked|question)/i.exec(reply)?.[1]?.toLowerCase() as DelegationStatus | undefined
    if (delegation.status !== 'overdue') delegation.status = status === 'error' ? 'failed' : (stated ?? 'unknown')
    delegation.handoff = this.saveHandoff(delegation, items)
    if (status === 'error') return
    delete delegation.resuming
    // Stopped by the user: the work so far stays, and nothing happens until they say.
    if (current.stopped) {
      delegation.status = 'stopped'
      return
    }
    const asked = delegation.status === 'question' ? /STATUS:\s*question\W*(.*)/i.exec(reply)?.[1]?.trim() : undefined
    if (delegation.status === 'question') {
      delegation.rounds = (delegation.rounds ?? 0) + 1
      if (this.record.questionsTo === 'user' || delegation.rounds > MAX_QUESTION_ROUNDS) {
        this.record.userQuestions.push({ id: randomUUID(), from: agent, delegation: delegation.id, question: asked || reply })
        return
      }
    }
    // A phase that is done, checked, and clean hands straight on to the next; anything else goes to the lead.
    const next = this.seriesOf(delegation).find((phase) => phase.phase === (delegation.phase ?? 0) + 1 && phase.status === 'planned')
    const passed = delegation.status === 'done' && delegation.facts?.verify?.ok !== false && !delegation.facts?.violations.length
    if (next && passed) {
      next.status = 'queued'
      return
    }
    this.record.queue.unshift({ id: randomUUID(), target: delegation.lead, internal: true, text: this.reportText(delegation), reportOf: delegation.id })
  }

  /** The phases of the plan a delegation belongs to, in order. */
  private seriesOf(delegation: Delegation): Delegation[] {
    return delegation.series ? this.record.delegations.filter((candidate) => candidate.series === delegation.series).sort((a, b) => (a.phase ?? 0) - (b.phase ?? 0)) : []
  }

  private reportText(delegation: Delegation): string {
    const facts = delegation.facts
    const lines = [
      `Report from ${delegation.agent} on: ${delegation.phase ? `phase ${delegation.phase} of ${delegation.phases}, ` : ''}${delegation.task}`,
      ...this.seriesNote(delegation),
      delegation.report ?? '(no reply)',
      '',
      'Recorded by AgentDeck, not by the agent:',
      `Files changed: ${facts?.files.join('; ') || 'none'}`,
      `Commands run: ${facts?.commands.map((command) => `${command.command}${command.failed ? ' (failed)' : ''}`).join('; ') || 'none'}`,
      ...(facts?.verify ? [`AgentDeck ran ${facts.verify.command}: ${facts.verify.ok ? 'passed' : `FAILED\n${facts.verify.output}`}`] : []),
      ...(facts?.violations.length ? [`Writes it should not have made: ${facts.violations.join('; ')}`] : []),
      ...(facts?.stillRunning?.length ? [`Still running after AgentDeck stopped waiting: ${facts.stillRunning.join('; ')}. Decide whether to keep waiting or call stop_work.`] : []),
      ...(facts?.servicesLeft?.length ? [`Servers left running: ${facts.servicesLeft.join('; ')}. Stop them with stop_work when nothing needs them.`] : []),
      ...(delegation.status === 'question' ? [`${delegation.agent} is asking the question above and waiting. If this conversation already settles it, call answer_delegate and cite where. If not, or if it is a product decision, call ask_user. Never guess.`] : []),
      ...(delegation.status === 'unknown' ? ['It did not give a status line, so treat it as not finished until checked.'] : []),
      ...(delegation.handoff ? [`Full record: ${delegation.handoff}`] : []),
      '',
      'Tell the user the real result, and hand out what comes next if the roster calls for it. Do not repeat a claim the record does not support.'
    ]
    return lines.join('\n')
  }

  private seriesNote(delegation: Delegation): string[] {
    const series = this.seriesOf(delegation)
    if (series.length === 0) return []
    const held = series.filter((phase) => phase.status === 'planned')
    if (held.length === 0) return series.every((phase) => phase.status === 'done') ? [`All ${series.length} phases reported done; each was checked before the next began.`] : []
    return [`Phase ${held[0].phase} of ${series.length} is on hold until this one is sorted out. Send ${delegation.agent} back with message_delegate; the next phase starts when this one reports done and its checks pass.`]
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

  /** The lane's checkouts, plus the primary checkouts, where a stray command run from the workspace root lands. */
  private snapshot(): { path: string; tree: string; outsideLane?: boolean }[] {
    const lane = this.deps.checkouts?.(this.record.laneId) ?? []
    const others = this.record.laneId ? (this.deps.checkouts?.(undefined) ?? []).filter((path) => !lane.includes(path)) : []
    return [...lane, ...others].flatMap((path) => {
      try {
        return [{ path, tree: snapshotTree(path), ...(others.includes(path) ? { outsideLane: true } : {}) }]
      } catch {
        return []
      }
    })
  }

  /** The backstop: edit tools are blocked for read-only roles, but a shell command can still write. */
  private checkViolation(agent: string, before: { path: string; tree: string; outsideLane?: boolean }[]): Violation | undefined {
    const writer = !this.record.enforce || !this.record.roster.implement || agent === this.record.roster.implement
    const watched = writer ? before.filter((entry) => entry.outsideLane) : before
    const files = watched.flatMap(({ path, tree }) => changed(path, tree, snapshotTree(path)))
    if (files.length === 0) return undefined
    const violation: Violation = { id: randomUUID(), agent, files, before: watched }
    this.record.violations.push(violation)
    this.ledger.append({ from: 'agentdeck', text: `${agent} changed files it should not have: ${files.join('; ')}${writer ? ', outside its lane' : ''}. The user can undo this.` })
    return violation
  }

  /** ACP agents only stop at permission requests, which full access skips. */
  private async applyRole(agent: string, sessionId: string): Promise<void> {
    if (agent === 'claude' || agent === 'codex' || !this.record.roster.implement || !this.record.enforce) return
    await this.deps.manager.setMode(sessionId, agent === this.record.roster.implement ? this.record.mode : 'ask').catch(() => undefined)
  }

  private activity(agent: string): string {
    const lines = rollingLines((this.latest.get(agent) ?? []).slice(-ACTIVITY_WINDOW), this.deps.root)
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
      const record = { questionsTo: 'lead', userQuestions: [], ...JSON.parse(readFileSync(path, 'utf8')) } as GroupRecord
      const chat = new GroupChat(deps, record)
      this.chats.set(id, chat)
      chat.resumeAfterRestart()
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

  create(options: { lead: string; title?: string; mode?: PermissionMode; laneId?: string; roster?: Roster; enforce?: boolean; verify?: string; questionsTo?: 'lead' | 'user' }): GroupChat {
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
      questionsTo: options.questionsTo ?? 'lead',
      userQuestions: [],
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

