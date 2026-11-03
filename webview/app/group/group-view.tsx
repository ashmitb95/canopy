import { Fragment, type ReactNode, useMemo, useState } from 'react'
import { Conversation, ConversationContent, ConversationScrollButton } from '@/components/ai-elements/conversation'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { TooltipProvider } from '@/components/ui/tooltip'
import type { Delegation, GroupState, TimelineItem } from '../../../src/group/chat'
import { rollingLines } from '../../../src/group/rolling'
import { AttachmentsContext } from '../assets'
import { Codicon } from '../components/codicon'
import { ProviderAvatar } from '../components/provider-avatar'
import { send } from '../host'
import { useApprovalKeys } from '../items/approval-card'
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
        const active = group.running ? group.running === member.agent : group.lead === member.agent
        return (
          <span key={member.agent} className={`inline-flex h-10 items-center gap-[7px] rounded-lg px-2.5 ${active ? 'bg-primary text-primary-foreground' : 'bg-surface'}`}>
            <ProviderAvatar providerId={member.agent} className="size-5 rounded-md text-[10px]" />
            <span>
              <span className="block leading-[1.1] font-bold">{name(member.agent)}</span>
              <span className="block text-[11px] leading-[1.2]">{roleOf(group, member.agent) || 'In this chat'}</span>
            </span>
          </span>
        )
      })}
    </header>
  )
}

function Rolling({ items, full }: { items: TimelineItem[]; full: boolean }) {
  const all = useMemo(() => rollingLines(items.map(({ item }) => item)), [items])
  const lines = full ? all : all.slice(-WINDOW)
  if (lines.length === 0) return null
  return (
    <div className={`mx-3 flex flex-col justify-end gap-[3px] overflow-hidden rounded-lg bg-band px-3 py-2.5 text-[12.5px] leading-[1.45] ${full ? '' : 'max-h-[186px]'}`} aria-live="off">
      {lines.map((line) => (
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
  )
}

const STATUS_TEXT: Record<Delegation['status'], string> = {
  queued: 'Up next',
  running: 'Working',
  settling: 'Reported done, waiting for its work to finish',
  done: 'Report ready',
  blocked: 'Blocked',
  question: 'Asked a question',
  overdue: 'Still running past the limit',
  unknown: 'Stopped without saying whether it finished',
  failed: 'Failed',
  interrupted: 'Interrupted'
}

function cardStatus(group: GroupState, delegation: Delegation): { text: string; tone: string; mark: 'spin' | 'done' | 'needs' | 'fail' | 'none' } {
  const facts = delegation.facts
  if (delegation.undone) return { text: 'Undone', tone: 'text-muted-foreground', mark: 'none' }
  if (delegation.status === 'running' || delegation.status === 'settling') {
    const activity = group.members.find((member) => member.agent === delegation.agent)?.activity
    return { text: delegation.status === 'settling' ? STATUS_TEXT.settling : activity || 'Working', tone: 'text-info', mark: 'spin' }
  }
  if (delegation.status === 'question') {
    const toUser = group.userQuestions.some((question) => question.delegation === delegation.id)
    return { text: toUser ? 'Needs your answer' : `Waiting for ${name(delegation.lead)} to answer`, tone: toUser ? 'text-warning' : 'text-info', mark: toUser ? 'needs' : 'spin' }
  }
  if (delegation.status === 'done') {
    const parts = ['Report ready', ...(facts ? [`${facts.files.length} ${facts.files.length === 1 ? 'file' : 'files'}`] : []), ...(facts?.verify ? [facts.verify.ok ? 'checks pass' : 'checks fail'] : [])]
    return { text: parts.join(' · '), tone: facts?.verify && !facts.verify.ok ? 'text-destructive' : 'text-success', mark: facts?.verify && !facts.verify.ok ? 'fail' : 'done' }
  }
  if (delegation.status === 'queued') return { text: STATUS_TEXT.queued, tone: 'text-muted-foreground', mark: 'none' }
  return { text: STATUS_TEXT[delegation.status], tone: delegation.status === 'blocked' ? 'text-warning' : 'text-destructive', mark: delegation.status === 'blocked' ? 'needs' : 'fail' }
}

function Mark({ mark }: { mark: ReturnType<typeof cardStatus>['mark'] }) {
  if (mark === 'spin') return <span aria-label="Working" className="size-4 shrink-0 animate-spin rounded-full border-[3px] border-control border-t-info" />
  if (mark === 'done') return <span aria-label="Done" className="flex size-4 shrink-0 items-center justify-center rounded-[5px] bg-success text-[11px] font-extrabold text-background">✓</span>
  if (mark === 'needs') return <span aria-label="Needs you" className="flex size-4 shrink-0 items-center justify-center rounded-[5px] bg-warning text-[11px] font-extrabold text-background">!</span>
  if (mark === 'fail') return <span aria-label="Failed" className="flex size-4 shrink-0 items-center justify-center rounded-[5px] bg-destructive text-[11px] font-extrabold text-background">×</span>
  return null
}

function AnswerForm({ id }: { id: string }) {
  const [text, setText] = useState('')
  return (
    <form
      className="mt-2.5 flex flex-wrap gap-2"
      onSubmit={(event) => {
        event.preventDefault()
        if (text.trim()) send({ type: 'answerQuestion', id, text: text.trim() })
      }}
    >
      <input aria-label="Your answer" className="h-[38px] min-w-[10rem] flex-1 rounded-[7px] bg-surface px-3" value={text} onChange={(event) => setText(event.target.value)} />
      <button type="submit" className="h-[38px] rounded-[7px] bg-primary px-3.5 font-semibold text-primary-foreground">
        Answer
      </button>
    </form>
  )
}

function DelegateCard({ group, delegation, items, selected, onSelect }: { group: GroupState; delegation: Delegation; items: TimelineItem[]; selected: boolean; onSelect: () => void }) {
  const [open, setOpen] = useState(false)
  const [full, setFull] = useState(false)
  const live = delegation.status === 'running' || delegation.status === 'settling'
  const status = cardStatus(group, delegation)
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
            {delegation.role ? ` · ${ROLE_LABEL[delegation.role]}` : ''}: {delegation.task}
          </span>
          <span className={`mt-0.5 block truncate text-xs font-medium ${status.tone}`}>{status.text}</span>
        </span>
        <Mark mark={status.mark} />
      </button>
      {live || open ? (
        <>
          <Rolling items={items} full={full || (open && !live)} />
          <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
            {live ? (
              <>
                <span>@{delegation.agent} to redirect</span>
                <button type="button" className="hover:text-foreground hover:underline" onClick={() => send({ type: 'groupStop' })}>
                  · Stop
                </button>
                <button type="button" className="ml-auto h-[30px] rounded-md bg-control px-2.5 font-semibold text-foreground" onClick={() => setFull(!full)}>
                  {full ? 'Show less' : 'Show everything'}
                </button>
              </>
            ) : (
              <>
                {delegation.handoff ? (
                  <button type="button" className="h-[30px] rounded-md bg-control px-2.5 font-semibold text-foreground" onClick={() => send({ type: 'viewHandoff', id: delegation.id })}>
                    Open full transcript
                  </button>
                ) : null}
                {delegation.snapshots && !delegation.undone ? (
                  <button type="button" className="h-[30px] rounded-md bg-control px-2.5 font-semibold text-foreground" onClick={() => send({ type: 'undoDelegation', id: delegation.id })}>
                    Undo these changes
                  </button>
                ) : null}
              </>
            )}
          </div>
        </>
      ) : null}
      {question ? (
        <div className="bg-warning/12 p-3">
          <div className="text-[11px] font-extrabold tracking-[0.06em] text-warning">QUESTION FOR YOU, FROM {delegation.agent.toUpperCase()}</div>
          <div className="mt-[5px] leading-[1.45] font-medium">{question.question}</div>
          <AnswerForm id={question.id} />
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
          {delegation.doneWhen ? ` Done when ${delegation.doneWhen.replace(/^./, (first) => first.toLowerCase())}` : ''}
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

function Queue({ group }: { group: GroupState }) {
  const next = group.queue.filter((message) => !message.internal)
  return (
    <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
      <strong>Now</strong>
      <span className="rounded-[5px] bg-primary px-2 py-[3px] font-semibold text-primary-foreground">{group.running ? name(group.running) : 'Waiting for you'}</span>
      <strong className="ml-2">Next</strong>
      {next.length === 0 ? <span className="rounded-[5px] bg-control px-2 py-[3px]">{group.running ? name(group.queue[0]?.target ?? group.lead) : 'You'}</span> : null}
      {next.map((message) => (
        <span key={message.id} className="flex items-center gap-1 rounded-[5px] bg-control px-2 py-[3px]">
          {name(message.target)}
          {message.target === group.running ? (
            <button type="button" className="underline" onClick={() => send({ type: 'stopAndSend', queuedId: message.id })}>
              send now
            </button>
          ) : null}
          <button type="button" aria-label="Remove from queue" onClick={() => send({ type: 'cancelQueued', queuedId: message.id })}>
            <Codicon name="close" size={12} />
          </button>
        </span>
      ))}
      <button type="button" disabled={!group.running} className="ml-auto h-7 rounded-md bg-control px-2.5 disabled:opacity-40" onClick={() => send({ type: 'groupStop' })}>
        Stop
      </button>
    </div>
  )
}

function Composer({ group }: { group: GroupState }) {
  const [text, setText] = useState('')
  const target = /^@(\w+)/.exec(text.trim())?.[1] ?? group.target
  const submit = () => {
    if (!text.trim()) return
    send({ type: 'groupSend', text })
    setText('')
  }
  const others = group.members.map((member) => member.agent).filter((agent) => agent !== group.target)
  return (
    <div>
      <textarea
        aria-label="Message"
        rows={1}
        className="field-sizing-content max-h-48 min-h-11 w-full resize-none rounded-[10px] bg-surface px-3 py-3"
        placeholder={`Message ${name(group.target)}${others.length > 0 ? `, or @${others[0]}` : ''}`}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            submit()
          }
        }}
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button type="button" className="h-8 rounded-[7px] bg-control px-2.5 font-semibold">
              @ Mention
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {group.members.map((member) => (
              <DropdownMenuItem key={member.agent} onSelect={() => setText(`@${member.agent} ${text.replace(/^@\w+\s*/, '')}`)}>
                <ProviderAvatar providerId={member.agent} className="size-5 rounded-md text-[10px]" />
                {name(member.agent)}
                <span className="text-xs text-muted-foreground">{roleOf(group, member.agent)}</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button type="button" className="h-8 rounded-[7px] bg-control px-2.5">
              Lead: {name(group.lead)}
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {group.members.map((member) => (
              <DropdownMenuItem key={member.agent} disabled={member.agent === group.lead} onSelect={() => send({ type: 'groupSetLead', agent: member.agent })}>
                <ProviderAvatar providerId={member.agent} className="size-5 rounded-md text-[10px]" />
                Make {name(member.agent)} the lead
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        <span className="ml-auto text-xs text-muted-foreground">
          {name(target)} gets this {group.running === target ? 'when it finishes' : group.running ? 'when it is up' : 'now'}
        </span>
      </div>
    </div>
  )
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
        <Band key={answer.question + answer.answer} action={<BandButton onClick={() => send({ type: 'groupSend', text: `@${delegation.agent} ` })}>Change answer</BandButton>}>
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
                      <div key={`${entry.agent}:${entry.item.id}`} className="ml-auto max-w-[min(100%,52rem)] min-w-0 rounded-[10px] bg-control px-3 py-2.5 whitespace-pre-wrap">
                        {userText(entry)}
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
                  .filter((violation) => !violation.undone)
                  .map((violation) => (
                    <Band key={violation.id} tone="warning" action={<BandButton onClick={() => send({ type: 'undoViolation', id: violation.id })}>Undo</BandButton>}>
                      {name(violation.agent)} changed {violation.files.map(fileChange).join(', ')}, but {roleOf(group, violation.agent) || 'its role'} is read-only. AgentDeck flagged it.
                    </Band>
                  ))}
                {group.userQuestions
                  .filter((question) => !question.delegation)
                  .map((question) => (
                    <div key={question.id} className="ml-8 rounded-[10px] bg-warning/12 p-3">
                      <div className="text-[11px] font-extrabold tracking-[0.06em] text-warning">QUESTION FOR YOU, FROM {question.from.toUpperCase()}</div>
                      <div className="mt-[5px] leading-[1.45] font-medium">{question.question}</div>
                      <AnswerForm id={question.id} />
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
              <Queue group={group} />
              <Composer group={group} />
            </div>
          </div>
          <HandoffPanel group={group} delegation={shown} />
        </div>
      </TooltipProvider>
    </AttachmentsContext.Provider>
  )
}
