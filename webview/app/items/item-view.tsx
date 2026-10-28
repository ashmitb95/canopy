import type { SessionItem } from '../../../src/core/types'
import { ApprovalCard } from './approval-card'
import { AssistantMessageView } from './assistant-message'
import { DiffLine } from './diff-line'
import { NoticeView } from './notice'
import { PlanList } from './plan-list'
import { ThoughtView } from './thought'
import { ToolLine } from './tool-line'
import { UserMessageView } from './user-message'

export function ItemView({ item }: { item: SessionItem }) {
  switch (item.kind) {
    case 'message':
      return item.role === 'user' ? <UserMessageView item={item} /> : <AssistantMessageView item={item} />
    case 'thought':
      return <ThoughtView item={item} />
    case 'tool':
      return <ToolLine item={item} />
    case 'diff':
      return <DiffLine item={item} />
    case 'plan':
      return <PlanList item={item} />
    case 'approval':
      return <ApprovalCard item={item} />
    case 'notice':
      return <NoticeView item={item} />
    case 'turn':
      return null
  }
}
