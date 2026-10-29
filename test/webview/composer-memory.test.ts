import { describe, expect, it } from 'vitest'
import type { PromptPart } from '../../src/core/types'
import { Drafts } from '../../webview/app/composer/drafts'
import { History } from '../../webview/app/composer/history'

const p = (text: string): PromptPart[] => [{ type: 'text', text }]

describe('History', () => {
  it('walks back from the newest prompt and forward to empty', () => {
    const history = new History([p('one'), p('two'), p('three')])
    expect(history.up()).toEqual(p('three'))
    expect(history.up()).toEqual(p('two'))
    expect(history.up()).toEqual(p('one'))
    expect(history.up()).toEqual(p('one'))
    expect(history.down()).toEqual(p('two'))
    expect(history.down()).toEqual(p('three'))
    expect(history.down()).toEqual([])
    expect(history.down()).toBeUndefined()
  })

  it('has nothing to show without prompts', () => {
    expect(new History([]).up()).toBeUndefined()
  })
})

describe('Drafts', () => {
  it('keeps a draft per chat in the given store and forgets empty ones', () => {
    let saved: unknown = { sessionId: 's1' }
    const store = { get: () => saved, set: (value: unknown) => (saved = value) }
    const drafts = new Drafts(store)
    drafts.save('s1', { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'hi' }] }] })
    expect(new Drafts(store).load('s1')).toEqual({ type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'hi' }] }] })
    expect(saved).toMatchObject({ sessionId: 's1' })
    drafts.save('s1', undefined)
    expect(drafts.load('s1')).toBeUndefined()
  })
})
