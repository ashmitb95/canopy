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

export function catchUpText(entries: LedgerEntry[]): string {
  if (entries.length === 0) return ''
  const lines = entries.map((entry) => `[${entry.from}${entry.to ? ` to ${entry.to}` : ''}] ${entry.text}`)
  return `<chat-so-far>\nOther participants in this chat said this since your last turn:\n${lines.join('\n')}\n</chat-so-far>`
}
