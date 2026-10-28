import { Button } from '@/components/ui/button'
import type { ProviderInfo } from '../../../src/ui/protocol'
import { send } from '../host'
import { Codicon } from './codicon'

export function SignInBanner({ provider }: { provider?: ProviderInfo }) {
  const status = provider?.state.status
  if (!provider || (status !== 'signed-out' && status !== 'not-installed')) return null
  return (
    <div className="flex items-center gap-2 rounded-md border border-warning/50 bg-warning/5 px-3 py-2 text-sm">
      <Codicon name="warning" className="text-warning" />
      {status === 'signed-out' ? (
        <>
          <span className="flex-1">You are signed out of {provider.label}.</span>
          <Button size="xs" onClick={() => send({ type: 'signIn' })}>
            Sign in
          </Button>
        </>
      ) : (
        <span className="flex-1">
          The {provider.label} CLI is not installed. <a href={provider.installUrl}>Install it</a>, then reload.
        </span>
      )}
    </div>
  )
}
