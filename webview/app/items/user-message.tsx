import { Message, MessageContent } from '@/components/ai-elements/message'
import type { PromptPart, UserMessage } from '../../../src/core/types'
import { FilePill } from '../components/file-pill'
import { promptText } from '../format'

export function UserMessageView({ item }: { item: UserMessage }) {
  const files = item.parts.filter((part): part is Extract<PromptPart, { type: 'file' }> => part.type === 'file')
  return (
    <Message from="user">
      <MessageContent>
        <div className="whitespace-pre-wrap">{promptText(item.parts)}</div>
        {files.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {files.map((file) => (
              <FilePill key={file.path} path={file.path} range={file.range} />
            ))}
          </div>
        )}
      </MessageContent>
    </Message>
  )
}
