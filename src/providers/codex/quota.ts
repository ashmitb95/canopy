import type { Quota } from '../../core/types'

type Window = { usedPercent: number; windowDurationMins?: number | null; resetsAt?: number | null } | null | undefined

export function codexQuota(rateLimits: { primary?: Window; secondary?: Window }, now = new Date()): Quota | null {
  const windows = [rateLimits.primary, rateLimits.secondary].flatMap((window) =>
    window
      ? [
          {
            label: windowLabel(window.windowDurationMins),
            usedPercent: Math.round(window.usedPercent),
            ...(window.resetsAt ? { resetsAt: new Date(window.resetsAt * 1000).toISOString() } : {}),
            status: status(window.usedPercent)
          }
        ]
      : []
  )
  return windows.length > 0 ? { observedAt: now.toISOString(), windows } : null
}

function status(usedPercent: number): Quota['windows'][number]['status'] {
  return usedPercent >= 100 ? 'limited' : usedPercent >= 80 ? 'warning' : 'ok'
}

function windowLabel(minutes: number | null | undefined): string {
  if (!minutes) return 'Usage'
  if (minutes === 300) return '5-hour'
  if (minutes === 10080) return 'Weekly'
  if (minutes >= 40320 && minutes <= 44640) return 'Monthly'
  return minutes % 1440 === 0 ? `${minutes / 1440}-day` : `${Math.round(minutes / 60)}-hour`
}
