import { describe, expect, it } from 'vitest'
import { Emitter } from '../../src/core/emitter'

describe('Emitter', () => {
  it('delivers values to listeners until they are disposed', () => {
    const emitter = new Emitter<number>()
    const seen: number[] = []
    const subscription = emitter.event((value) => seen.push(value))
    emitter.fire(1)
    subscription.dispose()
    emitter.fire(2)
    expect(seen).toEqual([1])
  })

  it('supports several listeners', () => {
    const emitter = new Emitter<string>()
    const seen: string[] = []
    emitter.event((value) => seen.push(`a:${value}`))
    emitter.event((value) => seen.push(`b:${value}`))
    emitter.fire('x')
    expect(seen).toEqual(['a:x', 'b:x'])
  })
})
