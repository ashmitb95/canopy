import type { SDKMessage } from '@anthropic-ai/claude-agent-sdk'
import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import { ClaudeTranslator } from '../../src/providers/claude/translate'

const sdk = (message: object): SDKMessage => ({ uuid: 'u', session_id: 's', ...message }) as unknown as SDKMessage
const stream = (event: object, parent: string | null = null) =>
  sdk({ type: 'stream_event', event, parent_tool_use_id: parent })
const assistant = (content: object[], parent: string | null = null) =>
  sdk({ type: 'assistant', message: { id: 'msg_x', role: 'assistant', content }, parent_tool_use_id: parent })
const toolResult = (id: string, content: unknown, isError = false) =>
  sdk({
    type: 'user',
    message: { role: 'user', content: [{ type: 'tool_result', tool_use_id: id, content, is_error: isError }] },
    parent_tool_use_id: null
  })

function run(messages: SDKMessage[], setup?: (translator: ClaudeTranslator) => void) {
  const items: SessionItem[] = []
  const translator = new ClaudeTranslator((item) => items.push(item))
  setup?.(translator)
  for (const message of messages) translator.feed(message)
  const latest = new Map<string, SessionItem>()
  for (const item of items) latest.set(item.id, item)
  return { items, final: [...latest.values()] }
}

describe('ClaudeTranslator', () => {
  it('streams assistant text into one upserted message', () => {
    const { items, final } = run([
      stream({ type: 'message_start', message: { id: 'msg_1' } }),
      stream({ type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } }),
      stream({ type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: 'Hello' } }),
      stream({ type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: ' world' } }),
      stream({ type: 'content_block_stop', index: 0 })
    ])
    expect(items[2]).toEqual({ kind: 'message', id: 'msg_1:0', role: 'assistant', text: 'Hello world', streaming: true })
    expect(final).toEqual([{ kind: 'message', id: 'msg_1:0', role: 'assistant', text: 'Hello world', streaming: false }])
  })

  it('streams thinking into a thought', () => {
    const { final } = run([
      stream({ type: 'message_start', message: { id: 'msg_1' } }),
      stream({ type: 'content_block_start', index: 0, content_block: { type: 'thinking', thinking: '' } }),
      stream({ type: 'content_block_delta', index: 0, delta: { type: 'thinking_delta', thinking: 'Let me look' } }),
      stream({ type: 'content_block_stop', index: 0 })
    ])
    expect(final).toEqual([{ kind: 'thought', id: 'msg_1:0', text: 'Let me look', streaming: false }])
  })

  it('ignores subagent text', () => {
    const { items } = run([
      stream({ type: 'message_start', message: { id: 'msg_sub' } }, 'toolu_task'),
      stream({ type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } }, 'toolu_task'),
      stream({ type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: 'x' } }, 'toolu_task')
    ])
    expect(items).toEqual([])
  })

  it('turns an Edit into a running tool and a diff, then completes it', () => {
    const input = { file_path: '/w/notes.md', old_string: 'hello', new_string: 'goodbye' }
    const { final } = run([
      assistant([{ type: 'tool_use', id: 'toolu_1', name: 'Edit', input }]),
      toolResult('toolu_1', 'The file was updated.')
    ])
    expect(final).toEqual([
      {
        kind: 'tool',
        id: 'toolu_1',
        title: 'Edit /w/notes.md',
        toolKind: 'edit',
        status: 'done',
        input,
        output: 'The file was updated.',
        paths: ['/w/notes.md'],
        parentId: undefined
      },
      { kind: 'diff', id: 'toolu_1:diff', path: '/w/notes.md', oldText: 'hello', newText: 'goodbye', parentId: undefined }
    ])
  })

  it('shows a Write as a diff from nothing', () => {
    const { final } = run([
      assistant([{ type: 'tool_use', id: 'toolu_2', name: 'Write', input: { file_path: '/w/new.md', content: 'hi' } }])
    ])
    expect(final[1]).toEqual({ kind: 'diff', id: 'toolu_2:diff', path: '/w/new.md', oldText: null, newText: 'hi', parentId: undefined })
  })

  it('marks failed tools and joins block results', () => {
    const { final } = run([
      assistant([{ type: 'tool_use', id: 'toolu_3', name: 'Bash', input: { command: 'false' } }]),
      toolResult('toolu_3', [{ type: 'text', text: 'exit 1' }, { type: 'image' }], true)
    ])
    expect(final[0]).toMatchObject({ status: 'failed', output: 'exit 1\n[image]' })
  })

  it('links subagent tools to their parent', () => {
    const { final } = run([
      assistant([{ type: 'tool_use', id: 'toolu_4', name: 'Read', input: { file_path: '/w/a' } }], 'toolu_task')
    ])
    expect(final[0]).toMatchObject({ id: 'toolu_4', parentId: 'toolu_task' })
  })

  it('turns TodoWrite into the session plan', () => {
    const todos = [
      { content: 'Read code', status: 'completed' },
      { content: 'Fix bug', status: 'in_progress' },
      { content: 'Test', status: 'pending' }
    ]
    const { final } = run([assistant([{ type: 'tool_use', id: 'toolu_5', name: 'TodoWrite', input: { todos } }])])
    expect(final[1]).toEqual({
      kind: 'plan',
      id: 'plan',
      entries: [
        { text: 'Read code', status: 'done' },
        { text: 'Fix bug', status: 'in_progress' },
        { text: 'Test', status: 'pending' }
      ]
    })
  })

  it('opens and closes a turn', () => {
    const { final } = run(
      [sdk({ type: 'result', subtype: 'success', is_error: false, duration_ms: 1200, result: 'ok' })],
      (translator) => translator.startTurn()
    )
    expect(final).toHaveLength(1)
    expect(final[0]).toMatchObject({ kind: 'turn', state: 'ended', stopReason: 'success', durationMs: 1200 })
  })

  it('reports a failed turn', () => {
    const { final } = run(
      [sdk({ type: 'result', subtype: 'success', is_error: true, duration_ms: 5, result: 'API Error: overloaded' })],
      (translator) => translator.startTurn()
    )
    expect(final[1]).toMatchObject({ kind: 'notice', level: 'error', text: 'API Error: overloaded' })
  })

  it('does not report an interrupted turn as an error', () => {
    const { final } = run(
      [sdk({ type: 'result', subtype: 'error_during_execution', is_error: true, duration_ms: 5 })],
      (translator) => {
        translator.startTurn()
        translator.interrupted()
      }
    )
    expect(final).toHaveLength(1)
    expect(final[0]).toMatchObject({ kind: 'turn', state: 'ended', stopReason: 'interrupted' })
  })
})
