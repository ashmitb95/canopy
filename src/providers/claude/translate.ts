import { randomUUID } from 'node:crypto'
import type { SDKMessage } from '@anthropic-ai/claude-agent-sdk'
import type { AssistantMessage, PlanEntry, SessionItem, Thought, ToolItem } from '../../core/types'
import { toolKind, toolPaths, toolTitle } from './tools'

type Message<T extends SDKMessage['type']> = Extract<SDKMessage, { type: T }>

/** Claude's error when a 1M-context model is used without extra-usage credits. */
const LONG_CONTEXT = /usage credits are required for long context/i
const LONG_CONTEXT_HINT =
  'This model needs extra usage credits. Choose a model without “1M context” in the model picker, or turn on extra usage in your claude.ai settings.'

/** Tool output kept in the transcript; a Read result can be a whole file. */
const MAX_OUTPUT = 20_000

/** Turns Claude Agent SDK messages into session items. Facts are the provider's job. */
export class ClaudeTranslator {
  private messageId = ''
  private readonly streaming = new Map<number, AssistantMessage | Thought>()
  private readonly tools = new Map<string, ToolItem>()
  private turnId = ''
  private interruptRequested = false
  private promptRef: string | undefined
  private lastUuid: string | undefined

  constructor(private readonly emit: (item: SessionItem) => void) {}

  startTurn(promptRef?: string): void {
    this.turnId = `turn:${randomUUID()}`
    this.interruptRequested = false
    this.promptRef = promptRef
    this.lastUuid = undefined
    this.emit({ kind: 'turn', id: this.turnId, state: 'started', ...(promptRef ? { promptRef } : {}) })
  }

  interrupted(): void {
    this.interruptRequested = true
  }

  feed(message: SDKMessage): void {
    if ((message.type === 'assistant' || message.type === 'user') && !message.parent_tool_use_id && message.uuid) this.lastUuid = message.uuid
    switch (message.type) {
      case 'stream_event':
        return this.streamEvent(message)
      case 'assistant':
        return this.assistant(message)
      case 'user':
        return this.toolResults(message)
      case 'result':
        return this.result(message)
    }
  }

  private streamEvent(message: Message<'stream_event'>): void {
    if (message.parent_tool_use_id) return
    const event = message.event
    switch (event.type) {
      case 'message_start':
        this.messageId = event.message.id
        this.streaming.clear()
        return
      case 'content_block_start': {
        const id = `${this.messageId}:${event.index}`
        if (event.content_block.type === 'text') {
          this.stream(event.index, { kind: 'message', id, role: 'assistant', text: '', streaming: true })
        } else if (event.content_block.type === 'thinking') {
          this.stream(event.index, { kind: 'thought', id, text: '', streaming: true })
        }
        return
      }
      case 'content_block_delta': {
        const item = this.streaming.get(event.index)
        if (!item) return
        if (event.delta.type === 'text_delta' && item.kind === 'message') item.text += event.delta.text
        else if (event.delta.type === 'thinking_delta' && item.kind === 'thought') item.text += event.delta.thinking
        else return
        this.emit({ ...item })
        return
      }
      case 'content_block_stop': {
        const item = this.streaming.get(event.index)
        if (!item) return
        item.streaming = false
        this.emit({ ...item })
        return
      }
    }
  }

  private stream(index: number, item: AssistantMessage | Thought): void {
    this.streaming.set(index, item)
    this.emit({ ...item })
  }

  private assistant(message: Message<'assistant'>): void {
    const parentId = message.parent_tool_use_id ?? undefined
    for (const block of message.message.content) {
      if (block.type === 'tool_use') this.toolUse(block.id, block.name, block.input as Record<string, unknown>, parentId)
    }
  }

  private toolUse(id: string, name: string, input: Record<string, unknown>, parentId: string | undefined): void {
    const tool: ToolItem = {
      kind: 'tool',
      id,
      title: toolTitle(name, input),
      toolKind: toolKind(name),
      status: 'running',
      input,
      paths: toolPaths(input),
      parentId
    }
    this.tools.set(id, tool)
    this.emit(tool)
    const path = typeof input.file_path === 'string' ? input.file_path : undefined
    if (name === 'Edit' && path) {
      const oldText = String(input.old_string ?? '')
      this.emit({ kind: 'diff', id: `${id}:diff`, path, oldText, newText: String(input.new_string ?? ''), parentId })
    } else if (name === 'Write' && path) {
      this.emit({ kind: 'diff', id: `${id}:diff`, path, oldText: null, newText: String(input.content ?? ''), parentId })
    } else if (name === 'TodoWrite' && Array.isArray(input.todos)) {
      this.emit({ kind: 'plan', id: 'plan', entries: planEntries(input.todos) })
    }
  }

  private toolResults(message: Message<'user'>): void {
    const content = message.message.content
    if (typeof content === 'string') return
    for (const block of content) {
      if (block.type !== 'tool_result') continue
      const tool = this.tools.get(block.tool_use_id)
      if (!tool) continue
      const done: ToolItem = { ...tool, status: block.is_error ? 'failed' : 'done', output: resultText(block.content) }
      this.tools.set(tool.id, done)
      this.emit(done)
    }
  }

  private result(message: Message<'result'>): void {
    const turnId = this.turnId || `turn:${randomUUID()}`
    const stopReason = this.interruptRequested ? 'interrupted' : message.subtype
    this.emit({ kind: 'turn', id: turnId, state: 'ended',
      stopReason,
      durationMs: message.duration_ms,
      ...(this.promptRef ? { promptRef: this.promptRef } : {}),
      ...(this.lastUuid ? { ref: this.lastUuid } : {})
    })
    if (message.is_error && !this.interruptRequested) {
      const result = message.subtype === 'success' ? message.result : `The turn ended with ${message.subtype}.`
      const text = LONG_CONTEXT.test(result) ? `${result}\n${LONG_CONTEXT_HINT}` : result
      this.emit({ kind: 'notice', id: `${turnId}:error`, level: 'error', text })
    }
    this.turnId = ''
  }
}

function planEntries(todos: unknown[]): PlanEntry[] {
  return (todos as { content?: unknown; status?: unknown }[]).map((todo) => ({
    text: String(todo.content ?? ''),
    status: todo.status === 'completed' ? 'done' : todo.status === 'in_progress' ? 'in_progress' : 'pending'
  }))
}

function resultText(content: unknown): string {
  const text =
    typeof content === 'string'
      ? content
      : Array.isArray(content)
        ? (content as { type: string; text?: string }[])
            .map((part) => (part.type === 'text' ? (part.text ?? '') : `[${part.type}]`))
            .join('\n')
        : ''
  return text.slice(0, MAX_OUTPUT)
}
