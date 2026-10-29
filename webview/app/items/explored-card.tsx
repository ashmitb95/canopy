import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { ToolItem } from '../../../src/core/types'
import { Codicon } from '../components/codicon'
import { ToolCard } from './tool-card'

export function ExploredCard({ items }: { items: ToolItem[] }) {
  return (
    <Collapsible className="group">
      <CollapsibleTrigger className="flex items-center gap-2 px-1 text-xs text-muted-foreground hover:text-foreground">
        <Codicon name="search" size={12} />
        Explored {items.length} items
        <Codicon name="chevron-down" size={12} className="transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-1.5 space-y-1.5">
        {items.map((item) => (
          <ToolCard key={item.id} item={item} />
        ))}
      </CollapsibleContent>
    </Collapsible>
  )
}
