import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'
import { cn } from '@/lib/utils'
import type { Quota } from '../../../src/core/types'
import { quotaAge, resetTime, shortWindow } from '../format'
import { useNow } from '../use-now'

const TONE = { ok: 'text-muted-foreground', warning: 'text-warning', limited: 'text-destructive' } as const
const BAR = { ok: 'bg-info', warning: 'bg-warning', limited: 'bg-destructive' } as const

export function QuotaPill({ label, quota, compact = false }: { label: string; quota?: Quota; compact?: boolean }) {
  const now = useNow(30_000)
  if (!quota || quota.windows.length === 0) return null
  const worst = quota.windows.some((window) => window.status === 'limited')
    ? 'limited'
    : quota.windows.some((window) => window.status === 'warning')
      ? 'warning'
      : 'ok'
  const shown = compact ? quota.windows.slice(0, 1) : quota.windows
  return (
    <HoverCard openDelay={150}>
      <HoverCardTrigger asChild>
        <button type="button" className={cn('shrink-0 rounded-md border px-2 py-0.5 text-xs whitespace-nowrap', TONE[worst])}>
          {shown.map((window) => `${shortWindow(window.label)} ${window.usedPercent}%`).join(' · ')}
        </button>
      </HoverCardTrigger>
      <HoverCardContent align="end" className="w-72 space-y-3 p-3 text-xs">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-sm font-semibold">{label} usage</span>
          <span className="text-muted-foreground">as of {quotaAge(quota.observedAt, now)}</span>
        </div>
        {quota.windows.map((window) => (
          <div key={window.label} className="space-y-1">
            <div className="flex justify-between">
              <span>{window.label}</span>
              <span className="font-medium">{window.usedPercent}%</span>
            </div>
            <div className="h-1 overflow-hidden rounded-full bg-muted">
              <div className={cn('h-full rounded-full', BAR[window.status])} style={{ width: `${Math.min(window.usedPercent, 100)}%` }} />
            </div>
            {window.resetsAt && <div className="text-muted-foreground">Resets {resetTime(window.resetsAt, now)}</div>}
          </div>
        ))}
        <p className="border-t pt-2 text-muted-foreground">Reported by the {label} CLI while a session runs.</p>
      </HoverCardContent>
    </HoverCard>
  )
}
