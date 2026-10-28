import type { PromptPart } from '../../src/core/types'

export function promptText(parts: PromptPart[]): string {
  return parts
    .filter((part): part is Extract<PromptPart, { type: 'text' }> => part.type === 'text')
    .map((part) => part.text)
    .join('\n\n')
}

export function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path
}

export function elapsed(ms: number): string {
  const seconds = Math.floor(ms / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

const SHORT_WINDOWS: Record<string, string> = { '5-hour': '5h', Weekly: 'wk', Monthly: 'mo' }

export function shortWindow(label: string): string {
  return SHORT_WINDOWS[label] ?? label
}

export function quotaAge(observedAt: string, now: number): string {
  const minutes = Math.floor((now - Date.parse(observedAt)) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  return hours < 24 ? `${hours}h ago` : `${Math.floor(hours / 24)}d ago`
}

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

/** "at 3:10 PM" today, else "Monday at 3:10 PM". */
export function resetTime(iso: string, now: number): string {
  const date = new Date(iso)
  const time = clockTime(iso)
  return date.toDateString() === new Date(now).toDateString()
    ? `at ${time}`
    : `${date.toLocaleDateString([], { weekday: 'long' })} at ${time}`
}
