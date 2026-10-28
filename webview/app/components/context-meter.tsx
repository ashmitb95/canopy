import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { SessionFact } from '../../../src/core/types'

const RADIUS = 6
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

export function ContextMeter({ fact }: { fact?: Extract<SessionFact, { kind: 'context' }> }) {
  if (!fact || fact.maxTokens <= 0) return null
  const ratio = Math.min(fact.usedTokens / fact.maxTokens, 1)
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex items-center gap-1 px-1 text-xs text-muted-foreground">
          <svg width="16" height="16" viewBox="0 0 16 16" className="-rotate-90" aria-hidden>
            <circle cx="8" cy="8" r={RADIUS} fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2" />
            <circle
              cx="8"
              cy="8"
              r={RADIUS}
              fill="none"
              stroke="var(--info)"
              strokeWidth="2"
              strokeLinecap="round"
              strokeDasharray={CIRCUMFERENCE}
              strokeDashoffset={CIRCUMFERENCE * (1 - ratio)}
            />
          </svg>
          <span className="hidden @[20rem]:inline">{Math.round(ratio * 100)}%</span>
        </span>
      </TooltipTrigger>
      <TooltipContent>
        {fact.usedTokens.toLocaleString()} of {fact.maxTokens.toLocaleString()} context tokens used
      </TooltipContent>
    </Tooltip>
  )
}
