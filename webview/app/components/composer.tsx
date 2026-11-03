import type { JSONContent } from '@tiptap/core'
import { type RefObject, useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { PromptPart } from '../../../src/core/types'
import type { Attachment } from '../../../src/ui/protocol'
import { Drafts } from '../composer/drafts'
import { onEdit } from '../composer/edit-bus'
import { toDocument } from '../composer/prompt-document'
import { PromptEditor, type PromptEditorHandle } from '../composer/prompt-editor'
import { ask, onHostMessage, persisted, send } from '../host'
import type { ChatState } from '../state'
import { Codicon } from './codicon'
import { ContextMeter } from './context-meter'
import { EffortPicker } from './effort-picker'
import { FilePill } from './file-pill'
import { LanePicker } from './lane-picker'
import { McpPopover } from './mcp-popover'
import { ModelPicker } from './model-picker'
import { MODES, ModePicker } from './mode-picker'

const isEmptyDoc = (doc: JSONContent) => !(doc.content ?? []).some((block) => (block.content ?? []).length > 0)

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

/** In a group chat: the agents for the @ menu, the placeholder, and whether a message can go while an agent works. */
type GroupOptions = { agents: { id: string; label: string; detail?: string }[]; placeholder: string }

/** Settings changed now and then: kept behind one button, so the composer row stays clear. */
function Options({ state }: { state: ChatState }) {
  const mode = state.facts.mode?.kind === 'mode' ? state.facts.mode.current : (state.record?.mode ?? 'ask')
  const effort = state.facts.effort?.kind === 'effort' ? state.facts.effort : undefined
  const summary = [MODES[mode].label, ...(effort?.current ? [effort.current.charAt(0).toUpperCase() + effort.current.slice(1)] : [])].join(' · ')
  const row = (label: string, control: React.ReactNode) =>
    control ? (
      <div className="flex min-h-9 items-center gap-3">
        <span className="w-24 shrink-0 text-xs text-muted-foreground">{label}</span>
        {control}
      </div>
    ) : null
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button size="xs" variant="ghost" className="min-w-0 text-muted-foreground" title="Permissions, effort, lane, and MCP">
          <Codicon name="settings" size={12} />
          <span className="truncate">{summary}</span>
          <Codicon name="chevron-down" size={12} />
        </Button>
      </PopoverTrigger>
      {/* The pickers hide their labels in a narrow composer; here there is room, so the labels show. */}
      <PopoverContent align="start" className="w-auto min-w-64 p-2 [&_.hidden]:inline-flex">
        {row('Permissions', <ModePicker current={mode} available={state.provider?.modes ?? []} />)}
        {row('Effort', <EffortPicker fact={effort} />)}
        {row('Lane', <LanePicker lanes={state.lanes} current={state.record?.laneId} />)}
        {row('MCP servers', <McpPopover fact={state.facts.mcp?.kind === 'mcp' ? state.facts.mcp : undefined} />)}
      </PopoverContent>
    </Popover>
  )
}

export function Composer({ state, group }: { state: ChatState; group?: GroupOptions }) {
  const editor = useRef<PromptEditorHandle>(null)
  const [empty, setEmpty] = useState(true)
  const [includeContext, setIncludeContext] = useState(true)
  const busy = state.status === 'running' || state.status === 'needs-input'
  const context = includeContext ? state.editorContext : null
  const commands = state.facts.commands?.kind === 'commands' ? state.facts.commands.items : []

  const drafts = useMemo(() => new Drafts(persisted), [])
  const history = useMemo(
    () => state.items.flatMap((item) => (item.kind === 'message' && item.role === 'user' ? [item.parts] : [])),
    [state.items]
  )

  useEffect(() => {
    editor.current?.setContent(state.sessionId ? drafts.load(state.sessionId) : undefined)
  }, [state.sessionId, drafts])

  useEffect(() => onEdit((parts) => editor.current?.setContent(toDocument(parts))), [])

  useEffect(
    () =>
      onHostMessage((message) => {
        if (message.type === 'insertAttachments') editor.current?.insert(message.attachments)
        if (message.type === 'editPrompt') editor.current?.setContent(toDocument(message.parts))
      }),
    []
  )

  // A file the user removed is offered again once they switch to another file.
  useEffect(() => setIncludeContext(true), [state.editorContext?.path])

  const submit = (parts: PromptPart[]) => {
    send({ type: 'prompt', parts, includeContext: context !== null })
    if (state.sessionId) drafts.save(state.sessionId, undefined)
  }

  return (
    <div className="@container rounded-xl border bg-input/40 focus-within:border-ring">
      {context && (
        <div className="px-3 pt-2">
          <FilePill path={context.path} range={context.range} label={context.label} onRemove={() => setIncludeContext(false)} />
        </div>
      )}
      <PromptEditor
        ref={editor}
        placeholder={group?.placeholder ?? (busy ? 'Queue a follow-up…' : `Ask ${state.provider?.label ?? 'the agent'}… @ for files, / for commands`)}
        agents={group?.agents}
        commands={commands}
        onSubmit={submit}
        onEmptyChange={setEmpty}
        history={history}
        onChange={(doc) => state.sessionId && drafts.save(state.sessionId, isEmptyDoc(doc) ? undefined : doc)}
      />
      <div className="flex items-center gap-1 px-2 pb-2">
        <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-hidden">
          <AttachMenu editor={editor} />
          <ModelPicker fact={state.facts.model?.kind === 'model' ? state.facts.model : undefined} />
          <Options state={state} />
        </div>
        <ContextMeter
          fact={state.facts.context?.kind === 'context' ? state.facts.context : undefined}
          canCompact={state.provider?.capabilities.includes('compact') ?? false}
        />
        {busy && !(group && !empty) ? (
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
