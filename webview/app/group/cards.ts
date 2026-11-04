import type { TimelineItem } from '../../../src/group/chat'

const isUserMessage = (entry: TimelineItem) => entry.item.kind === 'message' && entry.item.role === 'user'

/** A delegate's own work shows in its card; the conversation keeps the user's messages and questions. */
export function inCard(entry: TimelineItem): boolean {
  return Boolean(entry.delegation) && !isUserMessage(entry) && entry.item.kind !== 'question'
}

/**
 * Each delegation's own items, and where its card goes: after the last message that started or resumed it,
 * so the newest work is always lowest in the chat.
 */
export function placeCards(items: TimelineItem[]): { own: Map<string, TimelineItem[]>; anchors: Map<number, string[]> } {
  const own = new Map<string, TimelineItem[]>()
  const at = new Map<string, number>()
  items.forEach((entry, index) => {
    const id = entry.delegation
    if (!id) return
    if (isUserMessage(entry) || !at.has(id)) at.set(id, index)
    if (inCard(entry)) own.set(id, [...(own.get(id) ?? []), entry])
  })
  const anchors = new Map<number, string[]>()
  for (const [id, index] of at) anchors.set(index, [...(anchors.get(index) ?? []), id])
  return { own, anchors }
}
