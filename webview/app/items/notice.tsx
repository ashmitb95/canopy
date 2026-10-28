import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { NoticeItem } from '../../../src/core/types'
import { Codicon } from '../components/codicon'
import { send } from '../host'

const TONES = {
  error: { icon: 'error', className: 'border-destructive/50 bg-destructive/5' },
  warning: { icon: 'warning', className: 'border-warning/50 bg-warning/5' },
  info: { icon: 'info', className: 'bg-muted' }
} as const

export function NoticeView({ item }: { item: NoticeItem }) {
  const tone = TONES[item.level]
  return (
    <div className={cn('flex items-start gap-2 rounded-md border px-3 py-2 text-sm', tone.className)}>
      <Codicon name={tone.icon} className="mt-0.5" />
      <div className="min-w-0 flex-1 whitespace-pre-wrap">{item.text}</div>
      {item.action === 'sign-in' && (
        <Button size="xs" variant="secondary" onClick={() => send({ type: 'signIn' })}>
          Sign in
        </Button>
      )}
    </div>
  )
}
