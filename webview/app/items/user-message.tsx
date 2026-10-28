import { Message, MessageContent } from '@/components/ai-elements/message'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { PromptPart, UserMessage } from '../../../src/core/types'
import { useAttachmentSrc } from '../assets'
import { Codicon } from '../components/codicon'
import { FilePill } from '../components/file-pill'
import { promptText } from '../format'

type Part<T extends PromptPart['type']> = Extract<PromptPart, { type: T }>

function ImageThumb({ image }: { image: Part<'image'> }) {
  const src = useAttachmentSrc(image.path)
  return src ? (
    <img src={src} alt={image.name} title={image.name} className="h-20 max-w-40 rounded border object-cover" />
  ) : (
    <span className="rounded border px-1.5 py-0.5 text-xs">{image.name}</span>
  )
}

function Pasted({ text }: { text: string }) {
  return (
    <Collapsible className="group rounded-md border text-xs">
      <CollapsibleTrigger className="flex w-full items-center gap-1.5 px-2 py-1 text-left text-muted-foreground">
        <Codicon name="note" size={12} />
        Pasted text · {text.split('\n').length} lines
        <Codicon name="chevron-down" size={12} className="ml-auto transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <pre className="max-h-60 overflow-auto border-t px-2 py-1.5 whitespace-pre-wrap">{text}</pre>
      </CollapsibleContent>
    </Collapsible>
  )
}

export function UserMessageView({ item }: { item: UserMessage }) {
  const of = <T extends PromptPart['type']>(type: T) => item.parts.filter((part): part is Part<T> => part.type === type)
  const commands = of('command')
  const files = of('file')
  const images = of('image')
  const text = promptText(item.parts)
  return (
    <Message from="user">
      <MessageContent>
        {(commands.length > 0 || text) && (
          <div className="whitespace-pre-wrap">
            {commands.map((command) => (
              <span key={command.name} className="mr-1 rounded border bg-muted px-1 font-mono text-xs">
                /{command.name}
              </span>
            ))}
            {text}
          </div>
        )}
        {of('pasted').map((pasted, index) => (
          <Pasted key={index} text={pasted.text} />
        ))}
        {images.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {images.map((image) => (
              <ImageThumb key={image.path} image={image} />
            ))}
          </div>
        )}
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
