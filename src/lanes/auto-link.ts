import { resolve } from 'node:path'
import type { Disposable } from '../core/emitter'
import type { SessionManager } from '../sessions/manager'
import { laneFromPaths } from './lanes'
import type { LaneTracker } from './tracker'

/** A chat on no lane joins the one lane its edits landed in. Agents may branch on their own; this keeps up. */
export async function linkChat(manager: SessionManager, tracker: LaneTracker, sessionId: string): Promise<void> {
  const record = manager.list().find((entry) => entry.record.id === sessionId)?.record
  if (!record || record.laneId) return
  const files = manager.diffPaths(sessionId).map((path) => resolve(tracker.root, path))
  const lane = laneFromPaths(tracker.repos, files)
  if (lane) await manager.setLane(sessionId, lane)
}

/** After each turn: refresh what Git shows, then link. */
export function autoLink(manager: SessionManager, tracker: LaneTracker): Disposable {
  return manager.onAttention(({ sessionId, reason }) => {
    if (reason !== 'turn-ended') return
    void tracker.refresh().then(() => linkChat(manager, tracker, sessionId))
  })
}
