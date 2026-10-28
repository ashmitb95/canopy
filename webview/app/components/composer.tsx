import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { send } from '../host'
import type { ChatState } from '../state'
import { Codicon } from './codicon'
import { FilePill } from './file-pill'

export function Composer({ state }: { state: ChatState }) {
  const [text, setText] = useState('')
  const [includeContext, setIncludeContext] = useState(true)
  const busy = state.status === 'running' || state.status === 'needs-input'
  const context = includeContext ? state.editorContext : null

  // A file the user removed is offered again once they switch to another file.
  useEffect(() => setIncludeContext(true), [state.editorContext?.path])

  const submit = () => {
    if (!text.trim()) return
    send({ type: 'prompt', text, includeContext: context !== null })
    setText('')
  }

  return (
    <div className="rounded-xl border bg-input/40 focus-within:border-ring">
      {context && (
        <div className="px-3 pt-2">
          <FilePill
            path={context.path}
            range={context.range}
            label={context.label}
            onRemove={() => setIncludeContext(false)}
          />
        </div>
      )}
      <Textarea
        value={text}
        rows={1}
        placeholder={`Ask ${state.provider?.label ?? 'the agent'}…`}
        className="max-h-48 min-h-10 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0 dark:bg-transparent"
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault()
            submit()
          }
        }}
      />
      <div className="flex items-center gap-1 px-2 pb-2">
        <div className="flex-1" />
        {busy ? (
          <Button key="stop" size="icon-sm" variant="secondary" aria-label="Stop" onClick={() => send({ type: 'cancel' })}>
            <Codicon name="debug-stop" />
          </Button>
        ) : (
          <Button key="send" size="icon-sm" aria-label="Send" disabled={!text.trim()} onClick={submit}>
            <Codicon name="send" />
          </Button>
        )}
      </div>
    </div>
  )
}
