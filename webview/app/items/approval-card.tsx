import { useEffect } from 'react'
import { MessageResponse } from '@/components/ai-elements/message'
import { Button } from '@/components/ui/button'
import type { ApprovalItem, PromptResponse, SessionItem } from '../../../src/core/types'
import { Codicon } from '../components/codicon'
import { send } from '../host'

function respond(item: ApprovalItem, response: PromptResponse): void {
  send({ type: 'answer', itemId: item.id, response })
}

const choose = (item: ApprovalItem, optionId: string) => respond(item, { kind: 'option', optionId })

function Kbd({ children }: { children: string }) {
  return <kbd className="ml-1 rounded border border-current/30 px-1 text-[10px] leading-4 opacity-80">{children}</kbd>
}

function resolvedLabel(item: ApprovalItem): string {
  if (item.resolved === 'expired') return 'Expired'
  if (item.resolved === 'dismissed') return 'Dismissed'
  return item.options.find((option) => option.id === item.resolved)?.label ?? item.resolved ?? ''
}

export function ApprovalCard({ item }: { item: ApprovalItem }) {
  if (item.resolved) {
    return (
      <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
        <Codicon name={item.subject?.kind === 'plan' ? 'checklist' : 'shield'} size={12} />
        <span className="truncate">{item.title}</span>
        <span>· {resolvedLabel(item)}</span>
      </div>
    )
  }
  const plan = item.subject?.kind === 'plan' ? item.subject : undefined
  const deny = item.options.find((option) => option.id === 'deny')
  const [primary, ...others] = item.options.filter((option) => option.id !== 'deny')
  const isLink = item.detail?.startsWith('https://')
  return (
    <div className="space-y-2.5 rounded-lg border border-warning/50 bg-warning/5 p-3">
      <div className="flex items-center gap-2 font-medium">
        <Codicon name={plan ? 'checklist' : 'shield'} className="text-warning" />
        {item.title}
      </div>
      {item.description && <p className="text-xs text-muted-foreground">{item.description}</p>}
      {item.reason && <p className="text-xs text-warning">{item.reason}</p>}
      {plan && (
        <div className="space-y-1.5">
          <div className="max-h-80 overflow-auto rounded-md border bg-background/50 p-3 text-sm">
            <MessageResponse>{plan.text}</MessageResponse>
          </div>
          {plan.filePath && (
            <button
              type="button"
              className="text-xs text-muted-foreground hover:underline"
              onClick={() => send({ type: 'openFile', path: plan.filePath ?? '' })}
            >
              Plan file: <span className="font-mono">{plan.filePath}</span>
            </button>
          )}
        </div>
      )}
      {item.detail &&
        (isLink ? (
          <a href={item.detail} className="block truncate text-sm">
            {item.detail}
          </a>
        ) : (
          <pre className="max-h-40 overflow-auto rounded-md bg-code px-3 py-2 text-xs whitespace-pre-wrap">{item.detail}</pre>
        ))}
      <div className="flex flex-wrap items-center gap-2">
        {primary && (
          <Button size="sm" onClick={() => choose(item, primary.id)}>
            {primary.label}
            <Kbd>⏎</Kbd>
          </Button>
        )}
        {others.map((option) => (
          <Button key={option.id} size="sm" variant="secondary" onClick={() => choose(item, option.id)}>
            {option.label}
          </Button>
        ))}
        {item.diffIds && item.diffIds.length > 0 && (
          <Button size="sm" variant="ghost" onClick={() => send({ type: 'reviewChanges', itemIds: item.diffIds ?? [] })}>
            <Codicon name="diff" />
            Review changes
          </Button>
        )}
        <span className="flex-1" />
        {deny ? (
          <Button size="sm" variant="ghost" onClick={() => choose(item, deny.id)}>
            {deny.label}
            <Kbd>esc</Kbd>
          </Button>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => respond(item, { kind: 'dismiss' })}>
            Dismiss
            <Kbd>esc</Kbd>
          </Button>
        )}
      </div>
    </div>
  )
}

/** Enter takes the first option and Escape denies or dismisses the oldest pending approval, unless the user is typing. */
export function useApprovalKeys(items: SessionItem[]): void {
  const pending = items.find((item): item is ApprovalItem => item.kind === 'approval' && !item.resolved)
  useEffect(() => {
    if (!pending) return
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.closest('textarea, input, [contenteditable="true"]')) return
      const primary = pending.options.find((option) => option.id !== 'deny')
      if (event.key === 'Enter' && primary) choose(pending, primary.id)
      else if (event.key === 'Escape') {
        if (pending.options.some((option) => option.id === 'deny')) choose(pending, 'deny')
        else respond(pending, { kind: 'dismiss' })
      } else return
      event.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pending])
}
