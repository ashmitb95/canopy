import { type RefObject, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import type { PromptPart } from '../../../src/core/types'
import type { Attachment } from '../../../src/ui/protocol'
import { PromptEditor, type PromptEditorHandle } from '../composer/prompt-editor'
import { ask, send } from '../host'
import type { ChatState } from '../state'
import { Codicon } from './codicon'
import { ContextMeter } from './context-meter'
import { FilePill } from './file-pill'
import { LanePicker } from './lane-picker'
import { McpPopover } from './mcp-popover'
import { ModelPicker } from './model-picker'
import { ModePicker } from './mode-picker'

function AttachMenu({ editor }: { editor: RefObject<PromptEditorHandle | null> }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="icon-xs" variant="ghost" className="shrink-0 text-muted-foreground" aria-label="Attach">
          <Codicon name="attach" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem
          onSelect={async () => editor.current?.insert(await ask<Attachment[]>({ type: 'pickAttachments' }))}
        >
          <Codicon name="cloud-upload" />
          Upload from computer…
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => editor.current?.mention()}>
          <Codicon name="mention" />
          Add file from workspace…
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function Composer({ state }: { state: ChatState }) {
  const editor = useRef<PromptEditorHandle>(null)
  const [empty, setEmpty] = useState(true)
  const [includeContext, setIncludeContext] = useState(true)
  const busy = state.status === 'running' || state.status === 'needs-input'
  const context = includeContext ? state.editorContext : null
  const commands = state.facts.commands?.kind === 'commands' ? state.facts.commands.items : []

  // A file the user removed is offered again once they switch to another file.
  useEffect(() => setIncludeContext(true), [state.editorContext?.path])

  const submit = (parts: PromptPart[]) => send({ type: 'prompt', parts, includeContext: context !== null })

  return (
    <div className="@container rounded-xl border bg-input/40 focus-within:border-ring">
      {context && (
        <div className="px-3 pt-2">
          <FilePill path={context.path} range={context.range} label={context.label} onRemove={() => setIncludeContext(false)} />
        </div>
      )}
      <PromptEditor
        ref={editor}
        placeholder={busy ? 'Queue a follow-up…' : `Ask ${state.provider?.label ?? 'the agent'}… @ for files, / for commands`}
        commands={commands}
        onSubmit={submit}
        onEmptyChange={setEmpty}
      />
      <div className="flex items-center gap-1 px-2 pb-2">
        <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-hidden">
          <AttachMenu editor={editor} />
          <ModelPicker fact={state.facts.model?.kind === 'model' ? state.facts.model : undefined} />
          <ModePicker
            current={state.facts.mode?.kind === 'mode' ? state.facts.mode.current : (state.record?.mode ?? 'ask')}
            available={state.provider?.modes ?? []}
          />
          <LanePicker lanes={state.lanes} current={state.record?.laneId} />
          <McpPopover fact={state.facts.mcp?.kind === 'mcp' ? state.facts.mcp : undefined} />
        </div>
        <ContextMeter fact={state.facts.context?.kind === 'context' ? state.facts.context : undefined} />
        {busy ? (
          <Button key="stop" size="icon-sm" variant="secondary" className="shrink-0" aria-label="Stop" onClick={() => send({ type: 'cancel' })}>
            <Codicon name="debug-stop" />
          </Button>
        ) : (
          <Button key="send" size="icon-sm" className="shrink-0" aria-label="Send" disabled={empty} onClick={() => editor.current?.submit()}>
            <Codicon name="send" />
          </Button>
        )}
      </div>
    </div>
  )
}
