import { describe, expect, it } from 'vitest'
import type { SessionItem, ToolItem } from '../../src/core/types'
import { nestItems, renderUnits } from '../../webview/app/units'

const tool = (id: string, toolKind: ToolItem['toolKind'], parentId?: string): ToolItem => ({
  kind: 'tool',
  id,
  title: `${toolKind} ${id}`,
  toolKind,
  status: 'done',
  ...(parentId ? { parentId } : {})
})
const say = (id: string): SessionItem => ({ kind: 'message', id, role: 'assistant', text: id, streaming: false })

describe('nestItems', () => {
  it('moves items with a known parent under it, keeping orphans on top', () => {
    const items = [tool('task', 'other'), tool('r1', 'read', 'task'), say('m1'), tool('r2', 'read', 'gone')]
    const { top, children } = nestItems(items)
    expect(top.map((item) => item.id)).toEqual(['task', 'm1', 'r2'])
    expect(children.get('task')?.map((item) => item.id)).toEqual(['r1'])
  })
})

describe('renderUnits', () => {
  it('folds two or more reads and searches in a row into one explored unit', () => {
    const units = renderUnits([say('a'), tool('r1', 'read'), tool('s1', 'search'), tool('f1', 'fetch'), say('b'), tool('r2', 'read'), tool('e1', 'execute')])
    expect(units.map((unit) => (unit.type === 'item' ? unit.item.id : `explored:${unit.items.map((item) => item.id).join(',')}`))).toEqual([
      'a',
      'explored:r1,s1,f1',
      'b',
      'r2',
      'e1'
    ])
  })

  it('does not fold running or failed tools', () => {
    const running: ToolItem = { ...tool('r1', 'read'), status: 'running' }
    expect(renderUnits([running, tool('r2', 'read')]).map((unit) => unit.type)).toEqual(['item', 'item'])
  })
})
