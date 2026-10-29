import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import { CodexTranslator } from '../../src/providers/codex/translate'

function run(frames: [method: string, params: unknown][], setup?: (translator: CodexTranslator) => void) {
  const latest = new Map<string, SessionItem>()
  const translator = new CodexTranslator((item) => latest.set(item.id, item))
  setup?.(translator)
  for (const [method, params] of frames) translator.feed(method, params)
  return [...latest.values()]
}

const turn = (status: string, error: string | null = null) => ({
  turn: { id: 'u1', status, error: error ? { message: error } : null, durationMs: 900 }
})
const started = (item: object) => ['item/started', { item }] as [string, unknown]
const completed = (item: object) => ['item/completed', { item }] as [string, unknown]

describe('CodexTranslator', () => {
  it('opens and closes turns', () => {
    expect(run([['turn/started', turn('inProgress')], ['turn/completed', turn('completed')]])).toEqual([
      { kind: 'turn', id: 'turn:u1', state: 'ended', stopReason: 'completed', durationMs: 900 }
    ])
  })

  it('reports a failed turn', () => {
    const items = run([['turn/completed', turn('failed', 'Rate limit reached')]])
    expect(items[1]).toMatchObject({ kind: 'notice', level: 'error', text: 'Rate limit reached' })
  })

  it('marks an interrupted turn', () => {
    const items = run([['turn/completed', turn('interrupted')]])
    expect(items).toEqual([{ kind: 'turn', id: 'turn:u1', state: 'ended', stopReason: 'interrupted', durationMs: 900 }])
  })

  it('streams agent messages', () => {
    const items = run([
      started({ type: 'agentMessage', id: 'm1', text: '' }),
      ['item/agentMessage/delta', { itemId: 'm1', delta: 'Hel' }],
      ['item/agentMessage/delta', { itemId: 'm1', delta: 'lo' }]
    ])
    expect(items).toEqual([{ kind: 'message', id: 'm1', role: 'assistant', text: 'Hello', streaming: true }])
    const done = run([started({ type: 'agentMessage', id: 'm1', text: '' }), completed({ type: 'agentMessage', id: 'm1', text: 'Hello.' })])
    expect(done).toEqual([{ kind: 'message', id: 'm1', role: 'assistant', text: 'Hello.', streaming: false }])
  })

  it('shows reasoning only when it has text', () => {
    expect(run([started({ type: 'reasoning', id: 'r1', summary: [] }), completed({ type: 'reasoning', id: 'r1', summary: [] })])).toEqual([])
    const items = run([
      started({ type: 'reasoning', id: 'r2', summary: [] }),
      ['item/reasoning/summaryTextDelta', { itemId: 'r2', delta: 'Checking the test' }],
      completed({ type: 'reasoning', id: 'r2', summary: ['Checking the test'] })
    ])
    expect(items).toEqual([{ kind: 'thought', id: 'r2', text: 'Checking the test', streaming: false }])
  })

  it('turns command executions into tools', () => {
    const command = {
      type: 'commandExecution',
      id: 'c1',
      command: `/bin/zsh -lc "grep -n -F 'hello' notes.md"`,
      commandActions: [{ type: 'search', command: `grep -n -F 'hello' notes.md` }],
      aggregatedOutput: null,
      status: 'inProgress'
    }
    const items = run([
      started(command),
      ['item/commandExecution/outputDelta', { itemId: 'c1', delta: '1:hello\n' }],
      completed({ ...command, status: 'completed', aggregatedOutput: '1:hello\n' })
    ])
    expect(items).toEqual([
      {
        kind: 'tool',
        id: 'c1',
        title: `Run grep -n -F 'hello' notes.md`,
        toolKind: 'search',
        status: 'done',
        input: { command: `grep -n -F 'hello' notes.md` },
        output: '1:hello\n'
      }
    ])
  })

  it('marks declined and failed commands as failed', () => {
    const items = run([
      completed({ type: 'commandExecution', id: 'c2', command: 'rm -rf x', commandActions: [], aggregatedOutput: null, status: 'declined' })
    ])
    expect(items[0]).toMatchObject({ status: 'failed', toolKind: 'execute' })
  })

  it('turns file changes into an edit tool and diffs', () => {
    const items = run([
      completed({
        type: 'fileChange',
        id: 'f1',
        status: 'completed',
        changes: [
          { path: '/w/notes.md', kind: { type: 'update', move_path: null }, diff: '@@ -1 +1 @@\n-hello world\n+goodbye world' },
          { path: '/w/new.md', kind: { type: 'add' }, diff: 'fresh file' }
        ]
      })
    ])
    expect(items).toEqual([
      { kind: 'tool', id: 'f1', title: 'Edit notes.md, new.md', toolKind: 'edit', status: 'done', paths: ['/w/notes.md', '/w/new.md'] },
      { kind: 'diff', id: 'f1:0', path: '/w/notes.md', oldText: 'hello world', newText: 'goodbye world' },
      { kind: 'diff', id: 'f1:1', path: '/w/new.md', oldText: null, newText: 'fresh file' }
    ])
  })

  it('turns MCP calls into tools', () => {
    const items = run([
      completed({
        type: 'mcpToolCall',
        id: 'x1',
        server: 'linear',
        tool: 'list_issues',
        status: 'completed',
        arguments: { team: 'core' },
        result: { content: [{ type: 'text', text: '3 issues' }] },
        error: null
      })
    ])
    expect(items).toEqual([
      { kind: 'tool', id: 'x1', title: 'linear · list_issues', toolKind: 'mcp', status: 'done', input: { team: 'core' }, output: '3 issues' }
    ])
  })

  it('keeps the plan as one item', () => {
    const items = run([
      ['turn/plan/updated', { plan: [{ step: 'Read', status: 'completed' }, { step: 'Fix', status: 'inProgress' }] }],
      ['turn/plan/updated', { plan: [{ step: 'Read', status: 'completed' }, { step: 'Fix', status: 'completed' }] }]
    ])
    expect(items).toEqual([
      {
        kind: 'plan',
        id: 'plan',
        entries: [
          { text: 'Read', status: 'done' },
          { text: 'Fix', status: 'done' }
        ]
      }
    ])
  })

  it('ignores items and notifications it does not show', () => {
    expect(
      run([
        started({ type: 'userMessage', id: 'u', content: [] }),
        ['turn/moderationMetadata', {}],
        ['account/rateLimits/updated', {}]
      ])
    ).toEqual([])
  })

  it('remembers which diff items a file change produced', () => {
    const translator = new CodexTranslator(() => {})
    translator.feed('item/started', {
      item: {
        type: 'fileChange',
        id: 'f9',
        status: 'inProgress',
        changes: [
          { path: '/w/a.ts', kind: { type: 'update', move_path: null }, diff: '@@ -1 +1 @@\n-a\n+b' },
          { path: '/w/b.ts', kind: { type: 'add' }, diff: 'new' }
        ]
      }
    })
    expect(translator.diffIdsFor('f9')).toEqual(['f9:0', 'f9:1'])
    expect(translator.diffIdsFor('missing')).toEqual([])
  })
})
