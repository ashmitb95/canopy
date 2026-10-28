import type { PlanItem } from '../../../src/core/types'
import { Codicon } from '../components/codicon'

const ICONS = { pending: 'circle-large-outline', in_progress: 'loading', done: 'pass-filled' } as const

export function PlanList({ item }: { item: PlanItem }) {
  return (
    <ul className="space-y-1 rounded-md border px-3 py-2 text-sm">
      {item.entries.map((entry, index) => (
        <li key={index} className="flex items-center gap-2">
          <Codicon name={ICONS[entry.status]} spin={entry.status === 'in_progress'} className="text-muted-foreground" />
          <span className={entry.status === 'done' ? 'text-muted-foreground line-through' : ''}>{entry.text}</span>
        </li>
      ))}
    </ul>
  )
}
