import { type ReactNode, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import type { SideData } from '../../../src/ui/protocol'
import { relativeTime } from '../../../src/ui/time'
import { Codicon } from '../components/codicon'
import { ProviderAvatar } from '../components/provider-avatar'
import { onHostMessage, send } from '../host'

const STATUS: Record<string, { label: string; tone: string }> = {
  running: { label: 'Working', tone: 'text-info' },
  'needs-input': { label: 'Needs you', tone: 'text-warning' },
  error: { label: 'Failed', tone: 'text-destructive' },
  stopped: { label: 'Stopped', tone: 'text-muted-foreground' },
  idle: { label: 'Idle', tone: 'text-muted-foreground' }
}

function Section({ title, open, onToggle, action, children }: { title: string; open: boolean; onToggle: () => void; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex min-h-0 flex-col">
      <div className="flex items-center bg-muted">
        <button type="button" aria-expanded={open} className="flex h-8 flex-1 items-center gap-1.5 px-2 text-left text-[11px] font-bold tracking-wider" onClick={onToggle}>
          <Codicon name={open ? 'chevron-down' : 'chevron-right'} size={12} />
          {title}
        </button>
        {action}
      </div>
      {open ? children : null}
    </section>
  )
}

function Lanes({ lanes }: { lanes: NonNullable<SideData['lanes']> }) {
  const primary = lanes.filter((lane) => lane.primary)
  const warm = lanes.filter((lane) => !lane.primary && lane.warm)
  const cold = lanes.filter((lane) => !lane.primary && !lane.warm)
  return (
    <div className="space-y-1 p-2">
      {primary.length > 0 ? (
        primary.map((lane) => (
          <div key={lane.name} className="rounded-md bg-primary px-3 py-2 text-primary-foreground">
            <div className="text-[10px] font-bold tracking-wider">PRIMARY CHECKOUT · RUNS HERE</div>
            <div className="truncate font-mono font-semibold">{lane.name}</div>
          </div>
        ))
      ) : (
        <div className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">The primary checkout is on its base branch.</div>
      )}
      {warm.map((lane) => (
        <div key={lane.name} className="flex items-center gap-2 rounded-md bg-card py-1 pr-1 pl-3">
          <span className="min-w-0 flex-1">
            <span className="block truncate font-mono text-xs font-medium">{lane.name}</span>
            <span className="block truncate text-[11px] text-muted-foreground">{lane.where}</span>
          </span>
          <Button size="sm" variant="secondary" title={`Move ${lane.name} into the primary checkout`} onClick={() => send({ type: 'switchLane', laneId: lane.name })}>
            Switch
          </Button>
          <button type="button" aria-label={`Review ${lane.name}`} className="p-1 text-muted-foreground hover:text-foreground" onClick={() => send({ type: 'reviewLane', laneId: lane.name })}>
            <Codicon name="diff" />
          </button>
        </div>
      ))}
      {cold.length > 0 ? <div className="px-3 pt-1 text-[11px] text-muted-foreground">{cold.length} other lanes with chats</div> : null}
    </div>
  )
}

export function SideApp() {
  const [data, setData] = useState<SideData>()
  const [lanesOpen, setLanesOpen] = useState(true)
  const [sessionsOpen, setSessionsOpen] = useState(true)
  useEffect(() => {
    const off = onHostMessage((message) => {
      if (message.type === 'side') setData(message.side)
    })
    send({ type: 'ready' })
    return off
  }, [])
  if (!data) return null
  const needsYou = data.groups.filter((group) => group.needsYou).length + data.sessions.filter((session) => session.status === 'needs-input').length
  return (
    <div className="flex h-screen flex-col text-[13px]">
      {data.lanes ? (
        <Section
          title="LANES"
          open={lanesOpen}
          onToggle={() => setLanesOpen(!lanesOpen)}
          action={
            <>
            <button type="button" aria-label="Open the lane view" className="flex size-8 items-center justify-center text-muted-foreground hover:text-foreground" onClick={() => send({ type: 'openLanes' })}>
              <Codicon name="link-external" />
            </button>
            <button type="button" aria-label="New worktree" className="flex size-8 items-center justify-center text-muted-foreground hover:text-foreground" onClick={() => send({ type: 'newLane' })}>
              <Codicon name="add" />
            </button>
            </>
          }
        >
          <Lanes lanes={data.lanes} />
        </Section>
      ) : null}
      <Section
        title={needsYou > 0 ? `SESSIONS · ${needsYou} NEED${needsYou === 1 ? 'S' : ''} YOU` : 'SESSIONS'}
        open={sessionsOpen}
        onToggle={() => setSessionsOpen(!sessionsOpen)}
        action={
          <button type="button" aria-label="New group chat" className="flex size-8 items-center justify-center text-muted-foreground hover:text-foreground" onClick={() => send({ type: 'newGroupChat' })}>
            <Codicon name="add" />
          </button>
        }
      >
        <div className="min-h-0 flex-1 space-y-0.5 overflow-auto p-1.5">
          {data.groups.map((group) => (
            <button key={group.id} type="button" className={`flex w-full gap-2 rounded-md px-2 py-2 text-left hover:bg-accent ${group.needsYou ? 'bg-muted' : ''}`} onClick={() => send({ type: 'openGroup', groupId: group.id })}>
              <span className="flex -space-x-1.5 pt-0.5">
                {group.agents.slice(0, 3).map((agent) => (
                  <ProviderAvatar key={agent} providerId={agent} className="size-5 text-[10px] ring-1 ring-background" />
                ))}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-semibold">{group.title}</span>
                <span className={`block truncate text-xs ${group.needsYou ? 'text-warning' : group.running ? 'text-info' : 'text-muted-foreground'}`}>
                  {group.needsYou ? 'Needs you' : group.running ? `${group.running}: ${group.activity || 'working'}` : `Idle · lead ${group.lead}`}
                </span>
                {group.laneId ? <span className="block truncate font-mono text-[11px] text-muted-foreground">{group.laneId}</span> : null}
              </span>
            </button>
          ))}
          {data.sessions.map((session) => {
            const status = STATUS[session.status] ?? STATUS.idle
            return (
              <button key={session.id} type="button" className="flex w-full gap-2 rounded-md px-2 py-2 text-left hover:bg-accent" onClick={() => send({ type: 'openSession', sessionId: session.id })}>
                <ProviderAvatar providerId={session.providerId} className="size-5 text-[10px]" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-2">
                    <span className={`min-w-0 flex-1 truncate ${session.unread ? 'font-semibold' : ''}`}>{session.title}</span>
                    <span className="shrink-0 text-[11px] text-muted-foreground">{relativeTime(session.updatedAt)}</span>
                  </span>
                  <span className={`block truncate text-xs ${status.tone}`}>{session.unread && session.status === 'idle' ? 'Finished, unread' : status.label}</span>
                  {session.laneId ? <span className="block truncate font-mono text-[11px] text-muted-foreground">{session.laneId}</span> : null}
                </span>
              </button>
            )
          })}
          {data.groups.length + data.sessions.length === 0 ? <div className="px-2 py-3 text-xs text-muted-foreground">No chats yet. Start one with +.</div> : null}
        </div>
      </Section>
    </div>
  )
}
