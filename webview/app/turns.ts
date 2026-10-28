import type { AssistantMessage, DiffItem, SessionItem, TurnItem, UserMessage } from '../../src/core/types'

export type TurnFooter = {
  at?: string
  prompt?: UserMessage
  reply?: AssistantMessage
  diffs: DiffItem[]
  files: number
  added: number
  removed: number
}

const lines = (text: string | null) => (text ? text.split('\n').length : 0)

/** Splits the transcript at user messages; each ended turn gets a footer keyed by its last item's id. */
export function turnFooters(items: SessionItem[]): Map<string, TurnFooter> {
  const footers = new Map<string, TurnFooter>()
  let segment: SessionItem[] = []
  const close = () => {
    const turn = segment.find((item): item is TurnItem => item.kind === 'turn')
    const last = segment.at(-1)
    if (turn?.state === 'ended' && last) {
      const diffs = segment.filter((item): item is DiffItem => item.kind === 'diff')
      footers.set(last.id, {
        at: turn.at,
        prompt: segment.find((item): item is UserMessage => item.kind === 'message' && item.role === 'user'),
        reply: segment.findLast((item): item is AssistantMessage => item.kind === 'message' && item.role === 'assistant'),
        diffs,
        files: new Set(diffs.map((diff) => diff.path)).size,
        added: diffs.reduce((sum, diff) => sum + lines(diff.newText), 0),
        removed: diffs.reduce((sum, diff) => sum + lines(diff.oldText), 0)
      })
    }
    segment = []
  }
  for (const item of items) {
    if (item.kind === 'message' && item.role === 'user') close()
    segment.push(item)
  }
  close()
  return footers
}
