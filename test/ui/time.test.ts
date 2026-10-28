import { describe, expect, it } from 'vitest'
import { relativeTime } from '../../src/ui/time'

const now = Date.parse('2026-10-28T12:00:00.000Z')
const ago = (ms: number) => new Date(now - ms).toISOString()

describe('relativeTime', () => {
  it('labels recent times compactly', () => {
    expect(relativeTime(ago(20_000), now)).toBe('now')
    expect(relativeTime(ago(5 * 60_000), now)).toBe('5m')
    expect(relativeTime(ago(3 * 3_600_000), now)).toBe('3h')
    expect(relativeTime(ago(2 * 86_400_000), now)).toBe('2d')
    expect(relativeTime(ago(40 * 86_400_000), now)).toBe('5w')
  })
})
