import type { PromptPart } from '../../../src/core/types'

const listeners = new Set<(parts: PromptPart[]) => void>()

/** Moves a queued message back into the composer for editing. */
export function editInComposer(parts: PromptPart[]): void {
  for (const listener of listeners) listener(parts)
}

export function onEdit(listener: (parts: PromptPart[]) => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
