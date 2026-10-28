import { basename } from 'node:path'
import type { SessionItem, ToolItem, ToolKind } from '../../core/types'
import type { CommandAction, PlanStep, ThreadItem, Turn } from './protocol'
import { splitDiff, unwrapShell } from './text'

/** Tool output kept in the transcript. */
const MAX_OUTPUT = 20_000

const STATUS: Record<string, ToolItem['status']> = {
  inProgress: 'running',
  completed: 'done',
  failed: 'failed',
  declined: 'failed'
}

/** Turns app-server notifications into session items. Facts are the provider's job. */
export class CodexTranslator {
  private readonly items = new Map<string, SessionItem>()
  private readonly types = new Map<string, string>()
  private interruptRequested = false

  constructor(private readonly emit: (item: SessionItem) => void) {}

  interrupted(): void {
    this.interruptRequested = true
  }

  feed(method: string, params: unknown): void {
    switch (method) {
      case 'turn/started': {
        const { turn } = params as { turn: Turn }
        this.interruptRequested = false
        return this.upsert({ kind: 'turn', id: `turn:${turn.id}`, state: 'started' })
      }
      case 'turn/completed':
        return this.turnCompleted((params as { turn: Turn }).turn)
      case 'item/started':
        return this.item((params as { item: ThreadItem }).item, false)
      case 'item/completed':
        return this.item((params as { item: ThreadItem }).item, true)
      case 'item/agentMessage/delta':
      case 'item/reasoning/summaryTextDelta':
      case 'item/commandExecution/outputDelta':
        return this.delta(params as { itemId: string; delta: string })
      case 'turn/plan/updated':
        return this.plan((params as { plan: PlanStep[] }).plan)
    }
  }

  private turnCompleted(turn: Turn): void {
    const id = `turn:${turn.id}`
    const interrupted = turn.status === 'interrupted' || this.interruptRequested
    this.upsert({
      kind: 'turn',
      id,
      state: 'ended',
      stopReason: interrupted ? 'interrupted' : turn.status,
      durationMs: turn.durationMs ?? undefined
    })
    if (turn.status === 'failed' && !interrupted) {
      this.upsert({ kind: 'notice', id: `${id}:error`, level: 'error', text: turn.error?.message ?? 'The turn failed.' })
    }
  }

  private item(item: ThreadItem, completed: boolean): void {
    this.types.set(item.id, item.type)
    switch (item.type) {
      case 'agentMessage':
        return this.upsert({ kind: 'message', id: item.id, role: 'assistant', text: item.text, streaming: !completed })
      case 'reasoning': {
        const current = this.items.get(item.id)
        const text = item.summary.join('\n\n') || (current?.kind === 'thought' ? current.text : '')
        if (text) this.upsert({ kind: 'thought', id: item.id, text, streaming: !completed })
        return
      }
      case 'commandExecution': {
        const command = unwrapShell(item.command)
        const current = this.items.get(item.id)
        const output = item.aggregatedOutput ?? (current?.kind === 'tool' ? current.output : undefined)
        return this.upsert({
          kind: 'tool',
          id: item.id,
          title: `Run ${command}`,
          toolKind: commandKind(item.commandActions),
          status: STATUS[item.status],
          input: { command },
          ...(output ? { output: output.slice(0, MAX_OUTPUT) } : {})
        })
      }
      case 'fileChange':
        this.upsert({
          kind: 'tool',
          id: item.id,
          title: `Edit ${item.changes.map((change) => basename(change.path)).join(', ')}`,
          toolKind: 'edit',
          status: STATUS[item.status],
          paths: item.changes.map((change) => change.path)
        })
        item.changes.forEach((change, index) => {
          const { oldText, newText } = splitDiff(change.diff)
          this.upsert({
            kind: 'diff',
            id: `${item.id}:${index}`,
            path: change.path,
            oldText: change.kind.type === 'add' ? null : oldText,
            newText
          })
        })
        return
      case 'mcpToolCall':
        return this.upsert({
          kind: 'tool',
          id: item.id,
          title: `${item.server} · ${item.tool}`,
          toolKind: 'mcp',
          status: STATUS[item.status],
          input: item.arguments,
          ...(completed ? { output: (item.error?.message ?? mcpText(item.result)).slice(0, MAX_OUTPUT) } : {})
        })
    }
  }

  private delta({ itemId, delta }: { itemId: string; delta: string }): void {
    const current = this.items.get(itemId)
    if (current?.kind === 'message' && current.role === 'assistant') this.upsert({ ...current, text: current.text + delta })
    else if (current?.kind === 'thought') this.upsert({ ...current, text: current.text + delta })
    else if (current?.kind === 'tool') this.upsert({ ...current, output: `${current.output ?? ''}${delta}`.slice(0, MAX_OUTPUT) })
    else if (!current && this.types.get(itemId) === 'reasoning') {
      this.upsert({ kind: 'thought', id: itemId, text: delta, streaming: true })
    }
  }

  private plan(steps: PlanStep[]): void {
    this.upsert({
      kind: 'plan',
      id: 'plan',
      entries: steps.map((step) => ({
        text: step.step,
        status: step.status === 'completed' ? 'done' : step.status === 'inProgress' ? 'in_progress' : 'pending'
      }))
    })
  }

  private upsert(item: SessionItem): void {
    this.items.set(item.id, item)
    this.emit(item)
  }
}

function commandKind(actions: CommandAction[]): ToolKind {
  if (actions.length > 0 && actions.every((action) => action.type === 'read')) return 'read'
  if (actions.some((action) => action.type === 'search' || action.type === 'listFiles')) return 'search'
  return 'execute'
}

function mcpText(result: { content: unknown[] } | null): string {
  if (!result) return ''
  return result.content
    .map((part) => {
      const block = part as { type?: string; text?: string }
      return block.type === 'text' ? (block.text ?? '') : JSON.stringify(part)
    })
    .join('\n')
}
