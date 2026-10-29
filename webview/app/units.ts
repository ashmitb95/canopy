import type { SessionItem, ToolItem } from '../../src/core/types'

/** Items whose parent is in the transcript go under it (a subagent's steps under the tool that started it). */
export function nestItems(items: SessionItem[]): { top: SessionItem[]; children: Map<string, SessionItem[]> } {
  const ids = new Set(items.map((item) => item.id))
  const children = new Map<string, SessionItem[]>()
  const top: SessionItem[] = []
  for (const item of items) {
    const parentId = 'parentId' in item ? item.parentId : undefined
    if (parentId && ids.has(parentId)) children.set(parentId, [...(children.get(parentId) ?? []), item])
    else top.push(item)
  }
  return { top, children }
}

export type RenderUnit = { type: 'item'; item: SessionItem } | { type: 'explored'; items: ToolItem[] }

const EXPLORING = new Set<ToolItem['toolKind']>(['read', 'search', 'fetch'])
const explores = (item: SessionItem): item is ToolItem => item.kind === 'tool' && item.status === 'done' && EXPLORING.has(item.toolKind)

/** Two or more finished reads, searches, or fetches in a row read as one "Explored N items" row. */
export function renderUnits(items: SessionItem[]): RenderUnit[] {
  const units: RenderUnit[] = []
  let run: ToolItem[] = []
  const flush = () => {
    if (run.length >= 2) units.push({ type: 'explored', items: run })
    else units.push(...run.map((item) => ({ type: 'item' as const, item })))
    run = []
  }
  for (const item of items) {
    if (explores(item)) {
      run.push(item)
      continue
    }
    flush()
    units.push({ type: 'item', item })
  }
  flush()
  return units
}
