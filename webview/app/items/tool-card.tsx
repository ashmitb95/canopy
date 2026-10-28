import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'
import type { ToolItem, ToolKind } from '../../../src/core/types'
import { Codicon } from '../components/codicon'

const ICONS: Record<ToolKind, string> = {
  read: 'file',
  edit: 'edit',
  execute: 'terminal',
  search: 'search',
  fetch: 'globe',
  mcp: 'plug',
  other: 'tools'
}

const STATUS: Record<ToolItem['status'], { label: string; icon: string; className: string }> = {
  running: { label: 'Running', icon: 'loading', className: 'bg-info/15 text-info' },
  done: { label: 'Completed', icon: 'check', className: 'bg-success/15 text-success' },
  failed: { label: 'Failed', icon: 'close', className: 'bg-destructive/15 text-destructive' }
}

export function ToolCard({ item }: { item: ToolItem }) {
  const [verb, ...rest] = item.title.split(' ')
  const status = STATUS[item.status]
  const input = item.input === undefined ? null : JSON.stringify(item.input, null, 2)
  return (
    <Collapsible defaultOpen={item.status === 'failed'} className="group rounded-md border">
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-accent/50">
        <Codicon name={ICONS[item.toolKind]} className="text-muted-foreground" />
        <span className="font-medium">{verb}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-muted-foreground">{rest.join(' ')}</span>
        <span className={cn('inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium', status.className)}>
          <Codicon name={status.icon} size={10} spin={item.status === 'running'} />
          {status.label}
        </span>
        <Codicon name="chevron-down" className="text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-2 border-t px-3 py-2">
        {input && (
          <div>
            <div className="mb-1 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">Input</div>
            <pre className="max-h-40 overflow-auto rounded-md bg-code px-3 py-2 text-xs whitespace-pre-wrap">{input}</pre>
          </div>
        )}
        {item.output && (
          <div>
            <div className="mb-1 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">Output</div>
            <pre className="max-h-64 overflow-auto rounded-md bg-code px-3 py-2 text-xs whitespace-pre-wrap">{item.output}</pre>
          </div>
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}
