import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import { CodexTranslator } from '../../src/providers/codex/translate'

function translateFixture(): SessionItem[] {
  const latest = new Map<string, SessionItem>()
  const translator = new CodexTranslator((item) => latest.set(item.id, item))
  for (const line of readFileSync('test/fixtures/codex/edit-turn.jsonl', 'utf8').trim().split('\n')) {
    const { method, params } = JSON.parse(line) as { method: string; params: unknown }
    translator.feed(method, params)
  }
  return [...latest.values()]
}

describe('Codex fixture: an edit turn', () => {
  const items = translateFixture()

  it('ends the turn successfully', () => {
    expect(items.find((item) => item.kind === 'turn')).toMatchObject({ state: 'ended', stopReason: 'completed' })
  })

  it('replies with finished text', () => {
    const replies = items.filter((item) => item.kind === 'message' && item.role === 'assistant')
    expect(replies.length).toBeGreaterThan(0)
    for (const reply of replies) expect(reply).toMatchObject({ streaming: false, text: expect.stringMatching(/\S/) })
  })

  it('leaves no tool running', () => {
    const tools = items.filter((item) => item.kind === 'tool')
    expect(tools.length).toBeGreaterThan(0)
    for (const tool of tools) expect(tool).not.toMatchObject({ status: 'running' })
  })

  it('records the edit as a file change or a command', () => {
    const edited = items.some(
      (item) =>
        (item.kind === 'diff' && item.newText.includes('goodbye world')) ||
        (item.kind === 'tool' && item.title.includes('goodbye world'))
    )
    expect(edited).toBe(true)
  })
})
