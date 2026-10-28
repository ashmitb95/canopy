import { Message, MessageContent, MessageResponse } from '@/components/ai-elements/message'
import type { AssistantMessage } from '../../../src/core/types'

export function AssistantMessageView({ item }: { item: AssistantMessage }) {
  return (
    <Message from="assistant">
      <MessageContent>
        <MessageResponse isAnimating={item.streaming}>{item.text}</MessageResponse>
      </MessageContent>
    </Message>
  )
}
