import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import { frameAt, plain, rollingLines, toolLine } from '../../src/group/rolling'

const message = (text: string, streaming = false): SessionItem => ({ kind: 'message', id: 'm', role: 'assistant', text, streaming })

describe('rolling view', () => {
  it('shortens tools across providers', () => {
    expect(toolLine('Bash ls -la')).toBe('$ ls -la')
    expect(toolLine('Run node check.test.mjs')).toBe('$ node check.test.mjs')
    expect(toolLine('Command Execute node a.mjs')).toBe('$ node a.mjs')
    expect(toolLine('list files list .')).toBe('list .')
    expect(toolLine('Read ./c.ts')).toBe('read c.ts')
    expect(toolLine('Edit c.ts, ./check.test.mjs')).toBe('edit c.ts, check.test.mjs')
  })

  it('keeps one line per item as snapshots stream in, in first-seen order', () => {
    const lines = rollingLines([message('I will', true), { kind: 'tool', id: 't', title: 'Read ./a.ts', toolKind: 'read', status: 'running' }, message('I will read it', false), { kind: 'tool', id: 't', title: 'Read ./a.ts', toolKind: 'read', status: 'done', output: 'x' }])
    expect(lines.map((line) => line.text)).toEqual(['I will read it', 'read a.ts'])
    expect(lines[1].live).toBe(false)
  })

  it('shows the tail of command output only, and skips file contents', () => {
    const lines = rollingLines([
      { kind: 'tool', id: 'r', title: 'Read ./a.ts', toolKind: 'read', status: 'done', output: 'secret file contents' },
      { kind: 'tool', id: 'b', title: 'Bash pnpm test', toolKind: 'execute', status: 'done', output: 'one\ntwo\nthree\n' }
    ])
    expect(lines.map((line) => line.text)).toEqual(['read a.ts', '$ pnpm test', 'two', 'three'])
  })

  it('adds a diff count to an edit, and drops empty thinking', () => {
    const lines = rollingLines([
      { kind: 'thought', id: 'th', text: '', streaming: false },
      { kind: 'tool', id: 'e', title: 'Edit ./c.ts', toolKind: 'edit', status: 'done', paths: ['./c.ts'] },
      { kind: 'diff', id: 'd', path: './c.ts', oldText: 'a\nb\n', newText: 'a\nc\nd\n' }
    ])
    expect(lines).toHaveLength(1)
    expect(lines[0].stat).toBe('+2 −1')
  })

  it('strips markup from prose, and counts diffs only on edits', () => {
    expect(plain('- **`c.ts`:** see [c.ts](./c.ts)')).toBe('c.ts: see c.ts')
    const lines = rollingLines([
      { kind: 'tool', id: 'r', title: 'Read ./c.ts', toolKind: 'read', status: 'done', paths: ['./c.ts'] },
      { kind: 'diff', id: 'd', path: './c.ts', oldText: 'a', newText: 'b' }
    ])
    expect(lines[0].stat).toBeUndefined()
  })

  it('replays a stream by time', () => {
    const events = [{ t: 0, item: message('Hello', true) }, { t: 100, item: message('Hello there', false) }]
    expect(frameAt(events, 50)[0]).toMatchObject({ text: 'Hello', live: true })
    expect(frameAt(events, 150)[0]).toMatchObject({ text: 'Hello there', live: false })
  })

  it('shows an answered approval as one line with the choice', () => {
    const lines = rollingLines([{ kind: 'approval', id: 'a', title: 'Allow Grok to run this command?', options: [{ id: 'always', label: 'Always allow' }], resolved: 'always' }])
    expect(lines.map((line) => line.text)).toEqual(['Allow Grok to run this command? · Always allow'])
  })
})
