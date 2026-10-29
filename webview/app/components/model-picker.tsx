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

/** The picker entry for the current model: the CLI reports a concrete id; the picker lists aliases. */
export function selectedModel(fact: Extract<SessionFact, { kind: 'model' }>) {
  return fact.available.find((model) => model.id === fact.current) ?? fact.available.find((model) => model.resolved === fact.current)
}

export function ModelPicker({ fact }: { fact?: Extract<SessionFact, { kind: 'model' }> }) {
  if (!fact) return null
  // The CLI reports the concrete model id; the picker lists aliases that resolve to it.
  const selected = selectedModel(fact)
  // "Opus 5.5 (1M context)" shows as "Opus 5.5"; the menu keeps the full label.
  const label = (selected?.label ?? fact.current).split(' (')[0]
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="xs" variant="ghost" className="min-w-[4.5rem] max-w-40 shrink text-muted-foreground" title={selected?.label ?? fact.current}>
          <span className="min-w-0 truncate">{label}</span>
          <span className="hidden @[26rem]:inline-flex"><Codicon name="chevron-down" size={12} /></span>
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
