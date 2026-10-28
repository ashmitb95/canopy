import { describe, expect, it } from 'vitest'
import { elapsed, quotaAge, shortWindow } from '../../webview/app/format'

describe('format', () => {
  it('formats elapsed time', () => {
    expect(elapsed(12_000)).toBe('12s')
    expect(elapsed(72_000)).toBe('1m 12s')
    expect(elapsed(3_780_000)).toBe('1h 3m')
  })

  it('shortens window labels', () => {
    expect(shortWindow('5-hour')).toBe('5h')
    expect(shortWindow('Weekly')).toBe('wk')
    expect(shortWindow('Monthly')).toBe('mo')
    expect(shortWindow('Weekly (Opus)')).toBe('Weekly (Opus)')
  })

  it('says how old a quota reading is', () => {
    const now = Date.parse('2026-10-29T10:00:00.000Z')
    expect(quotaAge('2026-10-29T09:59:50.000Z', now)).toBe('just now')
    expect(quotaAge('2026-10-29T09:57:00.000Z', now)).toBe('3m ago')
  })
})
