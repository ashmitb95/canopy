import type { ToolItem, ToolKind } from '../../../src/core/types'
import { Codicon } from '../components/codicon'

export const TOOL_ICONS: Record<ToolKind, string> = {
  read: 'file',
  edit: 'edit',
  execute: 'terminal',
  search: 'search',
  fetch: 'globe',
  mcp: 'plug',
  other: 'tools'
}

export function ToolStatusIcon({ status }: { status: ToolItem['status'] }) {
  if (status === 'running') return <Codicon name="loading" spin className="text-muted-foreground" />
  if (status === 'failed') return <Codicon name="error" className="text-destructive" />
  return <Codicon name="check" className="text-success" />
}

export function ToolLine({ item }: { item: ToolItem }) {
  return (
    <div className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs">
      <Codicon name={TOOL_ICONS[item.toolKind]} className="text-muted-foreground" />
      <span className="min-w-0 flex-1 truncate font-mono">{item.title}</span>
      <ToolStatusIcon status={item.status} />
    </div>
  )
}
