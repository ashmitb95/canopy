import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import { AcpTranslator, type SessionUpdate } from '../../src/providers/acp/translate'

function translateFixture(): SessionItem[] {
  const latest = new Map<string, SessionItem>()
  const translator = new AcpTranslator((item) => latest.set(item.id, item))
  translator.startTurn()
  for (const line of readFileSync('test/fixtures/grok/edit-turn.jsonl', 'utf8').trim().split('\n')) {
    const entry = JSON.parse(line) as { update?: SessionUpdate; stopReason?: string }
    if (entry.update) translator.feed(entry.update)
    if (entry.stopReason) translator.endTurn(entry.stopReason)
  }
  return [...latest.values()]
}

describe('Grok fixture: an edit turn', () => {
  const items = translateFixture()

  it('ends the turn', () => {
    expect(items.find((item) => item.kind === 'turn')).toMatchObject({ state: 'ended', stopReason: 'end_turn' })
  })

  it('replies with finished text', () => {
    const replies = items.filter((item) => item.kind === 'message' && item.role === 'assistant')
    expect(replies.length).toBeGreaterThan(0)
    for (const reply of replies) expect(reply).toMatchObject({ streaming: false, text: expect.stringMatching(/\S/) })
  })

  it('completes its tools', () => {
    const tools = items.filter((item) => item.kind === 'tool')
    expect(tools.length).toBeGreaterThan(0)
    for (const tool of tools) expect(tool).not.toMatchObject({ status: 'running' })
  })

  it('shows the edit as a diff', () => {
    expect(items.some((item) => item.kind === 'diff' && item.newText.includes('goodbye world'))).toBe(true)
  })
})
