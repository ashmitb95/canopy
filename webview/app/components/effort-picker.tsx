import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import type { SessionFact } from '../../../src/core/types'
import { send } from '../host'
import { Codicon } from './codicon'

const label = (effort: string) => effort.charAt(0).toUpperCase() + effort.slice(1)

/** Reasoning effort for models that offer levels. */
export function EffortPicker({ fact }: { fact?: Extract<SessionFact, { kind: 'effort' }> }) {
  if (!fact || fact.available.length === 0) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="xs" variant="ghost" className="text-muted-foreground" title="Reasoning effort">
          <Codicon name="lightbulb" size={12} />
          <span className="hidden @[26rem]:inline">{fact.current ? label(fact.current) : 'Effort'}</span>
          <Codicon name="chevron-down" size={12} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuRadioGroup value={fact.current ?? ''} onValueChange={(effort) => send({ type: 'setEffort', effort })}>
          {fact.available.map((effort) => (
            <DropdownMenuRadioItem key={effort} value={effort}>
              {label(effort)}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
