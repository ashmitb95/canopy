import { useEffect, useState } from 'react'
import type { LaneCard } from '../../../src/ui/protocol'
import { ProviderAvatar } from '../components/provider-avatar'
import { onHostMessage, send } from '../host'

const TONE: Record<NonNullable<LaneCard['status']>['tone'], string> = { needs: 'text-warning', working: 'text-info', done: 'text-success', idle: 'text-muted-foreground' }

// Text and fills on the inverted primary card are mixed from its two colors, so they hold in any theme.
const ON_PRIMARY_SOFT = { color: 'color-mix(in srgb, var(--primary-foreground) 82%, var(--primary))' }
const ON_PRIMARY_FILL = { background: 'color-mix(in srgb, var(--primary-foreground) 12%, var(--primary))' }
const ON_PRIMARY_BUTTON = { background: 'color-mix(in srgb, var(--primary-foreground) 18%, var(--primary))' }

function Label({ children }: { children: string }) {
  return <div className="text-[11px] font-extrabold tracking-[0.08em] text-muted-foreground">{children}</div>
}

function Status({ status }: { status?: LaneCard['status'] }) {
  if (!status) return <div className="text-muted-foreground">No chat yet</div>
  return (
    <div className={`flex min-w-0 items-center gap-1.5 font-medium ${TONE[status.tone]}`}>
      <ProviderAvatar providerId={status.agent} className="size-5 rounded-md text-[10px]" />
      <span className="truncate">{status.text}</span>
    </div>
  )
}

function Primary({ lane }: { lane?: LaneCard }) {
  return (
    <section aria-label="Primary checkout" data-card="primary" className="flex flex-wrap gap-6 rounded-2xl bg-primary p-5 text-primary-foreground">
      <div className="min-w-[16rem] flex-1">
        <div className="text-[11px] font-extrabold tracking-[0.08em]" style={ON_PRIMARY_SOFT}>
          PRIMARY CHECKOUT · CODE RUNS HERE
        </div>
        <div className="mt-2 truncate font-mono text-[30px] leading-tight font-semibold">{lane?.name ?? 'base branch'}</div>
        <div className="mt-1 text-[15px]" style={ON_PRIMARY_SOFT}>
          {lane ? lane.goal ?? 'No goal set' : 'No lane is checked out here. Switch one in to run it.'}
        </div>
        {lane ? (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" className="h-10 rounded-lg bg-primary-foreground px-3.5 font-bold text-primary" onClick={() => send({ type: 'openLaneChat', laneId: lane.name })}>
              {lane.chats > 0 ? 'Open chat' : 'Start a chat'}
            </button>
            <button type="button" className="h-10 rounded-lg px-3.5 font-semibold" style={ON_PRIMARY_BUTTON} onClick={() => send({ type: 'reviewLane', laneId: lane.name })}>
              Review changes
            </button>
            <span className="ml-1.5" style={ON_PRIMARY_SOFT}>
              {lane.chats} {lane.chats === 1 ? 'chat' : 'chats'} · {lane.dirty} uncommitted
            </span>
          </div>
        ) : null}
      </div>
      {lane?.shared && lane.shared.length > 0 ? (
        <div className="w-80 max-w-full shrink-0 rounded-[10px] px-3.5 py-3" style={ON_PRIMARY_FILL}>
          <div className="text-[11px] font-extrabold tracking-[0.08em]" style={ON_PRIMARY_SOFT}>
            SHARED WITH OTHER LANES
          </div>
          {lane.shared.slice(0, 6).map((file) => (
            <div key={file.path} className="mt-[7px] flex justify-between gap-2.5 font-mono text-xs">
              <span className="truncate">{file.path}</span>
              <span className="shrink-0">
                +{file.added} −{file.removed}
              </span>
            </div>
          ))}
          {lane.shared.length > 6 ? <div className="mt-[7px] text-xs" style={ON_PRIMARY_SOFT}>and {lane.shared.length - 6} more</div> : null}
          <div className="mt-2 text-xs" style={ON_PRIMARY_SOFT}>
            Chats on other lanes get this on their next turn.
          </div>
        </div>
      ) : null}
    </section>
  )
}

function Warm({ lane }: { lane: LaneCard }) {
  return (
    <div data-card="" data-vscode-context={JSON.stringify({ webviewSection: 'lane', lane: { name: lane.name }, preventDefaultContextMenuItems: true })} className="flex min-w-0 flex-col gap-2 rounded-xl bg-surface p-3.5">
      <button type="button" className="truncate text-left font-mono text-[15px] font-semibold hover:underline" onClick={() => send({ type: 'openLaneChat', laneId: lane.name })}>
        {lane.name}
      </button>
      <div className="line-clamp-2 min-h-[34px] leading-[1.35] text-muted-foreground">{lane.goal ?? 'No goal set'}</div>
      <Status status={lane.status} />
      <div className="truncate font-mono text-xs text-muted-foreground">
        {lane.paths.join(' · ')}
        {lane.dirty > 0 ? ` · ${lane.dirty} uncommitted` : ''}
      </div>
      <div className="mt-0.5 flex gap-1.5">
        <button type="button" className="h-11 flex-1 rounded-lg bg-primary font-bold text-primary-foreground" onClick={() => send({ type: 'switchLane', laneId: lane.name })}>
          Run in primary
        </button>
        <button type="button" className="h-11 rounded-lg bg-control px-3 font-medium" title="Free the worktree; the branch stays" onClick={() => send({ type: 'parkLane', laneId: lane.name })}>
          Park
        </button>
      </div>
    </div>
  )
}

/** The lane view: in its own tab it listens for lane cards; inside the chat view it is handed them. */
export function LanesApp({ cards }: { cards?: LaneCard[] }) {
  const [own, setLanes] = useState<LaneCard[]>()
  useEffect(() => {
    if (cards) return
    const off = onHostMessage((message) => {
      if (message.type === 'laneCards') setLanes(message.lanes)
    })
    send({ type: 'ready' })
    return off
  }, [cards])
  const lanes = cards ?? own
  if (!lanes) return null
  const warm = lanes.filter((lane) => lane.place === 'warm')
  const cold = lanes.filter((lane) => lane.place === 'cold')
  return (
    <main className="flex min-h-screen flex-col gap-4 bg-page p-6 text-[13px]">
      <div className="flex items-center gap-3">
        <h1 className="flex-1 text-[26px] font-extrabold tracking-[-0.02em]">Lanes</h1>
        <button type="button" className="h-11 rounded-[9px] bg-primary px-4 font-bold text-primary-foreground" onClick={() => send({ type: 'newLane' })}>
          New worktree
        </button>
      </div>
      <Primary lane={lanes.find((lane) => lane.place === 'primary')} />
      <section aria-label="Warm lanes">
        <Label>WARM · WORKTREE READY</Label>
        {warm.length > 0 ? (
          <div className="mt-2 grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-3">
            {warm.map((lane) => (
              <Warm key={lane.name} lane={lane} />
            ))}
          </div>
        ) : (
          <p className="mt-2 text-muted-foreground">No lane has a worktree. New worktree starts one, ready to switch in.</p>
        )}
      </section>
      {cold.length > 0 ? (
        <section aria-label="Cold lanes">
          <Label>COLD · BRANCH ONLY</Label>
          <div className="mt-2 flex flex-wrap gap-2">
            {cold.map((lane) => (
              <div key={lane.name} data-card="" className="flex min-h-[52px] items-center gap-3 rounded-[10px] bg-band py-1 pr-1.5 pl-3.5" title={lane.goal}>
                <span className="font-mono font-medium">{lane.name}</span>
                <button type="button" className="h-11 rounded-[7px] bg-surface px-3 font-semibold" onClick={() => send({ type: 'warmUpLane', laneId: lane.name })}>
                  Warm up
                </button>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </main>
  )
}
