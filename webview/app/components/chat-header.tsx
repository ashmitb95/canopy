import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import { send } from '../host'
import type { ChatState } from '../state'
import { Codicon } from './codicon'
import { ProviderAvatar } from './provider-avatar'
import { QuotaPill } from './quota-pill'
import { SessionSwitcher } from './session-switcher'
import { StatusBadge } from './status-badge'

function ChatMenu({ state }: { state: ChatState }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="icon-xs" variant="ghost" className="shrink-0 text-muted-foreground" aria-label="Chat actions">
          <Codicon name="kebab-vertical" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {state.provider?.capabilities.includes('fork') && (
          <DropdownMenuItem onSelect={() => send({ type: 'forkSession' })}>Fork conversation</DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={() => send({ type: 'handOff' })}>Hand off to…</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => send({ type: 'renameSession' })}>Rename…</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem className="text-destructive" onSelect={() => send({ type: 'deleteSession' })}>
          Delete…
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function ChatHeader({ state }: { state: ChatState }) {
  if (!state.record) return null
  const label = state.provider?.label ?? state.record.providerId
  const quota = state.quotas[state.record.providerId]
  if (document.body.dataset.surface === 'view') {
    return (
      <header className="flex items-center gap-1.5 border-b px-2 py-1.5">
        <ProviderAvatar providerId={state.record.providerId} className="size-6 text-[11px]" />
        <SessionSwitcher state={state} />
        <QuotaPill label={label} quota={quota} compact />
        <ChatMenu state={state} />
        <StatusBadge status={state.status} />
      </header>
    )
  }
  return (
    <header className="flex items-center gap-2.5 border-b px-4 py-2.5">
      <ProviderAvatar providerId={state.record.providerId} />
      <div className="min-w-0 flex-1">
        <div className="truncate font-semibold">{state.record.title}</div>
        <div className="truncate text-xs text-muted-foreground">{label}</div>
      </div>
      <QuotaPill label={label} quota={quota} />
      <ChatMenu state={state} />
      <StatusBadge status={state.status} />
    </header>
  )
}
