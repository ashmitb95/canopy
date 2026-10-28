import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import type { ApprovalItem, SessionItem } from '../../../src/core/types'
import { Codicon } from '../components/codicon'
import { send } from '../host'

function answer(item: ApprovalItem, optionId: string): void {
  send({ type: 'answer', itemId: item.id, optionId })
}

function Kbd({ children }: { children: string }) {
  return <kbd className="ml-1 rounded border border-current/30 px-1 text-[10px] leading-4 opacity-80">{children}</kbd>
}

export function ApprovalCard({ item }: { item: ApprovalItem }) {
  if (item.resolved) {
    const label =
      item.resolved === 'expired' ? 'Expired' : (item.options.find((option) => option.id === item.resolved)?.label ?? item.resolved)
    return (
      <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
        <Codicon name="shield" size={12} />
        <span className="truncate">{item.title}</span>
        <span>· {label}</span>
      </div>
    )
  }
  const [primary, ...others] = item.options.filter((option) => option.id !== 'deny')
  const deny = item.options.find((option) => option.id === 'deny')
  return (
    <div className="space-y-2.5 rounded-lg border border-warning/50 bg-warning/5 p-3">
      <div className="flex items-center gap-2 font-medium">
        <Codicon name="shield" className="text-warning" />
        {item.title}
      </div>
      {item.detail && (
        <pre className="max-h-40 overflow-auto rounded-md bg-code px-3 py-2 text-xs whitespace-pre-wrap">{item.detail}</pre>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {primary && (
          <Button size="sm" onClick={() => answer(item, primary.id)}>
            {primary.label}
            <Kbd>⏎</Kbd>
          </Button>
        )}
        {others.map((option) => (
          <Button key={option.id} size="sm" variant="secondary" onClick={() => answer(item, option.id)}>
            {option.label}
          </Button>
        ))}
        {deny && (
          <Button size="sm" variant="ghost" className="ml-auto" onClick={() => answer(item, deny.id)}>
            {deny.label}
            <Kbd>esc</Kbd>
          </Button>
        )}
      </div>
    </div>
  )
}

/** Enter allows and Escape denies the oldest pending approval, unless the user is typing. */
export function useApprovalKeys(items: SessionItem[]): void {
  const pending = items.find((item): item is ApprovalItem => item.kind === 'approval' && !item.resolved)
  useEffect(() => {
    if (!pending) return
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.closest('textarea, input, [contenteditable="true"]')) return
      const allow = pending.options.find((option) => option.id !== 'deny')
      if (event.key === 'Enter' && allow) answer(pending, allow.id)
      else if (event.key === 'Escape') answer(pending, 'deny')
      else return
      event.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pending])
}
