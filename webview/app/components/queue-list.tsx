import type { QueuedPrompt } from '../../../src/sessions/manager'
import { promptText } from '../format'
import { send } from '../host'
import { Codicon } from './codicon'

export function QueueList({ queue }: { queue: QueuedPrompt[] }) {
  if (queue.length === 0) return null
  return (
    <div className="space-y-1">
      {queue.map((queued) => (
        <div key={queued.id} className="flex items-center gap-2 rounded-md border bg-card px-3 py-1.5 text-sm">
          <span className="text-xs text-muted-foreground">Queued</span>
          <span className="min-w-0 flex-1 truncate">{promptText(queued.parts)}</span>
          <button
            type="button"
            aria-label="Remove queued message"
            className="text-muted-foreground hover:text-foreground"
            onClick={() => send({ type: 'removeQueued', queuedId: queued.id })}
          >
            <Codicon name="close" />
          </button>
        </div>
      ))}
    </div>
  )
}
