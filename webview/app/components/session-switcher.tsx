import { useState } from 'react'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import type { SessionStatus } from '../../../src/sessions/store'
import type { WebviewMessage } from '../../../src/ui/protocol'
import { relativeTime } from '../../../src/ui/time'
import { shortWindow } from '../format'
import { send } from '../host'
import type { ChatState } from '../state'
import { Codicon } from './codicon'
import { ProviderAvatar } from './provider-avatar'

function StatusDot({ status }: { status: SessionStatus }) {
  if (status === 'running') return <Codicon name="loading" size={12} spin className="text-info" />
  const color = status === 'needs-input' ? 'bg-warning' : status === 'error' ? 'bg-destructive' : 'border border-muted-foreground'
  return <span className={cn('mx-0.5 size-2 shrink-0 rounded-full', color)} />
}

/** The sidebar header: the session title opens a searchable list of new chats and recent sessions. */
export function SessionSwitcher({ state }: { state: ChatState }) {
  const [open, setOpen] = useState(false)
  const [highlighted, setHighlighted] = useState('')
  const choose = (message: WebviewMessage) => {
    setOpen(false)
    send(message)
  }
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button" className="flex min-w-0 flex-1 items-center gap-1 rounded-md px-1 py-0.5 text-left hover:bg-accent">
          <span className="truncate text-sm font-semibold">{state.record?.title ?? 'New chat'}</span>
          <Codicon name="chevron-down" size={12} className="shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-0">
        <Command
          value={highlighted}
          onValueChange={setHighlighted}
          onKeyDown={(event) => {
            if (event.key !== 'Enter' || !(event.metaKey || event.ctrlKey) || !highlighted.startsWith('session:')) return
            event.preventDefault()
            choose({ type: 'openSession', sessionId: highlighted.slice('session:'.length) })
          }}
        >
          <CommandInput placeholder="Search sessions or start a new chat…" />
          <CommandList>
            <CommandEmpty>No matching sessions.</CommandEmpty>
            <CommandGroup heading="New chat">
              {state.providers.map((provider) => {
                const status = provider.state.status
                const quota = state.quotas[provider.id]?.windows[0]
                return (
                  <CommandItem
                    key={provider.id}
                    value={`new:${provider.id}`}
                    keywords={[provider.label, 'new chat']}
                    disabled={status === 'not-installed'}
                    onSelect={() =>
                      choose(status === 'signed-out' ? { type: 'signIn', providerId: provider.id } : { type: 'newChat', providerId: provider.id })
                    }
                  >
                    <ProviderAvatar providerId={provider.id} className="size-5 text-[10px]" />
                    <span className="flex-1">{provider.label}</span>
                    {status === 'signed-out' ? (
                      <span className="text-xs text-warning">Sign in</span>
                    ) : status === 'not-installed' ? (
                      <span className="text-xs text-muted-foreground">Not installed</span>
                    ) : (
                      quota && <span className="text-xs text-muted-foreground">{`${shortWindow(quota.label)} ${quota.usedPercent}%`}</span>
                    )}
                  </CommandItem>
                )
              })}
            </CommandGroup>
            <CommandSeparator />
            <CommandGroup heading="Recent">
              {state.sessions.map((session) => (
                <CommandItem
                  key={session.id}
                  value={`session:${session.id}`}
                  keywords={[session.title]}
                  onSelect={() => choose({ type: 'switchSession', sessionId: session.id })}
                >
                  <StatusDot status={session.status} />
                  <span className="min-w-0 flex-1 truncate">{session.title}</span>
                  {session.inTab && <span className="rounded border px-1 text-[10px] text-muted-foreground">in tab</span>}
                  <span className="text-xs text-muted-foreground">{relativeTime(session.updatedAt)}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
          <div className="flex gap-3 border-t px-3 py-1.5 text-[11px] text-muted-foreground">
            <span>↑↓ navigate</span>
            <span>↵ open</span>
            <span>⌘↵ open in tab</span>
          </div>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
