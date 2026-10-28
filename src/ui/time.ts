const UNITS: [label: string, ms: number][] = [
  ['w', 7 * 86_400_000],
  ['d', 86_400_000],
  ['h', 3_600_000],
  ['m', 60_000]
]

/** Compact age for lists: now, 5m, 3h, 2d, 5w. */
export function relativeTime(iso: string, now = Date.now()): string {
  const elapsed = now - Date.parse(iso)
  for (const [label, ms] of UNITS) {
    if (elapsed >= ms) return `${Math.floor(elapsed / ms)}${label}`
  }
  return 'now'
}
