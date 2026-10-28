import { readFileSync } from 'node:fs'
import type { SDKMessage } from '@anthropic-ai/claude-agent-sdk'
import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../../src/core/types'
import { ClaudeTranslator } from '../../src/providers/claude/translate'

function translateFixture(): SessionItem[] {
  const messages = readFileSync('test/fixtures/claude/edit-turn.jsonl', 'utf8')
    .trim()
    .split('\n')
    .map((line) => JSON.parse(line) as SDKMessage)
  const latest = new Map<string, SessionItem>()
  const translator = new ClaudeTranslator((item) => latest.set(item.id, item))
  translator.startTurn()
  for (const message of messages) translator.feed(message)
  return [...latest.values()]
}

describe('Claude fixture: an edit turn', () => {
  const items = translateFixture()

  it('completes an edit tool call', () => {
    expect(items.some((item) => item.kind === 'tool' && item.toolKind === 'edit' && item.status === 'done')).toBe(true)
  })

  it('shows the edit as a diff of notes.md', () => {
    const diff = items.find((item) => item.kind === 'diff')
    expect(diff).toMatchObject({ kind: 'diff', newText: expect.stringContaining('goodbye world') })
    expect(diff?.kind === 'diff' && diff.path.endsWith('notes.md')).toBe(true)
  })

  it('replies with finished text', () => {
    const replies = items.filter((item) => item.kind === 'message' && item.role === 'assistant')
    expect(replies.length).toBeGreaterThan(0)
    for (const reply of replies) expect(reply).toMatchObject({ streaming: false, text: expect.stringMatching(/\S/) })
  })

  it('ends the turn successfully', () => {
    // Started and ended share an id, so the folded turn item sits where the turn began.
    expect(items.find((item) => item.kind === 'turn')).toMatchObject({ kind: 'turn', state: 'ended', stopReason: 'success' })
  })
})
