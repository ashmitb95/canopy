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

export function ModelPicker({ fact }: { fact?: Extract<SessionFact, { kind: 'model' }> }) {
  if (!fact) return null
  // The CLI reports the concrete model id; the picker lists aliases that resolve to it.
  const selected =
    fact.available.find((model) => model.id === fact.current) ??
    fact.available.find((model) => model.resolved === fact.current)
  const label = selected?.label ?? fact.current
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="xs" variant="ghost" className="text-muted-foreground">
          {label}
          <Codicon name="chevron-down" size={12} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-w-80">
        <DropdownMenuRadioGroup value={selected?.id ?? fact.current} onValueChange={(model) => send({ type: 'setModel', model })}>
          {fact.available.map((model) => (
            <DropdownMenuRadioItem key={model.id} value={model.id} className="items-start">
              <div className="min-w-0">
                <div>{model.label}</div>
                {model.description && <div className="text-xs text-muted-foreground">{model.description}</div>}
              </div>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
