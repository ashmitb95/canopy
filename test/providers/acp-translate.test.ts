import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import { AcpTranslator, type SessionUpdate } from '../../src/providers/acp/translate'

function run(updates: SessionUpdate[], end?: (translator: AcpTranslator) => void) {
  const latest = new Map<string, SessionItem>()
  const translator = new AcpTranslator((item) => latest.set(item.id, item))
  translator.startTurn()
  for (const update of updates) translator.feed(update)
  end?.(translator)
  return [...latest.values()].filter((item) => item.kind !== 'turn')
}

const text = (sessionUpdate: 'agent_message_chunk' | 'agent_thought_chunk', value: string): SessionUpdate => ({
  sessionUpdate,
  content: { type: 'text', text: value }
})
const grokTool = (name: string, kind: string, label: string) => ({ 'x.ai/tool': { name, kind, label } })

describe('AcpTranslator', () => {
  it('joins consecutive chunks into one message and one thought', () => {
    const items = run(
      [text('agent_thought_chunk', 'The '), text('agent_thought_chunk', 'file'), text('agent_message_chunk', 'Re'), text('agent_message_chunk', 'placed.')],
      (translator) => translator.endTurn('end_turn')
    )
    expect(items).toEqual([
      expect.objectContaining({ kind: 'thought', text: 'The file', streaming: false }),
      expect.objectContaining({ kind: 'message', role: 'assistant', text: 'Replaced.', streaming: false })
    ])
  })

  it('starts a new message after a tool call', () => {
    const items = run([
      text('agent_message_chunk', 'Looking.'),
      { sessionUpdate: 'tool_call', toolCallId: 't1', title: 'grep', rawInput: { pattern: 'x' }, _meta: grokTool('grep', 'search', 'Search') },
      text('agent_message_chunk', 'Done.')
    ])
    expect(items.filter((item) => item.kind === 'message').map((item) => item.kind === 'message' && item.role === 'assistant' && item.text)).toEqual([
      'Looking.',
      'Done.'
    ])
  })

  it('builds tool titles from the label and the target', () => {
    const items = run([
      { sessionUpdate: 'tool_call', toolCallId: 't1', title: 'grep', rawInput: { pattern: 'hello' }, _meta: grokTool('grep', 'search', 'Search') },
      { sessionUpdate: 'tool_call_update', toolCallId: 't1', kind: 'search', title: 'hello world' },
      {
        sessionUpdate: 'tool_call_update',
        toolCallId: 't1',
        status: 'completed',
        content: [{ type: 'content', content: { type: 'text', text: 'found 1 matches' } }]
      }
    ])
    expect(items).toEqual([
      {
        kind: 'tool',
        id: 't1',
        title: 'Search hello world',
        toolKind: 'search',
        status: 'done',
        input: { pattern: 'hello' },
        output: 'found 1 matches'
      }
    ])
  })

  it('turns diff content into diff items and keeps edit titles readable', () => {
    const items = run([
      { sessionUpdate: 'tool_call', toolCallId: 't2', title: 'search_replace', _meta: grokTool('search_replace', 'edit', 'Edit') },
      {
        sessionUpdate: 'tool_call_update',
        toolCallId: 't2',
        kind: 'edit',
        title: 'Edit `/w/notes.md`',
        status: 'completed',
        locations: [{ path: '/w/notes.md' }],
        content: [{ type: 'diff', path: '/w/notes.md', oldText: 'hello world', newText: 'goodbye world' }]
      }
    ])
    expect(items).toEqual([
      expect.objectContaining({ kind: 'tool', id: 't2', title: 'Edit /w/notes.md', toolKind: 'edit', status: 'done', paths: ['/w/notes.md'] }),
      { kind: 'diff', id: 't2:diff:0', path: '/w/notes.md', oldText: 'hello world', newText: 'goodbye world' }
    ])
  })

  it('marks failed tools', () => {
    const items = run([
      { sessionUpdate: 'tool_call', toolCallId: 't3', title: 'Run tests', kind: 'execute', status: 'in_progress' },
      { sessionUpdate: 'tool_call_update', toolCallId: 't3', status: 'failed' }
    ])
    expect(items[0]).toMatchObject({ title: 'Run tests', toolKind: 'execute', status: 'failed' })
  })

  it('keeps the plan as one item', () => {
    const items = run([
      { sessionUpdate: 'plan', entries: [{ content: 'Read', priority: 'medium', status: 'completed' }, { content: 'Fix', priority: 'high', status: 'in_progress' }] }
    ])
    expect(items).toEqual([
      {
        kind: 'plan',
        id: 'plan',
        entries: [
          { text: 'Read', status: 'done' },
          { text: 'Fix', status: 'in_progress' }
        ]
      }
    ])
  })

  it('ends turns from the prompt result', () => {
    const latest = new Map<string, SessionItem>()
    const translator = new AcpTranslator((item) => latest.set(item.id, item))
    translator.startTurn()
    translator.endTurn('cancelled')
    expect([...latest.values()]).toEqual([expect.objectContaining({ kind: 'turn', state: 'ended', stopReason: 'interrupted' })])
    translator.startTurn()
    translator.failTurn('Rate limited')
    expect([...latest.values()].at(-1)).toMatchObject({ kind: 'notice', level: 'error', text: 'Rate limited' })
  })

  it('ignores updates it does not show', () => {
    expect(run([{ sessionUpdate: 'available_commands_update' }, { sessionUpdate: 'session_info_update' }])).toEqual([])
  })
})
