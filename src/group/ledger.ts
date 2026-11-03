import { appendFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs'
import { dirname } from 'node:path'

export type LedgerEntry = { seq: number; from: string; to?: string; text: string; at: string }

/** One chat's shared record: what was said to and by each agent. Append-only, kept on disk. */
export class Ledger {
  private readonly entries: LedgerEntry[]

  constructor(private readonly path: string) {
    this.entries = existsSync(path)
      ? readFileSync(path, 'utf8')
          .split('\n')
          .filter(Boolean)
          .map((line) => JSON.parse(line) as LedgerEntry)
      : []
  }

  get length(): number {
    return this.entries.length
  }

  all(): readonly LedgerEntry[] {
    return this.entries
  }

  append(entry: { from: string; to?: string; text: string }): LedgerEntry {
    const full: LedgerEntry = { ...entry, seq: this.entries.length, at: new Date().toISOString() }
    mkdirSync(dirname(this.path), { recursive: true })
    appendFileSync(this.path, `${JSON.stringify(full)}\n`)
    this.entries.push(full)
    return full
  }

  /** What an agent missed from a position on: not its own replies, and not the message it is about to receive. */
  missed(cursor: number, agent: string, except?: number): LedgerEntry[] {
    return this.entries.slice(cursor).filter((entry) => entry.from !== agent && entry.seq !== except)
  }
}

/** How much of what an agent missed is sent inline; the rest stays in the ledger file for it to read. */
export const CATCH_UP_LIMIT = 16_000

export function catchUpText(entries: LedgerEntry[], ledgerPath?: string, limit = CATCH_UP_LIMIT): string {
  if (entries.length === 0) return ''
  const lines = entries.map((entry) => `[${entry.from}${entry.to ? ` to ${entry.to}` : ''}] ${entry.text}`)
  // The newest messages matter most, so older ones are dropped first, with a pointer to the full record.
  const kept: string[] = []
  let size = 0
  for (const line of [...lines].reverse()) {
    if (size + line.length > limit && kept.length > 0) break
    kept.unshift(line.length > limit ? `${line.slice(0, limit)}…` : line)
    size += line.length
  }
  const dropped = lines.length - kept.length
  const note = dropped > 0 ? `(${dropped} earlier message${dropped === 1 ? '' : 's'} left out for length${ledgerPath ? `; the full record is in ${ledgerPath}, one JSON object per line` : ''}.)\n` : ''
  return `<chat-so-far>\nOther participants in this chat said this since your last turn:\n${note}${kept.join('\n')}\n</chat-so-far>`
}
