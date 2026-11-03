import { Fragment, useMemo, useState } from 'react'
import { Conversation, ConversationContent, ConversationScrollButton } from '@/components/ai-elements/conversation'
import { Button } from '@/components/ui/button'
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
const WINDOW = 7

function roleOf(group: GroupState, agent: string): string {
  const roles = Object.entries(group.roster).flatMap(([role, holder]) => (holder === agent ? [ROLE_LABEL[role] ?? role] : []))
  return [agent === group.lead ? 'Lead' : undefined, ...roles].filter(Boolean).join(' · ')
}

function userText(entry: TimelineItem): string {
  return entry.item.kind === 'message' && entry.item.role === 'user' ? entry.item.parts.map((part) => ('text' in part ? part.text : '')).join(' ') : ''
}

/** Messages AgentDeck sent between agents read as one line, so the conversation stays the user's. */
function marker(group: GroupState, entry: TimelineItem): string | undefined {
  const text = userText(entry)
  if (!text) return undefined
  if (text.startsWith('Report from ')) return `${/^Report from (\S+)/.exec(text)?.[1]} reported back to ${entry.agent}`
  if (text.startsWith('You are ') && text.includes('delegated this by')) return `${/delegated this by (\S+)/.exec(text)?.[1]} handed this to ${entry.agent}: ${/Task: (.*)/.exec(text)?.[1] ?? ''}`
  if (text.startsWith('The lead answered') || text.startsWith('The user answered')) return `${entry.agent} got an answer`
  if (text.startsWith('The background work you started') || text.startsWith('AgentDeck restarted') || text.startsWith('You said you would hand this off')) return `AgentDeck checked in with ${entry.agent}`
  return group.roster && text.startsWith('You lead a group chat') ? undefined : undefined
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

function Header({ group }: { group: GroupState }) {
  return (
    <header className="flex flex-wrap items-center gap-1.5 border-b px-3 py-2">
      <span className="mr-auto truncate font-semibold">{group.title}</span>
      {group.members.map((member) => {
        const active = group.running === member.agent
        return (
          <span key={member.agent} className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-xs ${active ? 'bg-primary text-primary-foreground' : 'bg-muted'}`}>
            <ProviderAvatar providerId={member.agent} className="size-5 text-[10px]" />
            <span className="leading-tight">
              <span className="block font-semibold capitalize">{member.agent}</span>
              <span className="block opacity-80">{roleOf(group, member.agent) || 'In this chat'}</span>
            </span>
          </span>
        )
      })}
      {group.delegations.length > 0 ? (
        <Button size="sm" variant="ghost" onClick={() => send({ type: 'openReview' })}>
          Review
        </Button>
      ) : null}
    </header>
  )
}

function Rolling({ items }: { items: TimelineItem[] }) {
  const lines = useMemo(() => rollingLines(items.map(({ item }) => item)).slice(-WINDOW), [items])
  if (lines.length === 0) return null
  return (
    <div className="mx-3 mb-2 space-y-0.5 rounded-md bg-muted px-3 py-2 text-xs" aria-live="off">
      {lines.map((line) => (
        <div key={line.id} className={`truncate ${line.kind === 'tool' ? 'font-mono' : ''} ${line.kind === 'output' || line.kind === 'thought' ? 'pl-3 font-mono text-muted-foreground' : ''} ${line.failed ? 'text-destructive' : ''}`}>
          {line.text}
          {line.stat ? <span className="ml-2 font-mono">{line.stat}</span> : null}
          {line.live ? <span className="ml-1 animate-pulse">▌</span> : null}
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

function DelegateCard({ group, delegation, items }: { group: GroupState; delegation: Delegation; items: TimelineItem[] }) {
  const [open, setOpen] = useState(false)
  const live = group.running === delegation.agent && (delegation.status === 'running' || delegation.status === 'settling')
  const facts = delegation.facts
  return (
    <div className="ml-8 overflow-hidden rounded-md border bg-card">
      <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left" aria-expanded={open} onClick={() => setOpen(!open)}>
        <ProviderAvatar providerId={delegation.agent} className="size-6 text-[11px]" />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">
            <span className="capitalize">{delegation.agent}</span>
            {delegation.role ? ` · ${ROLE_LABEL[delegation.role]}` : ''}: {delegation.task}
          </span>
          <span className="block text-xs text-muted-foreground">
            {STATUS_TEXT[delegation.status]}
            {facts ? ` · ${facts.files.length} files · ${facts.commands.length} commands` : ''}
            {facts?.verify ? ` · check ${facts.verify.ok ? 'passed' : 'failed'}` : ''}
          </span>
        </span>
        {live ? <Codicon name="loading" className="animate-spin" /> : null}
      </button>
      {live || open ? <Rolling items={items} /> : null}
      {open && !live && facts ? (
        <div className="space-y-1 px-3 pb-3 text-xs">
          {facts.files.length > 0 && <div className="font-mono">{facts.files.map(fileChange).join(' · ')}</div>}
          {delegation.report ? <div className="whitespace-pre-wrap text-muted-foreground">{delegation.report}</div> : null}
          {facts.stillRunning?.length ? <div>Still running: {facts.stillRunning.join('; ')}</div> : null}
          {facts.servicesLeft?.length ? <div>Left running: {facts.servicesLeft.join('; ')}</div> : null}
          <div className="flex gap-2 pt-1">
            {delegation.snapshots && !delegation.undone ? (
              <Button size="sm" variant="secondary" onClick={() => send({ type: 'undoDelegation', id: delegation.id })}>
                Undo these changes
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function Questions({ group }: { group: GroupState }) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  if (group.userQuestions.length === 0) return null
  return (
    <div className="space-y-2">
      {group.userQuestions.map((question) => (
        <div key={question.id} className="rounded-md border border-warning bg-card p-3 text-sm">
          <div className="text-xs font-semibold text-warning">
            QUESTION FOR YOU, FROM <span className="uppercase">{question.from}</span>
          </div>
          <div className="mt-1">{question.question}</div>
          <form
            className="mt-2 flex gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              const text = answers[question.id]?.trim()
              if (text) send({ type: 'answerQuestion', id: question.id, text })
            }}
          >
            <input
              aria-label="Your answer"
              className="min-w-0 flex-1 rounded-md border bg-input px-2 py-1"
              value={answers[question.id] ?? ''}
              onChange={(event) => setAnswers({ ...answers, [question.id]: event.target.value })}
            />
            <Button size="sm" type="submit">
              Answer
            </Button>
          </form>
        </div>
      ))}
    </div>
  )
}

function Queue({ group }: { group: GroupState }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="font-semibold">Now</span>
      <span className="rounded bg-primary px-2 py-0.5 capitalize text-primary-foreground">{group.running ?? 'Waiting for you'}</span>
      {group.queue.map((message, index) => (
        <span key={message.id} className="flex items-center gap-1 rounded bg-muted px-2 py-0.5">
          {index === 0 ? <span className="font-semibold">Next</span> : null}
          <span className="capitalize">{message.target}</span>
          {message.target === group.running ? (
            <button type="button" className="underline" onClick={() => send({ type: 'stopAndSend', queuedId: message.id })}>
              Stop and send now
            </button>
          ) : null}
          <button type="button" aria-label="Remove from queue" onClick={() => send({ type: 'cancelQueued', queuedId: message.id })}>
            <Codicon name="close" size={12} />
          </button>
        </span>
      ))}
      {group.running ? (
        <button type="button" className="ml-auto underline" onClick={() => send({ type: 'groupStop' })}>
          Stop
        </button>
      ) : null}
    </div>
  )
}

function Composer({ group }: { group: GroupState }) {
  const [text, setText] = useState('')
  const target = /^@(\w+)/.exec(text.trim())?.[1] ?? group.target
  const busy = group.running === target
  const submit = () => {
    if (!text.trim()) return
    send({ type: 'groupSend', text })
    setText('')
  }
  return (
    <div className="space-y-1.5">
      <textarea
        aria-label="Message"
        className="min-h-16 w-full resize-none rounded-md border bg-card px-3 py-2"
        placeholder={`Message ${group.target}, or type @ to address another agent`}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            submit()
          }
        }}
      />
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        {group.members.map((member) => (
          <Button key={member.agent} size="sm" variant="secondary" onClick={() => setText(`@${member.agent} ${text.replace(/^@\w+\s*/, '')}`)}>
            @{member.agent}
          </Button>
        ))}
        <span className="ml-auto text-muted-foreground">
          <span className="capitalize">{target}</span> gets this {busy ? 'when it finishes, unless it can take it now' : group.running ? 'when it is up' : 'now'}
        </span>
      </div>
    </div>
  )
}

export function GroupView({ state }: { state: ChatState }) {
  const group = state.group as GroupState
  const items = state.groupItems
  useApprovalKeys(items.map(({ item }) => item))
  const byAgent = useMemo(() => {
    const map = new Map<string, TimelineItem[]>()
    for (const entry of items) map.set(entry.agent, [...(map.get(entry.agent) ?? []), entry])
    return map
  }, [items])
  let previous: string | undefined
  // Each card sits right after the handoff that started it; any whose handoff is not loaded go at the end.
  const placed = new Set<string>()
  const cardFor = (entry: TimelineItem) => {
    const task = /\nTask: (.*)/.exec(userText(entry))?.[1]
    const delegation = task === undefined ? undefined : group.delegations.find((candidate) => !placed.has(candidate.id) && candidate.agent === entry.agent && candidate.task === task)
    if (!delegation) return null
    placed.add(delegation.id)
    return <DelegateCard key={delegation.id} group={group} delegation={delegation} items={byAgent.get(delegation.agent) ?? []} />
  }
  return (
    <AttachmentsContext.Provider value={state.attachmentsUri}>
      <TooltipProvider>
        <div className="flex h-screen flex-col">
          <Header group={group} />
          <Conversation className="min-h-0 flex-1">
            <ConversationContent className="gap-3 px-4 py-4">
              {items.map((entry) => {
                const line = marker(group, entry)
                if (line) {
                  previous = undefined
                  return (
                    <Fragment key={`${entry.agent}:${entry.item.id}`}>
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <ProviderAvatar providerId={entry.agent} className="size-5 text-[10px]" />
                        <span className="truncate">{line}</span>
                      </div>
                      {cardFor(entry)}
                    </Fragment>
                  )
                }
                if (entry.item.kind === 'turn' || inCard(group, entry)) return null
                const speaker = entry.item.kind === 'message' && entry.item.role === 'user' ? 'user' : entry.agent
                const label = speaker !== 'user' && speaker !== previous
                previous = speaker
                return (
                  <div key={`${entry.agent}:${entry.item.id}`}>
                    {label ? (
                      <div className="mb-1 flex items-center gap-2 text-xs">
                        <ProviderAvatar providerId={entry.agent} className="size-5 text-[10px]" />
                        <span className="font-semibold capitalize">{entry.agent}</span>
                        <span className="text-muted-foreground">{roleOf(group, entry.agent)}</span>
                      </div>
                    ) : null}
                    <ItemView item={entry.item} />
                  </div>
                )
              })}
              {group.delegations.filter((delegation) => !placed.has(delegation.id)).map((delegation) => (
                <DelegateCard key={delegation.id} group={group} delegation={delegation} items={byAgent.get(delegation.agent) ?? []} />
              ))}
              {group.violations.filter((violation) => !violation.undone).map((violation) => (
                <div key={violation.id} className="flex items-center gap-2 rounded-md bg-muted px-3 py-2 text-xs">
                  <span className="flex-1">
                    <span className="capitalize">{violation.agent}</span> changed files it should not have: {violation.files.map(fileChange).join(', ')}
                  </span>
                  <Button size="sm" variant="secondary" onClick={() => send({ type: 'undoViolation', id: violation.id })}>
                    Undo
                  </Button>
                </div>
              ))}
            </ConversationContent>
            <ConversationScrollButton />
          </Conversation>
          <div className="space-y-2 px-3 pb-3">
            {group.blocked ? (
              <div className="flex items-center gap-2 rounded-md border border-destructive px-3 py-2 text-xs">
                <span className="flex-1">{group.blocked}</span>
                <Button size="sm" variant="secondary" onClick={() => send({ type: 'groupRetry' })}>
                  Retry
                </Button>
              </div>
            ) : null}
            <Questions group={group} />
            <Queue group={group} />
            <Composer group={group} />
          </div>
        </div>
      </TooltipProvider>
    </AttachmentsContext.Provider>
  )
}
