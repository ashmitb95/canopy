import type { SessionStatus } from '../../../src/sessions/store'
import { cn } from '@/lib/utils'

const BADGES: Record<SessionStatus, { label: string; className: string } | null> = {
  idle: null,
  running: { label: 'Running', className: 'bg-info/15 text-info' },
  'needs-input': { label: 'Input', className: 'bg-warning/15 text-warning' },
  error: { label: 'Error', className: 'bg-destructive/15 text-destructive' },
  stopped: { label: 'Stopped', className: 'bg-muted text-muted-foreground' }
}

export function StatusBadge({ status }: { status: SessionStatus }) {
  const badge = BADGES[status]
  if (!badge) return null
  return (
    <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-medium', badge.className)}>{badge.label}</span>
  )
}
