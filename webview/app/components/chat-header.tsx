import type { ChatState } from '../state'
import { ProviderAvatar } from './provider-avatar'
import { StatusBadge } from './status-badge'

export function ChatHeader({ state }: { state: ChatState }) {
  if (!state.record) return null
  return (
    <header className="flex items-center gap-2.5 border-b px-4 py-2.5">
      <ProviderAvatar providerId={state.record.providerId} />
      <div className="min-w-0 flex-1">
        <div className="truncate font-semibold">{state.record.title}</div>
        <div className="truncate text-xs text-muted-foreground">{state.provider?.label ?? state.record.providerId}</div>
      </div>
      <StatusBadge status={state.status} />
    </header>
  )
}
