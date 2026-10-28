import { Shimmer } from '@/components/ai-elements/shimmer'
import type { SessionStatus } from '../../../src/sessions/store'
import { Codicon } from './codicon'

export function WorkingStatus({ status }: { status: SessionStatus }) {
  if (status === 'running') {
    return (
      <Shimmer as="div" className="px-1 text-xs">
        Working…
      </Shimmer>
    )
  }
  if (status === 'needs-input') {
    return (
      <div className="flex items-center gap-1.5 px-1 text-xs text-warning">
        <Codicon name="loading" size={12} spin />
        Waiting for your approval
      </div>
    )
  }
  return null
}
