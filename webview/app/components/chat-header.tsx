import type { ChatState } from '../state'
import { ProviderAvatar } from './provider-avatar'
import { SessionSwitcher } from './session-switcher'
import { StatusBadge } from './status-badge'

export function ChatHeader({ state }: { state: ChatState }) {
  if (!state.record) return null
  const compact = document.body.dataset.surface === 'view'
  return (
    <header className={compact ? 'flex items-center gap-2 border-b px-3 py-1.5' : 'flex items-center gap-2.5 border-b px-4 py-2.5'}>
      <ProviderAvatar providerId={state.record.providerId} className={compact ? 'size-6 text-[11px]' : undefined} />
      <div className="min-w-0 flex-1">
        <div className={compact ? 'truncate text-sm font-semibold' : 'truncate font-semibold'}>{state.record.title}</div>
        {!compact && (
          <div className="truncate text-xs text-muted-foreground">{state.provider?.label ?? state.record.providerId}</div>
        )}
      </div>
      <StatusBadge status={state.status} />
      {compact && <SessionSwitcher state={state} />}
    </header>
  )
}
