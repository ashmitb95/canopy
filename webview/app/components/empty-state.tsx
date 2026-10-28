import { Shimmer } from '@/components/ai-elements/shimmer'
import { Button } from '@/components/ui/button'
import type { ProviderInfo } from '../../../src/ui/protocol'
import { send } from '../host'
import { Codicon } from './codicon'
import { ProviderAvatar } from './provider-avatar'

/** Shown by a tab or the sidebar before a chat exists: pick who to work with. */
export function EmptyState({ providers }: { providers: ProviderInfo[] }) {
  return (
    <div className="flex h-screen flex-col justify-center gap-4 p-4">
      <div className="text-center">
        <div className="font-semibold">Start a chat</div>
        <div className="text-xs text-muted-foreground">Each agent runs through its own CLI and sign-in.</div>
      </div>
      {providers.length === 0 ? (
        <Shimmer as="div" className="text-center text-xs">
          Checking providers…
        </Shimmer>
      ) : (
        <div className="mx-auto flex w-full max-w-sm flex-col gap-2">
          {providers.map((provider) => (
            <ProviderCard key={provider.id} provider={provider} />
          ))}
        </div>
      )}
    </div>
  )
}

function ProviderCard({ provider }: { provider: ProviderInfo }) {
  const { status, account, version } = provider.state
  const detail =
    status === 'signed-in'
      ? [account, version && `v${version}`].filter(Boolean).join(' · ') || 'Signed in'
      : status === 'signed-out'
        ? 'Signed out'
        : status === 'not-installed'
          ? 'Not installed'
          : 'Status unknown'
  const body = (
    <>
      <ProviderAvatar providerId={provider.id} />
      <div className="min-w-0 flex-1 text-left">
        <div className="font-medium">{provider.label}</div>
        <div className="truncate text-xs text-muted-foreground">{detail}</div>
      </div>
    </>
  )
  if (status === 'signed-in' || status === 'unknown') {
    return (
      <button
        type="button"
        className="flex items-center gap-3 rounded-lg border px-3 py-2.5 hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring"
        onClick={() => send({ type: 'newChat', providerId: provider.id })}
      >
        {body}
        <Codicon name="arrow-right" className="text-muted-foreground" />
      </button>
    )
  }
  return (
    <div className="flex items-center gap-3 rounded-lg border px-3 py-2.5">
      {body}
      {status === 'signed-out' ? (
        <Button size="xs" variant="secondary" onClick={() => send({ type: 'signIn', providerId: provider.id })}>
          Sign in
        </Button>
      ) : (
        <Button size="xs" variant="secondary" asChild>
          <a href={provider.installUrl}>Install</a>
        </Button>
      )}
    </div>
  )
}
