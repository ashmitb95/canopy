import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import { relativeTime } from '../../../src/ui/time'
import { send } from '../host'
import type { ChatState } from '../state'
import { Codicon } from './codicon'
import { ProviderAvatar } from './provider-avatar'

export function SessionSwitcher({ state }: { state: ChatState }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="icon-sm" variant="ghost" aria-label="Switch session">
          <Codicon name="history" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        {state.providers
          .filter((provider) => provider.state.status !== 'not-installed')
          .map((provider) => (
            <DropdownMenuItem key={provider.id} onSelect={() => send({ type: 'newChat', providerId: provider.id })}>
              <ProviderAvatar providerId={provider.id} className="size-5 text-[10px]" />
              New {provider.label} chat
            </DropdownMenuItem>
          ))}
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-xs text-muted-foreground">Recent</DropdownMenuLabel>
        {state.sessions.map((session) => (
          <DropdownMenuItem key={session.id} onSelect={() => send({ type: 'switchSession', sessionId: session.id })}>
            <ProviderAvatar providerId={session.providerId} className="size-5 text-[10px]" />
            <span className="min-w-0 flex-1 truncate">{session.title}</span>
            <span className="text-xs text-muted-foreground">{relativeTime(session.updatedAt)}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
