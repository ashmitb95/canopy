import type { SessionItem } from '../../../src/core/types'
import { ApprovalCard } from './approval-card'
import { AssistantMessageView } from './assistant-message'
import { DiffCard } from './diff-card'
import { NoticeView } from './notice'
import { PlanCard } from './plan-card'
import { QuestionCard } from './question-card'
import { ThoughtView } from './thought'
import { ToolCard } from './tool-card'
import { UserMessageView } from './user-message'

export function ItemView({ item, steps }: { item: SessionItem; steps?: SessionItem[] }) {
  switch (item.kind) {
    case 'message':
      return item.role === 'user' ? <UserMessageView item={item} /> : <AssistantMessageView item={item} />
    case 'thought':
      return <ThoughtView item={item} />
    case 'tool':
      return <ToolCard item={item} steps={steps} />
    case 'diff':
      return <DiffCard item={item} />
    case 'plan':
      return <PlanCard item={item} />
    case 'approval':
      return <ApprovalCard item={item} />
    case 'question':
      return <QuestionCard item={item} />
    case 'notice':
      return <NoticeView item={item} />
    case 'turn':
      return null
  }
}
