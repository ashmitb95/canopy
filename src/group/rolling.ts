// The raw session stream as compact lines, for a live view of what an agent is doing.
import type { SessionItem } from '../core/types'

export type RollingLine = { id: string; kind: 'text' | 'thought' | 'tool' | 'output' | 'plan' | 'notice'; text: string; live: boolean; failed?: boolean; stat?: string }

const OUTPUT_LINES = 2
const WIDTH = 96

const clip = (text: string) => (text.length > WIDTH ? `${text.slice(0, WIDTH - 1)}…` : text)

/** The window shows prose, not markup. */
export const plain = (text: string) => text.trim().replace(/^[-*]\s+/, '').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/\*\*/g, '').replace(/`/g, '')

/** One line for a tool: the command or the file, without provider-specific wording. */
export function toolLine(title: string): string {
  const command = /^(?:Bash|Run|Shell|Command Execute)\s+(.+)$/s.exec(title)
  if (command) return `$ ${command[1].split('\n')[0]}`
  const file = /^(Read|Write|Edit|Grep|Glob|Search|Fetch)\s+(.+)$/s.exec(title)
  if (file) return `${file[1].toLowerCase()} ${file[2].replace(/^\.\//, '').replace(/, \.\//g, ', ')}`
  const listing = /^list files list\s+(.+)$/i.exec(title)
  if (listing) return `list ${listing[1]}`
  return title.toLowerCase()
}

function lineStat(oldText: string | null, newText: string): string {
  const before = oldText === null || oldText === '' ? [] : oldText.split('\n')
  const after = newText === '' ? [] : newText.split('\n')
  const seen = new Map<string, number>()
  for (const line of before) seen.set(line, (seen.get(line) ?? 0) + 1)
  let kept = 0
  for (const line of after) {
    const count = seen.get(line) ?? 0
    if (count > 0) {
      kept += 1
      seen.set(line, count - 1)
    }
  }
  return `+${after.length - kept} −${before.length - kept}`
}

/** Items arrive as repeated snapshots by id, in stream order: the latest of each wins, at its first position. */
export function rollingLines(stream: SessionItem[], root?: string): RollingLine[] {
  const short = (text: string) => (root ? text.split(`${root}/`).join('') : text)
  const latest = new Map<string, SessionItem>()
  for (const item of stream) latest.set(item.id, item)
  const diffs = [...latest.values()].filter((item) => item.kind === 'diff')
  const lines: RollingLine[] = []
  for (const item of latest.values()) {
    if (item.kind === 'message' && item.role === 'assistant' && item.text.trim()) {
      for (const [index, paragraph] of item.text.trim().split(/\n+/).entries()) lines.push({ id: `${item.id}:${index}`, kind: 'text', text: plain(paragraph), live: item.streaming })
    }
    if (item.kind === 'thought' && item.text.trim()) lines.push({ id: item.id, kind: 'thought', text: item.text.trim().replace(/\s+/g, ' '), live: item.streaming })
    if (item.kind === 'plan') {
      const done = item.entries.filter((entry) => entry.status === 'done').length
      lines.push({ id: item.id, kind: 'plan', text: `step ${Math.min(done + 1, item.entries.length)} of ${item.entries.length}`, live: false })
    }
    if (item.kind === 'notice') lines.push({ id: item.id, kind: 'notice', text: item.text, live: false })
    if (item.kind === 'approval' && item.resolved) {
      const choice = item.options.find((option) => option.id === item.resolved)?.label ?? item.resolved
      lines.push({ id: item.id, kind: 'notice', text: `${item.title} · ${choice}`, live: false })
    }
    if (item.kind === 'tool') {
      const diff = item.toolKind === 'edit' && item.paths?.length === 1 ? diffs.find((candidate) => candidate.kind === 'diff' && candidate.path === item.paths?.[0]) : undefined
      const stat = diff?.kind === 'diff' ? lineStat(diff.oldText, diff.newText) : undefined
      lines.push({ id: item.id, kind: 'tool', text: clip(short(toolLine(item.title))), live: item.status === 'running', failed: item.status === 'failed', ...(stat ? { stat } : {}) })
      if (item.toolKind === 'execute' && item.output?.trim()) {
        const tail = item.output.trim().split('\n').slice(-OUTPUT_LINES)
        tail.forEach((text, index) => lines.push({ id: `${item.id}:out:${index}`, kind: 'output', text: clip(text), live: false }))
      }
    }
  }
  return lines
}

/** The window at a moment: what had arrived by then. */
export function frameAt(events: { t: number; item: SessionItem }[], t: number): RollingLine[] {
  return rollingLines(events.filter((event) => event.t <= t).map((event) => event.item))
}
