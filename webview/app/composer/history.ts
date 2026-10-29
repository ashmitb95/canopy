import type { PromptPart } from '../../../src/core/types'

/** ↑/↓ through a chat's earlier prompts: up goes back from the newest, down returns toward an empty composer. */
export class History {
  private index = -1

  constructor(private readonly entries: PromptPart[][]) {}

  up(): PromptPart[] | undefined {
    if (this.entries.length === 0) return undefined
    this.index = Math.min(this.index + 1, this.entries.length - 1)
    return this.entries[this.entries.length - 1 - this.index]
  }

  /** The next newer prompt, `[]` when stepping past the newest, undefined when not browsing. */
  down(): PromptPart[] | undefined {
    if (this.index < 0) return undefined
    this.index--
    return this.index < 0 ? [] : this.entries[this.entries.length - 1 - this.index]
  }
}
