import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import type { McpServer, SessionFact } from '../../../src/core/types'
import { send } from '../host'
import { Codicon } from './codicon'

const STATES: Record<McpServer['status'], { label: string; dot: string }> = {
  connected: { label: 'Connected', dot: 'bg-success' },
  failed: { label: 'Failed', dot: 'bg-destructive' },
  'needs-auth': { label: 'Needs sign-in', dot: 'bg-warning' },
  pending: { label: 'Connecting…', dot: 'bg-muted-foreground' },
  disabled: { label: 'Disabled', dot: 'bg-muted-foreground/40' }
}

export function McpPopover({ fact }: { fact?: Extract<SessionFact, { kind: 'mcp' }> }) {
  if (!fact) return null
  const connected = fact.servers.filter((server) => server.status === 'connected').length
  const attention = fact.servers.some((server) => server.status === 'failed' || server.status === 'needs-auth')
  return (
    <Popover onOpenChange={(open) => open && send({ type: 'refreshMcp' })}>
      <PopoverTrigger asChild>
        <Button size="xs" variant="ghost" className="text-muted-foreground">
          <Codicon name="plug" size={12} />
          MCP {connected}
          {attention && <span className="size-1.5 rounded-full bg-warning" aria-label="Some servers need attention" />}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-0">
        <div className="flex items-center justify-between border-b px-3 py-2 text-xs font-medium">
          MCP servers
          <Button size="icon-xs" variant="ghost" aria-label="Refresh" onClick={() => send({ type: 'refreshMcp' })}>
            <Codicon name="refresh" size={12} />
          </Button>
        </div>
        {fact.servers.length === 0 ? (
          <p className="px-3 py-3 text-xs text-muted-foreground">No MCP servers are configured.</p>
        ) : (
          <ul className="max-h-80 overflow-auto py-1">
            {fact.servers.map((server) => (
              <McpServerRow key={server.name} server={server} />
            ))}
          </ul>
        )}
        <p className="border-t px-3 py-2 text-[11px] text-muted-foreground">
          Servers and their sign-ins come from the CLI's own configuration.
        </p>
      </PopoverContent>
    </Popover>
  )
}

function McpServerRow({ server }: { server: McpServer }) {
  const state = STATES[server.status]
  const details = [state.label, server.tools.length > 0 && `${server.tools.length} tools`, server.scope].filter(Boolean)
  return (
    <li className="flex items-start gap-2 px-3 py-1.5 text-xs">
      <span className={cn('mt-1 size-2 shrink-0 rounded-full', state.dot)} />
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{server.name}</div>
        <div className="truncate text-muted-foreground">{details.join(' · ')}</div>
        {server.error && <div className="mt-0.5 break-words text-destructive">{server.error}</div>}
      </div>
      {server.status === 'needs-auth' && (
        <Button
          size="xs"
          variant="secondary"
          onClick={() => send({ type: 'mcpSignIn', server: server.name, scope: server.scope })}
        >
          Sign in
        </Button>
      )}
      {(server.status === 'needs-auth' || server.status === 'failed') && (
        <Button size="xs" variant="ghost" onClick={() => send({ type: 'reconnectMcp', server: server.name })}>
          Reconnect
        </Button>
      )}
    </li>
  )
}
