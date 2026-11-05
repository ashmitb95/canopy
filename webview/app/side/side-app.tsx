import { useEffect, useState } from 'react'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import type { SideData } from '../../../src/ui/protocol'
import { relativeTime } from '../../../src/ui/time'
import { Codicon } from '../components/codicon'
import { ProviderAvatar } from '../components/provider-avatar'
import { onHostMessage, send } from '../host'

const label = (agent: string) => agent.charAt(0).toUpperCase() + agent.slice(1)

const SESSION_STATE: Record<string, string> = { running: 'working', 'needs-input': 'needs you', error: 'failed', stopped: 'stopped', idle: 'idle' }

/** Needs you is a diamond, working a spinning ring: they differ in shape as well as color. */
function StatusMark({ needs }: { needs: boolean }) {
  return needs ? (
    <span role="img" aria-label="Needs you" className="mx-px size-3 shrink-0 rotate-45 rounded-[2px] bg-warning" />
  ) : (
    <span role="img" aria-label="Working" className="size-3.5 shrink-0 animate-spin rounded-full border-[3px] border-control border-t-info" />
  )
}

function Heading({ children }: { children: string }) {
  return <span className="text-[11px] font-extrabold tracking-[0.08em]">{children}</span>
}

type Lane = NonNullable<SideData['lanes']>[number]

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? '' : 's'}`

/** What a lane holds, in words: where its code is, uncommitted files, and chats. */
function laneStatus(lane: Lane, chats: number): string {
  return [lane.primary ? undefined : lane.warm ? 'worktree' : 'branch only', lane.dirty > 0 ? `${lane.dirty} uncommitted` : lane.primary ? undefined : 'clean', chats > 0 ? plural(chats, 'chat') : undefined].filter(Boolean).join(' · ')
}

/** The primary checkout, then only lanes with chats or uncommitted work; the rest are a click away in the Lane view. */
function Lanes({ data }: { data: SideData }) {
  const lanes = data.lanes ?? []
  const chats = (name: string) => [...data.groups, ...data.sessions].filter((chat) => chat.laneId === name).length
  const primary = lanes.find((lane) => lane.primary)
  const busy = lanes.filter((lane) => !lane.primary && (lane.dirty > 0 || chats(lane.name) > 0))
  const rest = lanes.length - busy.length - (primary ? 1 : 0)
  const primaryStatus = primary ? laneStatus(primary, chats(primary.name)) : ''
  return (
    <div className="flex flex-col gap-1 px-2 pb-2">
      <button type="button" data-card="primary" className="rounded-lg bg-primary px-[11px] py-[9px] text-left text-primary-foreground" title="Open the Lane view" onClick={() => send({ type: 'openLanes' })}>
        <div className="text-[10px] font-extrabold tracking-[0.08em]">RUNS HERE · PRIMARY CHECKOUT</div>
        <div className="mt-0.5 truncate font-mono text-sm font-semibold">{primary ? primary.name : 'base branch'}</div>
        {primaryStatus ? <div className="mt-0.5 truncate text-xs">{primaryStatus}</div> : null}
      </button>
      {busy.map((lane) => (
        <div
          key={lane.name}
          data-card=""
          data-vscode-context={JSON.stringify({ webviewSection: 'lane', lane: { name: lane.name }, preventDefaultContextMenuItems: true })}
          className="flex items-center rounded-[7px] bg-surface hover:bg-control"
        >
          <button type="button" className="min-w-0 flex-1 py-1.5 pl-2.5 text-left" title={lane.where} onClick={() => send({ type: 'openLanes' })}>
            <span className="block truncate font-mono text-xs font-medium">{lane.name}</span>
            <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">{laneStatus(lane, chats(lane.name))}</span>
          </button>
          {lane.warm ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button type="button" aria-label={`More for ${lane.name}`} className="flex size-[30px] shrink-0 items-center justify-center rounded-md hover:bg-surface">
                  <Codicon name="ellipsis" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => send({ type: 'switchLane', laneId: lane.name })}>Run here (move into the primary checkout)</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
        </div>
      ))}
      {rest > 0 ? (
        <button type="button" className="flex h-[30px] items-center px-2.5 text-left text-muted-foreground hover:text-foreground" onClick={() => send({ type: 'openLanes' })}>
          {rest} more {rest === 1 ? 'lane' : 'lanes'} in Lane view
        </button>
      ) : null}
    </div>
  )
}

function Row({ attention, active, onOpen, context, children }: { attention: boolean; active: boolean; onOpen: () => void; context?: string; children: React.ReactNode }) {
  return (
    <button
      type="button"
      data-vscode-context={context}
      className={`block w-full rounded-lg p-2.5 text-left ${attention ? 'bg-warning/12' : active ? 'bg-surface' : 'hover:bg-surface'}`}
      onClick={onOpen}
    >
      {children}
    </button>
  )
}

/**
 * The primary sidebar, or with `conversationsOnly` every conversation. `embedded` is the data when another view
 * hosts the list, such as the chat view, which then owns the messages to and from the extension.
 */
export function SideApp({ conversationsOnly = false, embedded }: { conversationsOnly?: boolean; embedded?: SideData }) {
  const [own, setOwn] = useState<SideData>()
  const [lanesOpen, setLanesOpen] = useState(true)
  const hosted = conversationsOnly && embedded !== undefined
  useEffect(() => {
    if (hosted) return
    const off = onHostMessage((message) => {
      if (message.type === 'side') setOwn(message.side)
    })
    send({ type: 'ready' })
    return off
  }, [hosted])
  const data = embedded ?? own
  if (!data) return null
  return (
    <div className="flex h-screen flex-col text-[13px]">
      {data.lanes && !conversationsOnly ? (
        <>
          <div className="flex h-[38px] shrink-0 items-center">
            <button type="button" aria-expanded={lanesOpen} className="flex h-[38px] flex-1 items-center gap-1.5 px-2.5 text-left" onClick={() => setLanesOpen(!lanesOpen)}>
              <Codicon name={lanesOpen ? 'chevron-down' : 'chevron-right'} size={12} />
              <Heading>LANES</Heading>
            </button>
            <button type="button" aria-label="New worktree" className="flex size-[38px] items-center justify-center hover:bg-surface" onClick={() => send({ type: 'newLane' })}>
              <Codicon name="add" />
            </button>
          </div>
          {lanesOpen ? <Lanes data={data} /> : null}
        </>
      ) : null}
      <div className={`flex h-[38px] shrink-0 items-center pl-2.5 ${conversationsOnly ? 'hidden' : ''}`}>
        <span className="flex-1">
          <Heading>SESSIONS</Heading>
        </span>
        <button type="button" aria-label="New group chat" className="flex size-[38px] items-center justify-center hover:bg-surface" onClick={() => send({ type: 'newGroupChat' })}>
          <Codicon name="add" />
        </button>
      </div>
      <div className={`min-h-0 flex-1 space-y-0.5 overflow-auto px-1.5 pb-2 ${conversationsOnly ? 'pt-1.5' : ''}`}>
        {data.groups.map((group) => {
          const live = Boolean(group.running) || group.needsYou
          const who = group.running ?? group.lead
          return (
            <Row
              key={group.id}
              attention={group.needsYou}
              active={live}
              context={JSON.stringify({ webviewSection: 'group', id: group.id, preventDefaultContextMenuItems: true })}
              onOpen={() => send({ type: 'openGroup', groupId: group.id })}
            >
              <div className="flex items-center gap-[7px]">
                {live ? <StatusMark needs={group.needsYou} /> : null}
                <span className={`min-w-0 flex-1 truncate ${live ? 'font-semibold' : ''}`}>{group.title}</span>
              </div>
              {live ? (
                <>
                  <div className="mt-1.5 flex items-center gap-1.5 font-semibold">
                    <ProviderAvatar providerId={who} className="size-[18px] rounded-[5px] text-[10px]" />
                    {label(who)}
                  </div>
                  <div className={`mt-1 truncate text-xs ${group.needsYou ? 'text-warning' : 'text-muted-foreground'}`}>{group.needsYou ? 'Needs you' : group.activity || 'Working'}</div>
                </>
              ) : (
                <div className="mt-[3px] truncate text-xs text-muted-foreground">{group.agents.map(label).join(', ')} · idle</div>
              )}
              {group.laneId ? <div className="mt-[3px] truncate font-mono text-[11px] text-muted-foreground">{group.laneId}</div> : null}
            </Row>
          )
        })}
        {data.sessions.map((session) => {
          const attention = session.status === 'needs-input'
          const live = attention || session.status === 'running'
          const state = session.unread && session.status === 'idle' ? 'finished' : SESSION_STATE[session.status] ?? session.status
          return (
            <Row
              key={session.id}
              attention={attention}
              active={live}
              context={JSON.stringify({ webviewSection: 'session', id: session.id, title: session.title, preventDefaultContextMenuItems: true })}
              onOpen={() => send({ type: 'openSession', sessionId: session.id })}
            >
              <div className="flex items-center gap-[7px]">
                {live ? <StatusMark needs={attention} /> : null}
                <span className={`min-w-0 flex-1 truncate ${live || session.unread ? 'font-semibold' : ''}`}>{session.title}</span>
              </div>
              <div className={`mt-[3px] truncate text-xs ${attention ? 'text-warning' : 'text-muted-foreground'}`}>
                {label(session.providerId)} · {state} · {relativeTime(session.updatedAt)}
              </div>
              {session.laneId ? <div className="mt-[3px] truncate font-mono text-[11px] text-muted-foreground">{session.laneId}</div> : null}
            </Row>
          )
        })}
        {data.groups.length + data.sessions.length === 0 ? <div className="px-2.5 py-3 text-xs text-muted-foreground">No chats yet. Start one with +.</div> : null}
      </div>
    </div>
  )
}
