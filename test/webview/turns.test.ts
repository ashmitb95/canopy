import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import { turnFooters } from '../../webview/app/turns'

const user = (id: string): SessionItem => ({ kind: 'message', id, role: 'user', parts: [{ type: 'text', text: id }] })
const reply = (id: string, text: string): SessionItem => ({ kind: 'message', id, role: 'assistant', text, streaming: false })

describe('turnFooters', () => {
  it('puts a footer after the last item of each ended turn', () => {
    const items: SessionItem[] = [
      user('u1'),
      { kind: 'turn', id: 't1', state: 'ended', at: '2026-10-29T10:00:00.000Z' },
      reply('a1', 'first'),
      { kind: 'diff', id: 'd1', path: '/w/a.ts', oldText: 'x\ny', newText: 'x\ny\nz' },
      { kind: 'diff', id: 'd2', path: '/w/a.ts', oldText: null, newText: 'one' },
      reply('a2', 'done'),
      user('u2'),
      { kind: 'turn', id: 't2', state: 'started' },
      reply('a3', 'working')
    ]
    const footers = turnFooters(items)
    expect([...footers.keys()]).toEqual(['a2'])
    expect(footers.get('a2')).toMatchObject({
      at: '2026-10-29T10:00:00.000Z',
      prompt: { id: 'u1' },
      reply: { id: 'a2', text: 'done' },
      files: 1,
      added: 4,
      removed: 2
    })
    expect(footers.get('a2')?.diffs.map((diff) => diff.id)).toEqual(['d1', 'd2'])
  })

  it('gives no footer to a turn without a turn item', () => {
    expect(turnFooters([user('u1'), reply('a1', 'x')]).size).toBe(0)
  })
})
