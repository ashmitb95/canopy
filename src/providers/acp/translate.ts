import { randomUUID } from 'node:crypto'
import type { AssistantMessage, SessionItem, Thought, ToolItem, ToolKind } from '../../core/types'

type TextBlock = { type: string; text?: string }
type ToolContent =
  | { type: 'content'; content: TextBlock }
  | { type: 'diff'; path: string; oldText?: string | null; newText: string }
  | { type: 'terminal'; terminalId: string }

type ToolFields = {
  toolCallId: string
  title?: string | null
  kind?: string | null
  status?: string | null
  rawInput?: unknown
  content?: ToolContent[] | null
  locations?: { path: string }[] | null
  _meta?: Record<string, unknown> | null
}

export type SessionUpdate =
  | { sessionUpdate: 'agent_message_chunk' | 'agent_thought_chunk'; content: TextBlock }
  | ({ sessionUpdate: 'tool_call' | 'tool_call_update' } & ToolFields)
  | { sessionUpdate: 'plan'; entries: { content: string; priority?: string; status: 'pending' | 'in_progress' | 'completed' }[] }
  | { sessionUpdate: 'available_commands_update'; availableCommands?: { name: string; description?: string | null }[] }
  | { sessionUpdate: 'session_info_update' | 'current_mode_update' | 'usage_update' }

/** Tool output kept in the transcript. */
const MAX_OUTPUT = 20_000

const KINDS: Record<string, ToolKind> = {
  read: 'read',
  edit: 'edit',
  delete: 'edit',
  move: 'edit',
  search: 'search',
  execute: 'execute',
  fetch: 'fetch'
}

const VERBS: Record<ToolKind, string> = {
  read: 'Read',
  edit: 'Edit',
  execute: 'Run',
  search: 'Search',
  fetch: 'Fetch',
  mcp: 'MCP',
  other: 'Tool'
}

const STATUS: Record<string, ToolItem['status']> = {
  pending: 'running',
  in_progress: 'running',
  completed: 'done',
  failed: 'failed'
}

/** Turns ACP `session/update` notifications into session items. Facts are the provider's job. */
export class AcpTranslator {
  private readonly items = new Map<string, SessionItem>()
  private readonly diffs = new Map<string, string[]>()
  private turnId = ''
  private chunks = 0
  private stream: AssistantMessage | Thought | undefined
  private interruptRequested = false

  constructor(private readonly emit: (item: SessionItem) => void) {}

  startTurn(): void {
    this.turnId = `turn:${randomUUID()}`
    this.chunks = 0
    this.stream = undefined
    this.interruptRequested = false
    this.upsert({ kind: 'turn', id: this.turnId, state: 'started' })
  }

  interrupted(): void {
    this.interruptRequested = true
  }

  endTurn(stopReason: string): void {
    this.closeStream()
    const reason = stopReason === 'cancelled' || this.interruptRequested ? 'interrupted' : stopReason
    this.upsert({ kind: 'turn', id: this.turnId, state: 'ended', stopReason: reason })
  }

  failTurn(message: string): void {
    this.closeStream()
    this.upsert({ kind: 'turn', id: this.turnId, state: 'ended', stopReason: 'error' })
    this.upsert({ kind: 'notice', id: `${this.turnId}:error`, level: 'error', text: message })
  }

  feed(update: SessionUpdate): void {
    switch (update.sessionUpdate) {
      case 'agent_message_chunk':
        return this.chunk('message', update.content.text ?? '')
      case 'agent_thought_chunk':
        return this.chunk('thought', update.content.text ?? '')
      case 'tool_call':
      case 'tool_call_update':
        this.closeStream()
        return this.tool(update)
      case 'plan':
        this.closeStream()
        return this.upsert({
          kind: 'plan',
          id: 'plan',
          entries: update.entries.map((entry) => ({
            text: entry.content,
            status: entry.status === 'completed' ? 'done' : entry.status
          }))
        })
    }
  }

  private chunk(kind: 'message' | 'thought', text: string): void {
    if (this.stream?.kind !== kind) {
      this.closeStream()
      const id = `${this.turnId}:m${++this.chunks}`
      this.stream =
        kind === 'message'
          ? { kind: 'message', id, role: 'assistant', text: '', streaming: true }
          : { kind: 'thought', id, text: '', streaming: true }
    }
    this.stream = { ...this.stream, text: this.stream.text + text }
    this.upsert(this.stream)
  }

  private closeStream(): void {
    if (!this.stream) return
    this.upsert({ ...this.stream, streaming: false })
    this.stream = undefined
  }

  private tool(update: ToolFields): void {
    const current = this.items.get(update.toolCallId)
    const previous = current?.kind === 'tool' ? current : undefined
    const label = toolLabel(update._meta)
    const kind = KINDS[update.kind ?? label?.kind ?? ''] ?? previous?.toolKind ?? 'other'
    const verb = label?.label ?? previous?.title.split(' ')[0] ?? VERBS[kind]
    const target = update.title?.replaceAll('`', '').trim()
    const title = target ? (target.startsWith(verb) ? target : `${verb} ${target}`) : (previous?.title ?? verb)
    const text = (update.content ?? [])
      .flatMap((block) => (block.type === 'content' && block.content.text ? [block.content.text] : []))
      .join('\n')
    const paths = update.locations?.map((location) => location.path) ?? previous?.paths
    const input = update.rawInput ?? previous?.input
    const output = text ? text.slice(0, MAX_OUTPUT) : previous?.output
    this.upsert({
      kind: 'tool',
      id: update.toolCallId,
      title,
      toolKind: kind,
      status: STATUS[update.status ?? ''] ?? previous?.status ?? 'running',
      ...(input !== undefined ? { input } : {}),
      ...(output ? { output } : {}),
      ...(paths?.length ? { paths } : {})
    })
    ;(update.content ?? []).forEach((block, index) => {
      if (block.type !== 'diff') return
      this.diffs.set(update.toolCallId, [...new Set([...(this.diffs.get(update.toolCallId) ?? []), `${update.toolCallId}:diff:${index}`])])
      this.upsert({
        kind: 'diff',
        id: `${update.toolCallId}:diff:${index}`,
        path: block.path,
        oldText: block.oldText ?? null,
        newText: block.newText
      })
    })
  }

  /** The diff items a tool call produced, so its approval can offer Review changes. */
  diffIdsFor(toolCallId: string): string[] {
    return this.diffs.get(toolCallId) ?? []
  }

  private upsert(item: SessionItem): void {
    this.items.set(item.id, item)
    this.emit(item)
  }
}

/** Grok labels its tools in `_meta['x.ai/tool']`; other agents rely on the ACP kind. */
function toolLabel(meta: Record<string, unknown> | null | undefined): { label?: string; kind?: string } | undefined {
  const tool = meta?.['x.ai/tool'] as { label?: unknown; kind?: unknown } | undefined
  if (!tool) return undefined
  return {
    label: typeof tool.label === 'string' ? tool.label : undefined,
    kind: typeof tool.kind === 'string' ? tool.kind : undefined
  }
}
