import { describe, expect, it } from 'vitest'
import { recentSessions } from '../../src/ui/unread'

const day = 86_400_000
const at = (daysAgo: number) => new Date(Date.UTC(2026, 9, 30) - daysAgo * day).toISOString()

describe('recentSessions', () => {
  it('keeps chats from the last 30 days, at most 100', () => {
    const records = [{ updatedAt: at(1) }, { updatedAt: at(29) }, { updatedAt: at(31) }]
    expect(recentSessions(records, Date.UTC(2026, 9, 30))).toEqual([{ updatedAt: at(1) }, { updatedAt: at(29) }])
    const many = Array.from({ length: 150 }, () => ({ updatedAt: at(0) }))
    expect(recentSessions(many, Date.UTC(2026, 9, 30))).toHaveLength(100)
  })
})
