import { Button } from '@/components/ui/button'
import { Codicon } from '../components/codicon'
import { clockTime } from '../format'
import { send } from '../host'
import type { TurnFooter } from '../turns'

export function TurnFooterView({ footer, model }: { footer: TurnFooter; model?: string }) {
  const meta = [model, footer.at && clockTime(footer.at)].filter(Boolean).join(' · ')
  return (
    <div className="space-y-2">
      {footer.diffs.length > 0 && (
        <div className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs">
          <Codicon name="edit" className="text-muted-foreground" />
          <span className="font-medium">
            Edited {footer.files} {footer.files === 1 ? 'file' : 'files'}
          </span>
          <span className="text-success">+{footer.added}</span>
          <span className="text-destructive">−{footer.removed}</span>
          <span className="flex-1" />
          <Button size="xs" variant="ghost" onClick={() => send({ type: 'reviewChanges', itemIds: footer.diffs.map((diff) => diff.id) })}>
            Review changes
          </Button>
        </div>
      )}
      <div className="flex items-center gap-0.5 text-xs text-muted-foreground">
        {footer.reply && (
          <Button
            size="icon-xs"
            variant="ghost"
            aria-label="Copy reply"
            onClick={() => void navigator.clipboard.writeText(footer.reply?.text ?? '')}
          >
            <Codicon name="copy" size={12} />
          </Button>
        )}
        {footer.prompt && (
          <Button
            size="icon-xs"
            variant="ghost"
            aria-label="Send this prompt again"
            onClick={() => send({ type: 'prompt', parts: footer.prompt?.parts ?? [], includeContext: false })}
          >
            <Codicon name="refresh" size={12} />
          </Button>
        )}
        {meta && <span className="ml-1">{meta}</span>}
      </div>
    </div>
  )
}
