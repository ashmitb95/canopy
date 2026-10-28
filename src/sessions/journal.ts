import { appendFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs'
import { dirname } from 'node:path'
import type { SessionItem } from '../core/types'

/** Append-only log of item upserts. Streaming produces many upserts per item, so writes are coalesced. */
export class Journal {
  private readonly pending = new Map<string, SessionItem>()
  private timer: NodeJS.Timeout | undefined

  constructor(
    private readonly path: string,
    private readonly delayMs = 250
  ) {}

  append(item: SessionItem): void {
    this.pending.set(item.id, item)
    this.timer ??= setTimeout(() => this.flush(), this.delayMs)
  }

  flush(): void {
    clearTimeout(this.timer)
    this.timer = undefined
    if (this.pending.size === 0) return
    const lines = [...this.pending.values()].map((item) => `${JSON.stringify(item)}\n`).join('')
    this.pending.clear()
    mkdirSync(dirname(this.path), { recursive: true })
    appendFileSync(this.path, lines)
  }

  /** The latest version of every item, in the order items first appeared. */
  static read(path: string): SessionItem[] {
    if (!existsSync(path)) return []
    const items = new Map<string, SessionItem>()
    for (const line of readFileSync(path, 'utf8').split('\n')) {
      if (!line) continue
      try {
        const item = JSON.parse(line) as SessionItem
        items.set(item.id, item)
      } catch {
        // A crash mid-write leaves a partial last line.
      }
    }
    return [...items.values()]
  }
}
