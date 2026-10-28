import { Button } from '@/components/ui/button'
import type { DiffItem } from '../../../src/core/types'
import { Codicon } from '../components/codicon'
import { fileName } from '../format'
import { send } from '../host'

const MAX_LINES = 200

export function DiffCard({ item }: { item: DiffItem }) {
  const removed = item.oldText === null ? [] : item.oldText.split('\n')
  const added = item.newText.split('\n')
  const rows = [...removed.map((line) => ['-', line] as const), ...added.map((line) => ['+', line] as const)]
  return (
    <div className="overflow-hidden rounded-md border">
      <div className="flex items-center gap-2 border-b px-3 py-1.5 text-xs">
        <Codicon name="diff" className="text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate font-mono" title={item.path}>
          {fileName(item.path)}
        </span>
        <span className="text-success">+{added.length}</span>
        {removed.length > 0 && <span className="text-destructive">−{removed.length}</span>}
        <Button size="xs" variant="ghost" onClick={() => send({ type: 'openDiff', itemId: item.id })}>
          Open diff
        </Button>
      </div>
      <pre className="max-h-72 overflow-auto py-1 text-xs leading-5">
        {rows.slice(0, MAX_LINES).map(([sign, line], index) => (
          <div key={index} className={sign === '+' ? 'bg-diff-added px-3' : 'bg-diff-removed px-3'}>
            <span className="mr-2 text-muted-foreground select-none">{sign === '+' ? '+' : '−'}</span>
            {line}
          </div>
        ))}
        {rows.length > MAX_LINES && (
          <div className="px-3 text-muted-foreground">… {rows.length - MAX_LINES} more lines</div>
        )}
      </pre>
    </div>
  )
}
