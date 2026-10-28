import { Reasoning, ReasoningContent, ReasoningTrigger } from '@/components/ai-elements/reasoning'
import type { Thought } from '../../../src/core/types'

export function ThoughtView({ item }: { item: Thought }) {
  return (
    <Reasoning isStreaming={item.streaming}>
      <ReasoningTrigger />
      <ReasoningContent>{item.text}</ReasoningContent>
    </Reasoning>
  )
}
