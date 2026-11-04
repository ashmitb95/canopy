import { Shimmer } from '@/components/ai-elements/shimmer'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { ProviderInfo, SignInProgress } from '../../../src/ui/protocol'
import { send } from '../host'
import { Codicon } from './codicon'
import { ProviderAvatar } from './provider-avatar'

const READY = new Set(['signed-in', 'unknown'])

/** Shown by a tab or the sidebar before a chat exists: who is ready, and how to get the rest ready. */
export function EmptyState({ providers, signIns }: { providers: ProviderInfo[]; signIns: Record<string, SignInProgress> }) {
  const ready = providers.filter((provider) => READY.has(provider.state.status)).length
  return (
    <div className="@container flex min-h-screen flex-col justify-center gap-5 p-4">
      <div className="mx-auto max-w-lg space-y-2 text-center">
        {providers.length > 0 && (
          <span className="inline-block rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
            {ready} of {providers.length} providers ready
          </span>
        )}
        <div className="text-lg font-semibold @[36rem]:text-2xl">Your agents, one chat</div>
        <p className="text-xs text-muted-foreground @[36rem]:text-sm">
          Canopy runs each provider's own CLI on your own subscription. Sign-ins stay with those CLIs; nothing is stored here.
        </p>
      </div>
      {providers.length === 0 ? (
        <Shimmer as="div" className="text-center text-xs">
          Checking providers…
        </Shimmer>
      ) : (
        <div className="mx-auto grid w-full max-w-4xl grid-cols-1 gap-3 @[44rem]:grid-cols-3">
          {providers.map((provider) => (
            <ProviderCard key={provider.id} provider={provider} progress={signIns[provider.id]} />
          ))}
        </div>
      )}
      <button
        type="button"
        className="mx-auto inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        onClick={() => send({ type: 'refreshProviders' })}
      >
        <Codicon name="refresh" size={12} />
        Check again
      </button>
    </div>
  )
}

function ProviderCard({ provider, progress }: { provider: ProviderInfo; progress?: SignInProgress }) {
  const { status, account, version } = provider.state
  const ready = READY.has(status)
  const badge = ready
    ? { label: 'Ready', className: 'bg-success/15 text-success' }
    : status === 'signed-out'
      ? { label: 'Signed out', className: 'bg-warning/15 text-warning' }
      : { label: 'Not installed', className: 'bg-muted text-muted-foreground' }
  return (
    <div className={cn('flex flex-col gap-3 rounded-lg border p-3', progress && 'border-ring')}>
      <div className="flex items-center gap-2.5">
        <ProviderAvatar providerId={provider.id} />
        <div className="min-w-0 flex-1">
          <div className="font-medium">{provider.label}</div>
          <div className="truncate text-xs text-muted-foreground">{version ? `v${version}` : status === 'not-installed' ? 'CLI not found' : ''}</div>
        </div>
        <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-medium', badge.className)}>{progress ? 'Signing in' : badge.label}</span>
      </div>
      {progress ? (
        <SignInSteps providerId={provider.id} label={provider.label} progress={progress} />
      ) : (
        <>
          <p className="flex-1 text-xs text-muted-foreground">
            {ready
              ? account
                ? `Signed in as ${account}.`
                : 'Ready to chat.'
              : status === 'signed-out'
                ? `Installed. Sign in with your ${provider.label} account to start chatting.`
                : `Install the ${provider.label} CLI, then press Check again.`}
          </p>
          {ready ? (
            <Button size="sm" onClick={() => send({ type: 'newChat', providerId: provider.id })}>
              Start a chat
            </Button>
          ) : status === 'signed-out' ? (
            <Button size="sm" variant="secondary" onClick={() => send({ type: 'signIn', providerId: provider.id })}>
              Sign in
            </Button>
          ) : (
            <Button size="sm" variant="secondary" asChild>
              <a href={provider.installUrl}>Installation guide</a>
            </Button>
          )}
        </>
      )}
    </div>
  )
}

function SignInSteps({ providerId, label, progress }: { providerId: string; label: string; progress: SignInProgress }) {
  const step = progress.step === 'starting' ? 1 : 2
  const steps = [
    { title: 'Start sign-in', detail: `Runs ${label}'s own login` },
    {
      title: 'Approve in your browser',
      detail: progress.step === 'link' && progress.code ? `Confirm the code ${progress.code}` : 'Opened in your browser'
    },
    { title: 'Confirm account', detail: 'Checked automatically' }
  ]
  return (
    <div className="space-y-2.5">
      {progress.step === 'failed' ? (
        <div className="space-y-2">
          <p className="text-xs whitespace-pre-wrap text-destructive">{progress.message}</p>
          <div className="flex flex-wrap gap-2">
            <Button size="xs" onClick={() => send({ type: 'signIn', providerId })}>
              Try again
            </Button>
            <Button size="xs" variant="secondary" onClick={() => send({ type: 'signInInTerminal', providerId })}>
              Sign in in terminal
            </Button>
            <Button size="xs" variant="ghost" onClick={() => send({ type: 'cancelSignIn', providerId })}>
              Dismiss
            </Button>
          </div>
        </div>
      ) : (
        <>
          <ol className="space-y-1.5">
            {steps.map((entry, index) => {
              const number = index + 1
              const state = number < step ? 'done' : number === step ? 'active' : 'todo'
              return (
                <li key={entry.title} className="flex items-start gap-2 text-xs">
                  {state === 'done' ? (
                    <Codicon name="pass-filled" className="mt-0.5 text-success" />
                  ) : (
                    <span
                      className={cn(
                        'mt-0.5 inline-flex size-3.5 shrink-0 items-center justify-center rounded-full border text-[9px]',
                        state === 'active' ? 'border-info text-info' : 'text-muted-foreground'
                      )}
                    >
                      {number}
                    </span>
                  )}
                  <div>
                    <div className={state === 'todo' ? 'text-muted-foreground' : 'font-medium'}>{entry.title}</div>
                    <div className="text-muted-foreground">{entry.detail}</div>
                  </div>
                </li>
              )
            })}
          </ol>
          <div className="flex flex-wrap items-center gap-2 border-t pt-2 text-xs text-muted-foreground">
            {progress.step === 'link' ? (
              <>
                <span className="flex-1">Browser didn't open?</span>
                <Button size="xs" variant="secondary" onClick={() => void navigator.clipboard.writeText(progress.url)}>
                  Copy sign-in link
                </Button>
              </>
            ) : (
              <span className="flex-1">Starting {label}'s login…</span>
            )}
            <Button size="xs" variant="ghost" onClick={() => send({ type: 'cancelSignIn', providerId })}>
              Cancel
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
