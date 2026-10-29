import type { PromptPart } from '../core/types'
import type { SessionRecord } from '../sessions/store'
import { buildBrief, buildDelta, seenOf } from './brief'
import { deriveLanes } from './lanes'
import type { LaneMemory } from './memory'
import type { LaneTracker } from './tracker'

/**
 * The session manager's `decorate` hook: a chat's first prompt on its lane carries the lane brief; later prompts carry
 * a lane update when something changed. What the chat has now seen is kept on `record.laneSeen`.
 */
export function laneContext(tracker: LaneTracker, memory: LaneMemory) {
  return async (record: SessionRecord, parts: PromptPart[]): Promise<PromptPart[]> => {
    const name = record.laneId
    if (!name) return parts
    await tracker.refresh()
    const lane = deriveLanes(tracker.repos, [name]).find((candidate) => candidate.name === name)
    if (!lane) return parts
    memory.ensure(name)
    const planUpdated = memory.planUpdated(name)
    const text =
      record.laneSeen?.lane === name
        ? buildDelta(tracker.root, lane, record.laneSeen, planUpdated)
        : buildBrief({
            root: tracker.root,
            lane,
            goal: memory.goal(name),
            plan: { path: memory.planPath(name), ...(planUpdated ? { updated: planUpdated } : {}) },
            notes: { path: memory.notesPath(name), entries: memory.noteCount(name) },
            earlier: memory.summaries(name).filter((summary) => summary.chatId !== record.id)
          })
    record.laneSeen = seenOf(lane)
    return text ? [...parts, { type: 'text', text }] : parts
  }
}
