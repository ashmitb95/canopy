import { Fragment, type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { Conversation, ConversationContent, ConversationScrollButton } from '@/components/ai-elements/conversation'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { TooltipProvider } from '@/components/ui/tooltip'
import type { Delegation, GroupState, TimelineItem } from '../../../src/group/chat'
import { rollingLines } from '../../../src/group/rolling'
import { AttachmentsContext } from '../assets'
import { Codicon } from '../components/codicon'
import { ProviderAvatar } from '../components/provider-avatar'
import { send } from '../host'
import { Composer } from '../components/composer'
import { editInComposer } from '../composer/edit-bus'
import { useApprovalKeys } from '../items/approval-card'
import { useNow } from '../use-now'
import { ItemView } from '../items/item-view'
import type { ChatState } from '../state'

const ROLE_LABEL: Record<string, string> = { research: 'Research', plan: 'Plan', implement: 'Implement', review: 'Review' }
const WINDOW = 8
const name = (agent: string) => agent.charAt(0).toUpperCase() + agent.slice(1)

function roleOf(group: GroupState, agent: string): string {
  const roles = Object.entries(group.roster).flatMap(([role, holder]) => (holder === agent ? [ROLE_LABEL[role] ?? role] : []))
  return [agent === group.lead ? 'Lead' : undefined, ...roles].filter(Boolean).join(' · ')
}

function userText(entry: TimelineItem): string {
  return entry.item.kind === 'message' && entry.item.role === 'user' ? entry.item.parts.map((part) => ('text' in part ? part.text : '')).join(' ') : ''
}

/** Messages AgentDeck sent between agents. Handoffs and check-ins show as a band; reports and answers show on the card. */
function marker(entry: TimelineItem): 'handoff' | 'hidden' | 'checkin' | undefined {
  const text = userText(entry)
  if (!text) return undefined
  if (text.startsWith('You are ') && text.includes('delegated this by')) return 'handoff'
  if (text.startsWith('Report from ') || text.startsWith('The lead answered') || text.startsWith('The user answered')) return 'hidden'
  if (text.startsWith('The background work you started') || text.startsWith('AgentDeck restarted') || text.startsWith('You said you would hand this off')) return 'checkin'
  return undefined
}

const CHANGE: Record<string, string> = { A: 'new', M: 'changed', D: 'deleted', R: 'renamed' }

/** Git's `A\tpath` as `path (new)`. */
function fileChange(row: string): string {
  const [status, ...paths] = row.split('\t')
  return `${paths.join(' → ')} (${CHANGE[status[0]] ?? status})`
}

/** A delegate's own work shows in its card; the conversation keeps only what needs the user. */
function inCard(group: GroupState, entry: TimelineItem): boolean {
  if (entry.agent === group.lead || entry.item.kind === 'approval' || entry.item.kind === 'question') return false
  // The user's own messages always stay in the conversation, whoever they went to.
  if (entry.item.kind === 'message' && entry.item.role === 'user') return false
  return group.delegations.some((delegation) => delegation.agent === entry.agent)
}

function Band({ tone = 'band', action, children }: { tone?: 'band' | 'warning'; action?: ReactNode; children: ReactNode }) {
  return (
    <div className={`ml-8 flex min-h-7 flex-wrap items-center gap-2.5 rounded-lg px-3 py-2 ${tone === 'warning' ? 'bg-warning/12 text-warning' : 'bg-band'}`}>
      <span className="min-w-[12rem] flex-1 leading-[1.4]">{children}</span>
      {action}
    </div>
  )
}

function BandButton({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" className="h-8 shrink-0 rounded-md bg-control px-2.5 font-semibold text-foreground" onClick={onClick}>
      {children}
    </button>
  )
}

function Header({ group }: { group: GroupState }) {
  return (
    <header className="flex flex-wrap items-center gap-2 border-b border-control px-4 py-2.5">
      <strong className="mr-auto truncate text-[15px] font-bold">{group.title}</strong>
      {group.members.map((member) => {
        const active = group.active.length > 0 ? group.active.includes(member.agent) : group.lead === member.agent
        return (
          <span key={member.agent} title={`${name(member.agent)}: ${roleOf(group, member.agent) || 'In this chat'}`} className={`inline-flex h-10 items-center gap-[7px] rounded-lg px-2.5 max-[480px]:h-8 max-[480px]:px-1.5 ${active ? 'bg-primary text-primary-foreground' : 'bg-surface'}`}>
            <ProviderAvatar providerId={member.agent} className="size-5 rounded-md text-[10px]" />
            <span className="max-[480px]:hidden">
              <span className="block leading-[1.1] font-bold">{name(member.agent)}</span>
              <span className="block text-[11px] leading-[1.2]">{roleOf(group, member.agent) || 'In this chat'}</span>
            </span>
          </span>
        )
      })}
    </header>
  )
}

/** The newest lines, at most a few times a second, so a fast stream does not redraw on every token. */
function useBatched<T>(value: T, ms = 250): T {
  const [shown, setShown] = useState(value)
  const last = useRef(0)
  useEffect(() => {
    const wait = Math.max(0, last.current + ms - Date.now())
    const timer = setTimeout(() => {
      last.current = Date.now()
      setShown(value)
    }, wait)
    return () => clearTimeout(timer)
  }, [value, ms])
  return shown
}

function Rolling({ items, full }: { items: TimelineItem[]; full: boolean }) {
  const batched = useBatched(items)
  const all = useMemo(() => rollingLines(batched.map(({ item }) => item)), [batched])
  const box = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)
  // Follows the newest line unless the user has scrolled up to read.
  useEffect(() => {
    if (pinned.current && box.current) box.current.scrollTop = box.current.scrollHeight
  }, [all])
  if (all.length === 0) return null
  return (
    <div
      ref={box}
      tabIndex={0}
      aria-label="Live activity"
      aria-live="off"
      className={`mx-3 overflow-y-auto rounded-lg bg-band px-3 py-2.5 text-[12.5px] leading-[1.45] ${full ? 'max-h-[60vh]' : 'h-[186px]'}`}
      onScroll={(event) => {
        const element = event.currentTarget
        pinned.current = element.scrollHeight - element.scrollTop - element.clientHeight < 8
      }}
    >
      <div className="flex min-h-full flex-col justify-end gap-[3px]">
        {all.map((line) => (
          <div
            key={line.id}
            className={`flex min-w-0 items-baseline gap-2 ${line.kind === 'tool' ? 'font-mono font-medium' : ''} ${line.kind === 'output' ? 'pl-3.5 font-mono text-muted-foreground' : ''} ${line.kind === 'thought' ? 'text-muted-foreground' : ''} ${line.failed ? 'text-destructive' : ''}`}
          >
            <span className={`min-w-0 flex-1 overflow-hidden text-ellipsis ${full ? '' : 'whitespace-nowrap'}`}>
              {line.text}
              {line.live ? <span className="animate-pulse"> ▌</span> : null}
            </span>
            {line.stat ? <span className="shrink-0 font-mono text-[11.5px]">{line.stat}</span> : null}
          </div>
        ))}
      </div>
    </div>
  )
}

type CardMark = 'spin' | 'wait' | 'done' | 'needs' | 'fail' | 'stopped' | 'none'
type CardAction = { label: string; run: () => void; primary?: boolean } | { label: string; answer: true }
type CardState = { text: string; tone: string; mark: CardMark; actions: CardAction[]; time?: string }

function elapsed(since: string | undefined, now: number): string {
  if (!since) return ''
  const seconds = Math.max(0, Math.floor((now - Date.parse(since)) / 1000))
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

/** One card shape for every state: a status line, a status mark, and the actions that state allows. */
function cardState(group: GroupState, delegation: Delegation, items: TimelineItem[], now: number): CardState {
  const facts = delegation.facts
  const id = delegation.id
  const viewHandoff: CardAction = { label: 'View handoff', run: () => send({ type: 'viewHandoff', id }) }
  const undo: CardAction = { label: 'Undo changes', run: () => send({ type: 'undoDelegation', id }) }
  const review: CardAction = { label: 'Review', run: () => send({ type: 'openReview' }) }
  const changed = (facts?.files.length ?? 0) > 0 && !delegation.undone
  if (delegation.undone) return { text: 'Undone · its changes were reversed', tone: 'text-muted-foreground', mark: 'none', actions: delegation.handoff ? [viewHandoff] : [] }
  switch (delegation.status) {
    case 'running':
    case 'settling': {
      const asking = items.findLast(({ item }) => item.kind === 'approval' && !item.resolved)?.item
      if (asking?.kind === 'approval') return { text: `Needs permission: ${asking.title}`, tone: 'text-warning', mark: 'needs', actions: [] }
      if (delegation.resuming) return { text: 'Resuming after reload · session restored', tone: 'text-info', mark: 'spin', actions: [] }
      const activity = delegation.status === 'settling' ? 'Reported done, waiting for its work to finish' : group.members.find((member) => member.agent === delegation.agent)?.activity || 'Working'
      return { text: activity, time: elapsed(delegation.startedAt, now), tone: 'text-info', mark: 'spin', actions: [] }
    }
    case 'planned':
      return { text: `Starts when phase ${(delegation.phase ?? 2) - 1} is done and checked`, tone: 'text-muted-foreground', mark: 'wait', actions: [] }
    case 'queued':
      if (delegation.resuming) return { text: 'Resuming after reload · session restored', tone: 'text-info', mark: 'wait', actions: [] }
      return {
        text: `Up next, after ${name(group.running ?? delegation.lead)}`,
        tone: 'text-muted-foreground',
        mark: 'wait',
        actions: delegation.startedAt ? [] : [{ label: 'Cancel', run: () => send({ type: 'cancelDelegation', id }) }]
      }
    case 'question': {
      const toUser = group.userQuestions.some((question) => question.delegation === id)
      if (toUser && (delegation.rounds ?? 0) > 5) return { text: 'Paused: too many rounds with the lead', tone: 'text-warning', mark: 'needs', actions: delegation.handoff ? [{ label: 'Open', run: () => send({ type: 'viewHandoff', id }) }] : [] }
      if (toUser) return { text: `Needs your answer: ${name(delegation.lead)} could not decide`, tone: 'text-warning', mark: 'needs', actions: [] }
      return { text: `Asked ${name(delegation.lead)} · waiting for an answer`, tone: 'text-info', mark: 'wait', actions: [{ label: 'Answer myself', answer: true }] }
    }
    case 'blocked':
      return { text: `Blocked: ${(delegation.report ?? '').match(/STATUS:\s*blocked\W*(.*)/i)?.[1] || 'it cannot go on'}`, tone: 'text-warning', mark: 'needs', actions: [{ label: 'Answer myself', answer: true }] }
    case 'done': {
      const failedCheck = facts?.verify && !facts.verify.ok
      const parts = ['Report ready', ...(facts ? [`${facts.files.length} ${facts.files.length === 1 ? 'file' : 'files'}`] : []), ...(facts?.verify ? [facts.verify.ok ? 'checks pass' : 'checks fail'] : [])]
      return { text: parts.join(' · '), tone: failedCheck ? 'text-destructive' : 'text-success', mark: failedCheck ? 'fail' : 'done', actions: [...(delegation.handoff ? [viewHandoff] : []), ...(changed ? [undo] : [])] }
    }
    case 'stopped':
      if (!delegation.startedAt) return { text: 'Cancelled before it started', tone: 'text-muted-foreground', mark: 'stopped', actions: [] }
      return { text: `Stopped by you${changed ? ' · partial changes kept' : ''}`, tone: 'text-muted-foreground', mark: 'stopped', actions: [review, { label: 'Resume', run: () => send({ type: 'resumeDelegation', id }), primary: true }] }
    case 'overdue':
      return { text: 'Still running past the limit', tone: 'text-warning', mark: 'needs', actions: [{ label: 'Stop', run: () => send({ type: 'groupStop' }) }] }
    default: {
      const reason = delegation.status === 'unknown' ? 'it stopped without saying whether it finished' : (delegation.report ?? '').split('\n').find((line) => line.trim())?.trim() || 'the turn ended with an error'
      return { text: `Failed: ${reason}${changed ? ' · partial changes kept' : ''}`, tone: 'text-destructive', mark: 'fail', actions: [review, ...(changed ? [undo] : [])] }
    }
  }
}

// Each status differs in shape as well as color.
function Mark({ mark }: { mark: CardMark }) {
  if (mark === 'spin') return <span role="img" aria-label="Working" className="size-4 shrink-0 animate-spin rounded-full border-[3px] border-control border-t-info" />
  if (mark === 'wait') return <span role="img" aria-label="Waiting" className="size-4 shrink-0 rounded-full border-2 border-dashed border-muted-foreground" />
  if (mark === 'done') return <span role="img" aria-label="Done" className="flex size-4 shrink-0 items-center justify-center rounded-[5px] bg-success text-[11px] font-extrabold text-background">✓</span>
  if (mark === 'needs') return <span role="img" aria-label="Needs you" className="flex size-4 shrink-0 rotate-45 items-center justify-center rounded-[3px] bg-warning"><span className="-rotate-45 text-[11px] font-extrabold text-background">!</span></span>
  if (mark === 'fail') return <span role="img" aria-label="Failed" className="flex size-4 shrink-0 items-center justify-center rounded-full bg-destructive text-[11px] font-extrabold text-background">×</span>
  if (mark === 'stopped') return <span role="img" aria-label="Stopped" className="size-3.5 shrink-0 rounded-[3px] bg-muted-foreground" />
  return null
}

function AnswerForm({ onAnswer, label = 'Answer' }: { onAnswer: (text: string) => void; label?: string }) {
  const [text, setText] = useState('')
  return (
    <form
      className="mt-2.5 flex flex-wrap gap-2"
      onSubmit={(event) => {
        event.preventDefault()
        if (text.trim()) onAnswer(text.trim())
      }}
    >
      <input aria-label="Your answer" className="h-[38px] min-w-[10rem] flex-1 rounded-[7px] bg-surface px-3" value={text} onChange={(event) => setText(event.target.value)} />
      <button type="submit" className="h-[38px] rounded-[7px] bg-primary px-3.5 font-semibold text-primary-foreground">
        {label}
      </button>
    </form>
  )
}

function DelegateCard({ group, delegation, items, selected, onSelect }: { group: GroupState; delegation: Delegation; items: TimelineItem[]; selected: boolean; onSelect: () => void }) {
  const [open, setOpen] = useState(false)
  const [full, setFull] = useState(false)
  const [answering, setAnswering] = useState(false)
  const now = useNow(1000)
  const live = delegation.status === 'running' || delegation.status === 'settling'
  const state = cardState(group, delegation, items, now)
  const question = group.userQuestions.find((candidate) => candidate.delegation === delegation.id)
  return (
    <div className={`ml-8 overflow-hidden rounded-[10px] border-2 bg-surface ${selected ? 'border-foreground' : 'border-transparent'}`}>
      <button
        type="button"
        aria-expanded={live || open}
        className="flex min-h-[58px] w-full items-center gap-2.5 px-3 py-2 text-left"
        onClick={() => {
          onSelect()
          if (!live) setOpen(!open)
        }}
      >
        <ProviderAvatar providerId={delegation.agent} className="size-[26px] rounded-[7px] text-xs" />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-semibold">
            {name(delegation.agent)}
            {delegation.role ? ` · ${ROLE_LABEL[delegation.role]}` : ''}: {delegation.phase ? `Phase ${delegation.phase} of ${delegation.phases}: ` : ''}
            {delegation.task}
          </span>
          {/* Screen readers hear the state, not the time ticking. */}
          <span className={`mt-0.5 block truncate text-xs font-medium ${state.tone}`}>
            <span aria-live="polite">{state.text}</span>
            {state.time ? <span aria-hidden="true"> · {state.time}</span> : null}
          </span>
        </span>
        <Mark mark={state.mark} />
      </button>
      {live || open ? (
        <>
          <Rolling items={items} full={full || (open && !live)} />
          {live ? (
            <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
              <span>@{delegation.agent} to redirect</span>
              <button type="button" className="hover:text-foreground hover:underline" onClick={() => send({ type: 'groupStop' })}>
                · Stop
              </button>
              <button type="button" className="ml-auto h-[30px] rounded-md bg-control px-2.5 font-semibold text-foreground" onClick={() => setFull(!full)}>
                {full ? 'Show less' : 'Show everything'}
              </button>
            </div>
          ) : null}
        </>
      ) : null}
      {state.actions.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 px-3 pb-2.5">
          {state.actions.map((action) =>
            'answer' in action ? (
              <button key={action.label} type="button" aria-expanded={answering} className="h-[30px] rounded-md bg-control px-2.5 text-xs font-semibold" onClick={() => setAnswering(!answering)}>
                {action.label}
              </button>
            ) : (
              <button key={action.label} type="button" className={`h-[30px] rounded-md px-2.5 text-xs font-semibold ${action.primary ? 'bg-primary text-primary-foreground' : 'bg-control'}`} onClick={action.run}>
                {action.label}
              </button>
            )
          )}
        </div>
      ) : null}
      {answering && !question ? (
        <div className="px-3 pb-3">
          <AnswerForm
            label="Send"
            onAnswer={(text) => {
              send({ type: 'answerDelegate', id: delegation.id, text })
              setAnswering(false)
            }}
          />
        </div>
      ) : null}
      {question ? (
        <div className="bg-warning/12 p-3">
          <div className="text-[11px] font-extrabold tracking-[0.06em] text-warning">QUESTION FOR YOU, FROM {delegation.agent.toUpperCase()}</div>
          <div className="mt-[5px] leading-[1.45] font-medium">{question.question}</div>
          <AnswerForm label="Reply" onAnswer={(text) => send({ type: 'answerQuestion', id: question.id, text })} />
        </div>
      ) : null}
    </div>
  )
}

/** The selected handoff: what the lead wrote, what AgentDeck added and recorded, and what the delegate reported. */
function HandoffPanel({ group, delegation }: { group: GroupState; delegation?: Delegation }) {
  if (!delegation) return null
  const facts = delegation.facts
  const factLines = facts
    ? [
        ...facts.files.map(fileChange),
        `${facts.commands.length} ${facts.commands.length === 1 ? 'command' : 'commands'}${facts.commands.some((command) => command.failed) ? `, ${facts.commands.filter((command) => command.failed).length} failed` : ''}`,
        ...(facts.verify ? [`${facts.verify.command}: ${facts.verify.ok ? 'passed' : 'failed'}`] : []),
        ...facts.violations.map((violation) => `Write blocked: ${violation}`),
        ...(facts.stillRunning ?? []).map((process) => `Still running: ${process}`),
        ...(facts.servicesLeft ?? []).map((service) => `Left running: ${service}`)
      ]
    : []
  const section = (title: string, by: string | undefined, body: ReactNode) => (
    <div className="rounded-[10px] bg-surface p-[11px]">
      <div className="font-bold">{title}</div>
      {by ? <div className="text-[11.5px] text-muted-foreground">{by}</div> : null}
      <div className="mt-1.5 leading-[1.45]">{body}</div>
    </div>
  )
  return (
    <aside aria-label="Handoff" className="flex w-80 shrink-0 flex-col gap-2.5 overflow-auto bg-band p-3.5 max-[860px]:hidden">
      <div>
        <div className="text-[11px] font-extrabold tracking-[0.08em] text-muted-foreground">HANDOFF</div>
        <div className="mt-1 text-base font-bold">
          {name(delegation.lead)} to {name(delegation.agent)}
          {delegation.role ? ` · ${ROLE_LABEL[delegation.role]}` : ''}
        </div>
      </div>
      {section(
        'Task',
        'Written by the lead',
        <>
          {delegation.task}
          {delegation.doneWhen ? `${/[.!?]$/.test(delegation.task.trim()) ? '' : '.'} Done when ${delegation.doneWhen.replace(/^./, (first) => first.toLowerCase())}` : ''}
          {delegation.context ? <div className="mt-2 max-h-72 overflow-auto border-t border-band pt-2 whitespace-pre-wrap text-muted-foreground">{delegation.context}</div> : null}
        </>
      )}
      {section('Added by AgentDeck', undefined, delegation.added ? (delegation.added.length > 0 ? delegation.added.map((line) => <div key={line}>{line}</div>) : 'Nothing: it had seen the whole chat.') : <span className="text-muted-foreground">Added when it starts.</span>)}
      {section(
        'Facts',
        'Recorded by AgentDeck',
        factLines.length > 0 ? (
          <div className="font-mono text-xs whitespace-pre-line">{factLines.join('\n')}</div>
        ) : (
          <span className="text-muted-foreground">Recorded when it finishes.</span>
        )
      )}
      {section('Report', 'Written by the delegate', delegation.report ? <div className="whitespace-pre-wrap">{delegation.report.replace(/\n?STATUS:.*$/i, '').trim() || delegation.report}</div> : <span className="text-muted-foreground">Not yet.</span>)}
      {(delegation.answers ?? []).map((answer) =>
        section('Question', undefined, (
          <>
            {name(delegation.agent)} asked: {answer.question}
            <div className="mt-1">
              {answer.by === 'user' ? 'You' : name(answer.by)} answered: {answer.answer}
            </div>
          </>
        ))
      )}
      {delegation.handoff ? (
        <button type="button" className="min-h-10 rounded-lg bg-control font-medium" onClick={() => send({ type: 'viewHandoff', id: delegation.id })}>
          Open full transcript
        </button>
      ) : null}
      {group.delegations.length > 1 ? <p className="text-xs text-muted-foreground">Select a card to see its handoff.</p> : null}
    </aside>
  )
}

/** Who is working, what is waiting, who leads, and Stop: shown under the roster, so the composer stays the composer. */
function Status({ group }: { group: GroupState }) {
  const waiting = group.queue.filter((message) => !message.internal)
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-control px-4 py-2 text-xs max-[480px]:gap-1.5 max-[480px]:px-3">
      <strong className="max-[480px]:hidden">Now</strong>
      {group.active.length > 0 ? (
        group.active.map((agent) => (
          <span key={agent} className="rounded-[5px] bg-primary px-2 py-[3px] font-semibold text-primary-foreground">
            {name(agent)}
          </span>
        ))
      ) : (
        <span className="rounded-[5px] bg-primary px-2 py-[3px] font-semibold text-primary-foreground">Waiting for you</span>
      )}
      {waiting.length > 0 ? <strong className="ml-2 max-[480px]:ml-0">Next</strong> : null}
      {waiting.map((message) => (
        <span key={message.id} className="flex items-center gap-1 rounded-[5px] bg-control px-2 py-[3px]">
          {name(message.target)}
          <button type="button" aria-label={`Remove the message for ${name(message.target)}`} onClick={() => send({ type: 'cancelQueued', queuedId: message.id })}>
            <Codicon name="close" size={12} />
          </button>
        </span>
      ))}
      <span className="ml-auto" />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button type="button" className="h-7 rounded-md bg-control px-2.5">
            Lead: {name(group.lead)}
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {group.members.map((member) => (
            <DropdownMenuItem key={member.agent} disabled={member.agent === group.lead} onSelect={() => send({ type: 'groupSetLead', agent: member.agent })}>
              <ProviderAvatar providerId={member.agent} className="size-5 rounded-md text-[10px]" />
              Make {name(member.agent)} the lead
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      <button type="button" disabled={!group.running} className="h-7 rounded-md bg-control px-2.5 disabled:opacity-40" onClick={() => send({ type: 'groupStop' })}>
        Stop
      </button>
    </div>
  )
}

/** Puts text in the composer, ready to finish and send. */
function compose(text: string): void {
  editInComposer([{ type: 'text', text }])
}

/** The full composer, showing the session of the agent the next message goes to. */
function GroupComposer({ state, group }: { state: ChatState; group: GroupState }) {
  const member = state.groupComposer
  const target = group.target
  const composerState: ChatState = {
    ...state,
    sessionId: member?.sessionId ?? group.id,
    status: group.active.includes(target) ? 'running' : 'idle',
    facts: member?.facts ?? {},
    ...(member ? { provider: member.provider } : {}),
    // The mode and lane pickers read the record; the group's lane applies to every agent in it.
    ...(member && state.record === undefined ? { record: { mode: member.mode, ...(group.laneId ? { laneId: group.laneId } : {}) } as ChatState['record'] } : {}),
    items: state.groupItems.flatMap(({ item }) => (item.kind === 'message' && item.role === 'user' && !marker({ agent: '', item }) ? [item] : []))
  }
  const agents = group.members.map((entry) => ({ id: entry.agent, label: name(entry.agent), detail: roleOf(group, entry.agent) || 'In this chat' }))
  return <Composer state={composerState} group={{ agents, placeholder: `Message ${name(target)}, or @ an agent or file` }} />
}

export function GroupView({ state }: { state: ChatState }) {
  const group = state.group as GroupState
  const items = state.groupItems
  const [selected, setSelected] = useState<string>()
  useApprovalKeys(items.map(({ item }) => item))
  const byAgent = useMemo(() => {
    const map = new Map<string, TimelineItem[]>()
    for (const entry of items) map.set(entry.agent, [...(map.get(entry.agent) ?? []), entry])
    return map
  }, [items])
  const shown = group.delegations.find((delegation) => delegation.id === selected) ?? group.delegations.find((delegation) => delegation.status === 'running' || delegation.status === 'settling') ?? group.delegations.at(-1)
  let previous: string | undefined
  // Each card sits right after the handoff that started it; any whose handoff is not loaded go at the end.
  const placed = new Set<string>()
  const card = (delegation: Delegation) => (
    <Fragment key={delegation.id}>
      <DelegateCard group={group} delegation={delegation} items={byAgent.get(delegation.agent) ?? []} selected={delegation.id === selected} onSelect={() => setSelected(delegation.id)} />
      {(delegation.answers ?? []).map((answer) => (
        <Band key={answer.question + answer.answer} action={<BandButton onClick={() => compose(`@${delegation.agent} `)}>Change answer</BandButton>}>
          {name(delegation.agent)} asked: {answer.question} {answer.by === 'user' ? 'You' : name(answer.by)} answered: {answer.answer}
        </Band>
      ))}
    </Fragment>
  )
  const cardFor = (entry: TimelineItem) => {
    const task = /\nTask: (.*)/.exec(userText(entry))?.[1]
    const delegation = task === undefined ? undefined : group.delegations.find((candidate) => !placed.has(candidate.id) && candidate.agent === entry.agent && candidate.task === task)
    if (!delegation) return null
    placed.add(delegation.id)
    return (
      <>
        <Band>{delegation.role ? `Roster: ${ROLE_LABEL[delegation.role]} belongs to ${name(delegation.agent)}. ${name(delegation.lead)} delegated it.` : `${name(delegation.lead)} handed this to ${name(delegation.agent)}.`}</Band>
        {card(delegation)}
      </>
    )
  }
  const finished = group.delegations.length > 0 && !group.running && group.delegations.every((delegation) => !['queued', 'running', 'settling', 'question'].includes(delegation.status))
  return (
    <AttachmentsContext.Provider value={state.attachmentsUri}>
      <TooltipProvider>
        <div className="flex h-screen bg-page">
          <div className="flex min-w-0 flex-1 flex-col">
            <Header group={group} />
            <Status group={group} />
            <Conversation className="min-h-0 flex-1">
              <ConversationContent className="gap-3 px-5 py-4">
                {items.map((entry) => {
                  const kind = marker(entry)
                  if (kind === 'handoff') {
                    previous = undefined
                    return <Fragment key={`${entry.agent}:${entry.item.id}`}>{cardFor(entry)}</Fragment>
                  }
                  if (kind === 'hidden') return null
                  if (kind === 'checkin') {
                    previous = undefined
                    return <Band key={`${entry.agent}:${entry.item.id}`}>AgentDeck checked in with {name(entry.agent)}.</Band>
                  }
                  if (entry.item.kind === 'turn' || inCard(group, entry)) return null
                  const isUser = entry.item.kind === 'message' && entry.item.role === 'user'
                  if (isUser) {
                    previous = 'user'
                    return (
                      <div key={`${entry.agent}:${entry.item.id}`} className="ml-auto max-w-[min(100%,52rem)] min-w-0">
                        {entry.agent !== group.lead ? <div className="mb-1 text-right text-xs text-muted-foreground">To {name(entry.agent)}</div> : null}
                        <div className="rounded-[10px] bg-control px-3 py-2.5 whitespace-pre-wrap">{userText(entry)}</div>
                      </div>
                    )
                  }
                  const label = entry.agent !== previous
                  previous = entry.agent
                  return (
                    <div key={`${entry.agent}:${entry.item.id}`} className="flex gap-2.5">
                      <span className="w-[22px] shrink-0">{label ? <ProviderAvatar providerId={entry.agent} className="size-[22px] rounded-md text-[11px]" /> : null}</span>
                      <div className="min-w-0 flex-1 leading-normal">
                        {label ? (
                          <div>
                            <strong className="font-semibold">{name(entry.agent)}</strong> <span className="text-xs text-muted-foreground">{roleOf(group, entry.agent)}</span>
                          </div>
                        ) : null}
                        <ItemView item={entry.item} />
                      </div>
                    </div>
                  )
                })}
                {group.delegations.filter((delegation) => !placed.has(delegation.id)).map(card)}
                {group.violations
                  .filter((violation) => !violation.undone && !violation.allowed)
                  .map((violation) => (
                    <Band
                      key={violation.id}
                      tone="warning"
                      action={
                        <>
                          <BandButton onClick={() => send({ type: 'allowViolation', id: violation.id })}>Allow this time</BandButton>
                          <BandButton onClick={() => send({ type: 'undoViolation', id: violation.id })}>Undo</BandButton>
                        </>
                      }
                    >
                      Write blocked: {name(violation.agent)} changed {violation.files.map(fileChange).join(', ')}, but {roleOf(group, violation.agent) || 'its role'} is read-only.
                    </Band>
                  ))}
                {group.userQuestions
                  .filter((question) => !question.delegation)
                  .map((question) => (
                    <div key={question.id} className="ml-8 rounded-[10px] bg-warning/12 p-3">
                      <div className="text-[11px] font-extrabold tracking-[0.06em] text-warning">QUESTION FOR YOU, FROM {question.from.toUpperCase()}</div>
                      <div className="mt-[5px] leading-[1.45] font-medium">{question.question}</div>
                      <AnswerForm label="Reply" onAnswer={(text) => send({ type: 'answerQuestion', id: question.id, text })} />
                    </div>
                  ))}
                {group.queue
                  .filter((message) => !message.internal)
                  .map((message) => (
                    <div key={message.id} className="ml-auto max-w-[min(100%,52rem)] min-w-0 opacity-70">
                      <div className="mb-1 text-right text-xs text-muted-foreground">
                        To {name(message.target)} · {group.active.includes(message.target) ? 'after its current message' : 'waiting for the agent editing code to finish'}
                      </div>
                      <div className="rounded-[10px] border border-dashed border-control px-3 py-2.5 whitespace-pre-wrap">{message.text}</div>
                    </div>
                  ))}
                {finished ? (
                  <button type="button" className="ml-8 min-h-11 rounded-lg bg-primary font-bold text-primary-foreground" onClick={() => send({ type: 'openReview' })}>
                    Review the work
                  </button>
                ) : null}
              </ConversationContent>
              <ConversationScrollButton />
            </Conversation>
            <div className="border-t border-control px-5 pt-2.5 pb-3">
              {group.blocked ? (
                <div className="mb-2 flex items-center gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-destructive">
                  <span className="flex-1">{group.blocked}</span>
                  <BandButton onClick={() => send({ type: 'groupRetry' })}>Retry</BandButton>
                </div>
              ) : null}
              <GroupComposer state={state} group={group} />
            </div>
          </div>
          <HandoffPanel group={group} delegation={shown} />
        </div>
      </TooltipProvider>
    </AttachmentsContext.Provider>
  )
}
