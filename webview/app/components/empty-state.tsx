import { Button } from '@/components/ui/button'
import type { ProviderInfo } from '../../../src/ui/protocol'
import { send } from '../host'
import { Codicon } from './codicon'
import { ProviderAvatar } from './provider-avatar'

export function EmptyState({ provider }: { provider?: ProviderInfo }) {
  const status = provider?.state.status
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-3 p-6 text-center">
      <ProviderAvatar providerId={provider?.id ?? 'claude'} className="size-10 text-base" />
      <div className="font-semibold">{provider?.label ?? 'Claude'}</div>
      {status === 'not-installed' ? (
        <p className="text-sm text-muted-foreground">
          The {provider?.label} CLI is not installed. <a href={provider?.installUrl}>Install it</a>, then reopen this view.
        </p>
      ) : status === 'signed-out' ? (
        <Button size="sm" onClick={() => send({ type: 'signIn' })}>
          Sign in
        </Button>
      ) : (
        <Button size="sm" onClick={() => send({ type: 'newChat' })}>
          <Codicon name="add" />
          New chat
        </Button>
      )}
    </div>
  )
}
