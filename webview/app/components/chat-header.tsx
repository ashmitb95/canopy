import type { ChatState } from '../state'
import { ProviderAvatar } from './provider-avatar'
import { QuotaPill } from './quota-pill'
import { SessionSwitcher } from './session-switcher'
import { StatusBadge } from './status-badge'

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
      <StatusBadge status={state.status} />
    </header>
  )
}
