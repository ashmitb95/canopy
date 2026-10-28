import { describe, expect, it } from 'vitest'
import { claudeQuota } from '../../src/providers/claude/quota'
import { codexQuota } from '../../src/providers/codex/quota'

const now = new Date('2026-10-29T10:00:00.000Z')

describe('claudeQuota', () => {
  it('reads every unified window', () => {
    const quota = claudeQuota(
      {
        status: 'allowed',
        rateLimitType: 'five_hour',
        unifiedWindows: {
          five_hour: { utilization: 0.32, resetsAt: 1793241600, status: 'allowed' },
          seven_day: { utilization: 0.18, resetsAt: 1793743200, status: 'allowed_warning' }
        }
      },
      now
    )
    expect(quota).toEqual({
      observedAt: '2026-10-29T10:00:00.000Z',
      windows: [
        { label: '5-hour', usedPercent: 32, resetsAt: new Date(1793241600 * 1000).toISOString(), status: 'ok' },
        { label: 'Weekly', usedPercent: 18, resetsAt: new Date(1793743200 * 1000).toISOString(), status: 'warning' }
      ]
    })
  })

  it('falls back to the single window older CLIs report', () => {
    expect(claudeQuota({ status: 'rejected', rateLimitType: 'seven_day_opus', utilization: 1 }, now)?.windows).toEqual([
      { label: 'Weekly (Opus)', usedPercent: 100, status: 'limited' }
    ])
  })

  it('returns null without utilization', () => {
    expect(claudeQuota({ status: 'allowed' }, now)).toBeNull()
  })
})

describe('codexQuota', () => {
  it('labels windows by their length', () => {
    const quota = codexQuota(
      {
        primary: { usedPercent: 85, windowDurationMins: 300, resetsAt: 1795747162 },
        secondary: { usedPercent: 12, windowDurationMins: 10080, resetsAt: null }
      },
      now
    )
    expect(quota?.windows).toEqual([
      { label: '5-hour', usedPercent: 85, resetsAt: new Date(1795747162 * 1000).toISOString(), status: 'warning' },
      { label: 'Weekly', usedPercent: 12, status: 'ok' }
    ])
  })

  it('names a monthly window and marks a full one as limited', () => {
    expect(codexQuota({ primary: { usedPercent: 100, windowDurationMins: 43200 }, secondary: null }, now)?.windows).toEqual([
      { label: 'Monthly', usedPercent: 100, status: 'limited' }
    ])
  })
})
