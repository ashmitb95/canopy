import type { SessionItem } from '../../../src/core/types'
import { ApprovalCard } from './approval-card'
import { AssistantMessageView } from './assistant-message'
import { DiffCard } from './diff-card'
import { NoticeView } from './notice'
import { PlanCard } from './plan-card'
import { ThoughtView } from './thought'
import { ToolCard } from './tool-card'
import { UserMessageView } from './user-message'

export function ItemView({ item }: { item: SessionItem }) {
  switch (item.kind) {
    case 'message':
      return item.role === 'user' ? <UserMessageView item={item} /> : <AssistantMessageView item={item} />
    case 'thought':
      return <ThoughtView item={item} />
    case 'tool':
      return <ToolCard item={item} />
    case 'diff':
      return <DiffCard item={item} />
    case 'plan':
      return <PlanCard item={item} />
    case 'approval':
      return <ApprovalCard item={item} />
    case 'notice':
      return <NoticeView item={item} />
    case 'turn':
      return null
  }
}
