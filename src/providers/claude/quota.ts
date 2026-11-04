import type { Quota } from '../../core/types'

type Window = { utilization?: number; resetsAt?: number; status?: string }

/** The parts of `rate_limit_event.rate_limit_info` Canopy reads; `unifiedWindows` is newer than the SDK's types. */
export type RateLimitInfo = Window & { rateLimitType?: string; unifiedWindows?: Record<string, Window> }

const LABELS: Record<string, string> = {
  five_hour: '5-hour',
  seven_day: 'Weekly',
  seven_day_opus: 'Weekly (Opus)',
  seven_day_sonnet: 'Weekly (Sonnet)'
}

const STATUS: Record<string, Quota['windows'][number]['status']> = {
  allowed: 'ok',
  allowed_warning: 'warning',
  rejected: 'limited'
}

export function claudeQuota(info: RateLimitInfo, now = new Date()): Quota | null {
  const windows = info.unifiedWindows ?? (info.rateLimitType ? { [info.rateLimitType]: info } : {})
  const parsed = Object.entries(windows).flatMap(([type, window]) =>
    window.utilization === undefined
      ? []
      : [
          {
            label: LABELS[type] ?? type.replaceAll('_', ' '),
            usedPercent: Math.round(window.utilization * 100),
            ...(window.resetsAt ? { resetsAt: new Date(window.resetsAt * 1000).toISOString() } : {}),
            status: STATUS[window.status ?? ''] ?? 'ok'
          }
        ]
  )
  return parsed.length > 0 ? { observedAt: now.toISOString(), windows: parsed } : null
}
