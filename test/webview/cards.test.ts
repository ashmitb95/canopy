import { describe, expect, it } from 'vitest'
import type { TimelineItem } from '../../src/group/chat'
import { placeCards } from '../../webview/app/group/cards'

const user = (agent: string, id: string, delegation?: string): TimelineItem => ({ agent, item: { kind: 'message', id, role: 'user', parts: [{ type: 'text', text: id }] }, ...(delegation ? { delegation } : {}) }) as TimelineItem
const said = (agent: string, id: string, delegation?: string): TimelineItem => ({ agent, item: { kind: 'message', id, role: 'assistant', text: id, streaming: false }, ...(delegation ? { delegation } : {}) })

describe('placeCards', () => {
  it('gives each phase only its own items, and puts each card after the message that started it', () => {
    const items = [user('claude', 'ask'), said('claude', 'plan'), user('grok', 'handoff-1', 'p1'), said('grok', 'work-1', 'p1'), user('grok', 'handoff-2', 'p2'), said('grok', 'work-2', 'p2'), user('codex', 'handoff-r', 'r'), said('codex', 'review', 'r')]
    const { own, anchors } = placeCards(items)
    expect(own.get('p1')?.map((entry) => entry.item.id)).toEqual(['work-1'])
    expect(own.get('p2')?.map((entry) => entry.item.id)).toEqual(['work-2'])
    expect([...anchors]).toEqual([[2, ['p1']], [4, ['p2']], [6, ['r']]])
  })

  it('moves a card down to the latest message that resumed it, and leaves direct chat with the agent in the conversation', () => {
    const items = [user('grok', 'handoff', 'd'), said('grok', 'asks', 'd'), said('claude', 'answers'), user('grok', 'answer', 'd'), said('grok', 'finishes', 'd'), user('grok', 'thanks'), said('grok', 'welcome')]
    const { own, anchors } = placeCards(items)
    expect(own.get('d')?.map((entry) => entry.item.id)).toEqual(['asks', 'finishes'])
    expect([...anchors]).toEqual([[3, ['d']]])
  })
})
