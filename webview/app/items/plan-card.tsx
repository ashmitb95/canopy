import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { PlanItem } from '../../../src/core/types'
import { Codicon } from '../components/codicon'

const ICONS = { pending: 'circle-large-outline', in_progress: 'loading', done: 'pass-filled' } as const

export function PlanCard({ item }: { item: PlanItem }) {
  const done = item.entries.filter((entry) => entry.status === 'done').length
  return (
    <Collapsible defaultOpen className="group rounded-md border">
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-accent/50">
        <Codicon name="checklist" className="text-muted-foreground" />
        <span className="font-medium">Plan</span>
        <span className="flex-1 text-muted-foreground">
          {done} of {item.entries.length} done
        </span>
        <Codicon name="chevron-down" className="text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <div className="mx-3 mb-2 h-1 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-info transition-[width]"
          style={{ width: `${item.entries.length ? (done / item.entries.length) * 100 : 0}%` }}
        />
      </div>
      <CollapsibleContent className="border-t px-3 py-2">
        <ul className="space-y-1 text-sm">
          {item.entries.map((entry, index) => (
            <li key={index} className="flex items-center gap-2">
              <Codicon
                name={ICONS[entry.status]}
                spin={entry.status === 'in_progress'}
                className={entry.status === 'done' ? 'text-success' : 'text-muted-foreground'}
              />
              <span className={entry.status === 'done' ? 'text-muted-foreground line-through' : ''}>{entry.text}</span>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  )
}
