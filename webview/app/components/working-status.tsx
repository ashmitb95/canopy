import { Shimmer } from '@/components/ai-elements/shimmer'
import type { SessionStatus } from '../../../src/sessions/store'
import { elapsed } from '../format'
import { useNow } from '../use-now'
import { Codicon } from './codicon'

export function WorkingStatus({ status, since }: { status: SessionStatus; since?: number }) {
  const now = useNow(1000)
  const time = since ? ` ${elapsed(now - since)}` : ''
  if (status === 'running') {
    return (
      <Shimmer as="div" className="px-1 text-xs">
        {`Working…${time}`}
      </Shimmer>
    )
  }
  if (status === 'needs-input') {
    return (
      <div className="flex items-center gap-1.5 px-1 text-xs text-warning">
        <Codicon name="loading" size={12} spin />
        Waiting for your approval{time && ` ·${time}`}
      </div>
    )
  }
  return null
}
