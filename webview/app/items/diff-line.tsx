import type { DiffItem } from '../../../src/core/types'
import { Codicon } from '../components/codicon'
import { fileName } from '../format'

export function DiffLine({ item }: { item: DiffItem }) {
  return (
    <div className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs">
      <Codicon name="diff" className="text-muted-foreground" />
      <span className="min-w-0 flex-1 truncate font-mono" title={item.path}>
        {item.oldText === null ? 'Created' : 'Edited'} {fileName(item.path)}
      </span>
    </div>
  )
}
