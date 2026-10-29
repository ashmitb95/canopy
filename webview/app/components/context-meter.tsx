import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { SessionFact } from '../../../src/core/types'
import { send } from '../host'

const RADIUS = 6
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

/** Context used, the session's API-equivalent cost when the provider reports it, and Compact. */
export function ContextMeter({ fact, canCompact }: { fact?: Extract<SessionFact, { kind: 'context' }>; canCompact: boolean }) {
  if (!fact || fact.maxTokens <= 0) return null
  const ratio = Math.min(fact.usedTokens / fact.maxTokens, 1)
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button type="button" className="inline-flex items-center gap-1 rounded px-1 text-xs text-muted-foreground hover:bg-accent" aria-label="Context">
          <svg width="16" height="16" viewBox="0 0 16 16" className="-rotate-90" aria-hidden>
            <circle cx="8" cy="8" r={RADIUS} fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2" />
            <circle
              cx="8"
              cy="8"
              r={RADIUS}
              fill="none"
              stroke={ratio > 0.85 ? 'var(--warning)' : 'var(--info)'}
              strokeWidth="2"
              strokeLinecap="round"
              strokeDasharray={CIRCUMFERENCE}
              strokeDashoffset={CIRCUMFERENCE * (1 - ratio)}
            />
          </svg>
          <span className="hidden @[20rem]:inline">{Math.round(ratio * 100)}%</span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 space-y-2 text-xs">
        <div className="font-medium">Context</div>
        <div className="text-muted-foreground">
          {fact.usedTokens.toLocaleString()} of {fact.maxTokens.toLocaleString()} tokens ({Math.round(ratio * 100)}%)
        </div>
        {fact.costUsd !== undefined && (
          <div className="text-muted-foreground">
            Session at API prices: ${fact.costUsd.toFixed(2)} <span className="opacity-70">(not billed on a subscription)</span>
          </div>
        )}
        {canCompact && (
          <Button size="sm" variant="secondary" className="w-full" onClick={() => send({ type: 'compact' })}>
            Compact conversation
          </Button>
        )}
      </PopoverContent>
    </Popover>
  )
}
