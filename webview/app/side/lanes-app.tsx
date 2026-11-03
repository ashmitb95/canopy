import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import type { LaneCard } from '../../../src/ui/protocol'
import { Codicon } from '../components/codicon'
import { ProviderAvatar } from '../components/provider-avatar'
import { onHostMessage, send } from '../host'

function Card({ lane }: { lane: LaneCard }) {
  const primary = lane.repos.some((repo) => repo.location === 'primary')
  return (
    <section aria-label={lane.name} data-card={primary ? 'primary' : ''} className={`flex flex-col gap-3 rounded-lg p-4 ${primary ? 'bg-primary/10 ring-2 ring-primary' : 'bg-muted'}`}>
      <header className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          {primary ? <div className="text-[10px] font-bold tracking-wider text-primary">PRIMARY CHECKOUT · RUNS HERE</div> : null}
          <h2 className="truncate font-mono text-sm font-semibold">{lane.name}</h2>
        </div>
        {primary ? (
          <Button size="sm" variant="outline" title="Free the primary checkout and keep this work in a worktree" onClick={() => send({ type: 'parkLane', laneId: lane.name })}>
            Move to a worktree
          </Button>
        ) : (
          <Button size="sm" variant="secondary" title={`Move ${lane.name} into the primary checkout`} onClick={() => send({ type: 'switchLane', laneId: lane.name })}>
            Switch here
          </Button>
        )}
        <Button size="sm" variant="ghost" aria-label={`Review ${lane.name}`} onClick={() => send({ type: 'reviewLane', laneId: lane.name })}>
          <Codicon name="diff" />
        </Button>
      </header>
      {lane.repos.length > 0 ? (
        <ul className="space-y-1 text-xs">
          {lane.repos.map((repo) => (
            <li key={repo.repo} className="flex items-center gap-2">
              <Codicon name="repo" size={12} />
              <span className="font-medium">{repo.repo}</span>
              <span className="text-muted-foreground">{repo.location === 'primary' ? 'primary checkout' : repo.slot}</span>
              {repo.dirty > 0 ? <span className="text-warning">●{repo.dirty} uncommitted</span> : null}
            </li>
          ))}
        </ul>
      ) : (
        <div className="text-xs text-muted-foreground">Not checked out anywhere. A chat is linked to it.</div>
      )}
      {lane.chats.length > 0 ? (
        <div className="space-y-0.5 border-t pt-2">
          {lane.chats.map((chat) => (
            <button
              key={chat.id}
              type="button"
              className="flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left hover:bg-accent"
              onClick={() => send(chat.kind === 'group' ? { type: 'openGroup', groupId: chat.id } : { type: 'openSession', sessionId: chat.id })}
            >
              <span className="flex -space-x-1.5">
                {chat.agents.slice(0, 3).map((agent) => (
                  <ProviderAvatar key={agent} providerId={agent} className="size-5 text-[10px] ring-1 ring-background" />
                ))}
              </span>
              <span className="min-w-0 flex-1 truncate">{chat.title}</span>
              <span className={`shrink-0 text-xs ${chat.needsYou ? 'text-warning' : 'text-muted-foreground'}`}>{chat.state}</span>
            </button>
          ))}
        </div>
      ) : null}
    </section>
  )
}

export function LanesApp() {
  const [lanes, setLanes] = useState<LaneCard[]>()
  useEffect(() => {
    const off = onHostMessage((message) => {
      if (message.type === 'laneCards') setLanes(message.lanes)
    })
    send({ type: 'ready' })
    return off
  }, [])
  if (!lanes) return null
  // The lane in the primary checkout leads; the rest keep Git's order.
  const ordered = [...lanes].sort((a, b) => Number(b.repos.some((repo) => repo.location === 'primary')) - Number(a.repos.some((repo) => repo.location === 'primary')))
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4 p-6 text-[13px]">
      <header className="flex items-center gap-3">
        <h1 className="flex-1 text-lg font-semibold">Lanes</h1>
        <Button onClick={() => send({ type: 'newLane' })}>
          <Codicon name="add" /> New worktree
        </Button>
      </header>
      {ordered.length > 0 ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-3">
          {ordered.map((lane) => (
            <Card key={lane.name} lane={lane} />
          ))}
        </div>
      ) : (
        <div className="rounded-lg bg-muted p-6 text-center text-muted-foreground">No lanes yet. A lane is a branch you work on: start one with New worktree.</div>
      )}
    </div>
  )
}
