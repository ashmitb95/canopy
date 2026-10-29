import { describe, expect, it } from 'vitest'
import type { ApprovalItem, SessionItem } from '../../src/core/types'
import { PromptHolder } from '../../src/providers/prompt-holder'

const approval: ApprovalItem = { kind: 'approval', id: 'a1', title: 'Allow?', options: [{ id: 'allow', label: 'Allow' }] }

describe('PromptHolder', () => {
  it('shows a prompt, settles it once, and shows how it was resolved', async () => {
    const emitted: SessionItem[] = []
    const holder = new PromptHolder((item) => emitted.push(item))
    const result = holder.hold(approval, (response) => ({
      resolved: response.kind === 'option' ? response.optionId : 'dismissed',
      result: response.kind
    }))
    holder.answer('a1', { kind: 'option', optionId: 'allow' })
    holder.answer('a1', { kind: 'dismiss' })
    await expect(result).resolves.toBe('option')
    expect(emitted).toEqual([approval, { ...approval, resolved: 'allow' }])
  })

  it('dismisses everything still pending', async () => {
    const holder = new PromptHolder(() => {})
    const first = holder.hold(approval, (response) => ({ resolved: 'x', result: response.kind }))
    const second = holder.hold({ ...approval, id: 'a2' }, (response) => ({ resolved: 'x', result: response.kind }))
    holder.dismissAll()
    await expect(Promise.all([first, second])).resolves.toEqual(['dismiss', 'dismiss'])
  })
})
